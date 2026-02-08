#!/usr/bin/env python3
import math
import time
import requests
import rclpy
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from std_srvs.srv import Trigger
from std_msgs.msg import String
from geometry_msgs.msg import PoseStamped, Pose2D, PoseWithCovarianceStamped


def yaw_to_quat(yaw: float):
    return (0.0, 0.0, math.sin(yaw * 0.5), math.cos(yaw * 0.5))


def quat_to_yaw(x, y, z, w):
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def ang_wrap(a: float) -> float:
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a


class MissionNavNode(Node):
    """
    MissionNavNode (Variant B):
      - TaskFSM НЕ публикует точки и НЕ “знает” координаты.
      - MissionNav сам получает точки из backend (REST) при каждом вызове сервисов:
          /mission/nav_pick  -> GET /api/robot/nav/pick?robotId=...
          /mission/nav_place -> GET /api/robot/nav/place?robotId=...
        (place endpoint должен вернуть 204, если у робота нет активной IN_PROGRESS задачи)

    Навигация:
      - публикуем PoseStamped в goal_pose_topic (обычно /robot1/goal_pose)
      - ждём “приехали” по amcl_pose_topic (/amcl_pose) по порогам + стабильность + таймаут
    """

    def __init__(self):
        super().__init__("mission_nav_node")
        self.cb = ReentrantCallbackGroup()

        # --- куда отправлять goal ---
        self.declare_parameter("goal_pose_topic", "/robot1/goal_pose")
        self.declare_parameter("amcl_pose_topic", "/amcl_pose")
        self.declare_parameter("frame_id", "map")

        # --- критерии “приехал” ---
        self.declare_parameter("xy_tol_m", 0.25)
        self.declare_parameter("yaw_tol_rad", 0.50)
        self.declare_parameter("stable_sec", 0.8)
        self.declare_parameter("nav_timeout_sec", 170.0)


        # --- REST robot nav endpoints ---
        self.declare_parameter("rest_enable", True)
        self.declare_parameter("rest_base_url", "http://192.168.0.109:8080")
        self.declare_parameter("rest_timeout_sec", 1.0)
        self.declare_parameter("rest_robot_id", "robot1")
        self.declare_parameter("rest_pick_path", "/api/robot/nav/pick")
        self.declare_parameter("rest_place_path", "/api/robot/nav/place")

        # --- read params ---
        self.goal_topic = str(self.get_parameter("goal_pose_topic").value)
        self.amcl_topic = str(self.get_parameter("amcl_pose_topic").value)
        self.frame_id = str(self.get_parameter("frame_id").value)

        self.rest_enable = bool(self.get_parameter("rest_enable").value)
        self.rest_base_url = str(self.get_parameter("rest_base_url").value).rstrip("/")
        self.rest_timeout = float(self.get_parameter("rest_timeout_sec").value)
        self.rest_robot_id = str(self.get_parameter("rest_robot_id").value).strip()
        self.rest_pick_path = str(self.get_parameter("rest_pick_path").value)
        self.rest_place_path = str(self.get_parameter("rest_place_path").value)

        # --- stored targets (fallback + debug) ---
        self.pick = Pose2D()

        self.place = Pose2D()

        self.pick_stamp = self._now()
        self.place_stamp = self._now()

        # --- latest amcl ---
        self.amcl_ok = False
        self.amcl_x = 0.0
        self.amcl_y = 0.0
        self.amcl_yaw = 0.0
        self.amcl_stamp = 0.0

        # --- pubs/subs ---
        self.pub_goal = self.create_publisher(PoseStamped, self.goal_topic, 10)
        self.pub_state = self.create_publisher(String, "/mission/state", 10)

        # optional: manual override via topics (debug only)
        self.create_subscription(Pose2D, "/mission/pick_pose2d", self.on_pick_pose, 10, callback_group=self.cb)
        self.create_subscription(Pose2D, "/mission/place_pose2d", self.on_place_pose, 10, callback_group=self.cb)

        self.create_subscription(PoseWithCovarianceStamped, self.amcl_topic, self.on_amcl, 10, callback_group=self.cb)

        # --- services ---
        self.create_service(Trigger, "/mission/nav_pick", self.srv_nav_pick, callback_group=self.cb)
        self.create_service(Trigger, "/mission/nav_place", self.srv_nav_place, callback_group=self.cb)

        self._publish_state("READY")
        self.get_logger().info(
            f"MissionNavNode started. goal_topic={self.goal_topic} amcl_topic={self.amcl_topic} "
            f"REST={'ON' if self.rest_enable else 'OFF'} robotId={self.rest_robot_id}"
        )

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _publish_state(self, s: str):
        m = String()
        m.data = s
        self.pub_state.publish(m)

    # ---- debug topic overrides ----
    def on_pick_pose(self, msg: Pose2D):
        self.pick = msg
        self.pick_stamp = self._now()
        self.get_logger().info(f"Updated PICK from topic: x={msg.x:.2f} y={msg.y:.2f} yaw={msg.theta:.2f}")

    def on_place_pose(self, msg: Pose2D):
        self.place = msg
        self.place_stamp = self._now()
        self.get_logger().info(f"Updated PLACE from topic: x={msg.x:.2f} y={msg.y:.2f} yaw={msg.theta:.2f}")

    def on_amcl(self, msg: PoseWithCovarianceStamped):
        p = msg.pose.pose.position
        o = msg.pose.pose.orientation
        self.amcl_x = float(p.x)
        self.amcl_y = float(p.y)
        self.amcl_yaw = quat_to_yaw(o.x, o.y, o.z, o.w)
        self.amcl_stamp = self._now()
        self.amcl_ok = True

    # ---- REST ----
    def _fetch_nav_pose(self, path: str):
        """
        GET {base}{path}?robotId=...
        Expected JSON: {"x":..., "y":..., "yaw":...}
        If 204 -> return None
        """
        if not self.rest_enable:
            return None

        url = f"{self.rest_base_url}{path}"
        r = requests.get(url, params={"robotId": self.rest_robot_id}, timeout=self.rest_timeout)

        if r.status_code == 204:
            return None

        r.raise_for_status()
        data = r.json()

        p = Pose2D()
        p.x = float(data["x"])
        p.y = float(data["y"])
        p.theta = float(data["yaw"])
        return p

    # ---- helpers ----
    def _pose2d_to_stamped(self, p2: Pose2D) -> PoseStamped:
        ps = PoseStamped()
        ps.header.frame_id = self.frame_id
        ps.header.stamp = self.get_clock().now().to_msg()
        ps.pose.position.x = float(p2.x)
        ps.pose.position.y = float(p2.y)
        ps.pose.position.z = 0.0
        qx, qy, qz, qw = yaw_to_quat(float(p2.theta))
        ps.pose.orientation.x = qx
        ps.pose.orientation.y = qy
        ps.pose.orientation.z = qz
        ps.pose.orientation.w = qw
        return ps

    def _wait_arrival(self, target: Pose2D, label: str):
        xy_tol = float(self.get_parameter("xy_tol_m").value)
        yaw_tol = float(self.get_parameter("yaw_tol_rad").value)
        stable_sec = float(self.get_parameter("stable_sec").value)
        timeout = float(self.get_parameter("nav_timeout_sec").value)

        t0 = self._now()
        within_since = None

        while rclpy.ok():
            now = self._now()
            if (now - t0) > timeout:
                return False, "timeout"

            if not self.amcl_ok:
                time.sleep(0.05)
                continue

            dx = self.amcl_x - float(target.x)
            dy = self.amcl_y - float(target.y)
            dist = math.hypot(dx, dy)
            dyaw = ang_wrap(self.amcl_yaw - float(target.theta))

            ok = (dist <= xy_tol) and (abs(dyaw) <= yaw_tol)

            if ok:
                if within_since is None:
                    within_since = now
                if (now - within_since) >= stable_sec:
                    return True, "arrived"
            else:
                within_since = None

            time.sleep(0.08)

    def _navigate_to(self, target: Pose2D, label: str):
        goal = self._pose2d_to_stamped(target)
        self._publish_state(f"NAV_START:{label}")
        self.pub_goal.publish(goal)

        ok, msg = self._wait_arrival(target, label)
        if ok:
            self._publish_state(f"NAV_OK:{label}")
        else:
            self._publish_state(f"NAV_FAIL:{label}:{msg}")
        return ok, msg

    # ---- services ----
    def srv_nav_pick(self, req, resp):
        # fetch pick pose from backend
        if self.rest_enable:
            try:
                p = self._fetch_nav_pose(self.rest_pick_path)
                if p is None:
                    resp.success = False
                    resp.message = "no_pick_pose"
                    return resp
                self.pick = p
                self.pick_stamp = self._now()
                self.get_logger().info(f"PICK fetched: x={p.x:.2f} y={p.y:.2f} yaw={p.theta:.2f}")
            except Exception as e:
                self.get_logger().warn(f"Failed to fetch PICK pose: {e}")
                resp.success = False
                resp.message = "pick_fetch_failed"
                return resp
        else:
            self.get_logger().info("REST disabled: using default PICK pose")

        ok, msg = self._navigate_to(self.pick, "PICK")
        resp.success = bool(ok)
        resp.message = str(msg)
        return resp

    def srv_nav_place(self, req, resp):
        # fetch place pose from backend (active task for robot)
        if self.rest_enable:
            try:
                p = self._fetch_nav_pose(self.rest_place_path)
                if p is None:
                    resp.success = False
                    resp.message = "no_active_task"
                    return resp
                self.place = p
                self.place_stamp = self._now()
                self.get_logger().info(f"PLACE fetched: x={p.x:.2f} y={p.y:.2f} yaw={p.theta:.2f}")
            except Exception as e:
                self.get_logger().warn(f"Failed to fetch PLACE pose: {e}")
                resp.success = False
                resp.message = "place_fetch_failed"
                return resp
        else:
            self.get_logger().info("REST disabled: using default PLACE pose")

        ok, msg = self._navigate_to(self.place, "PLACE")
        resp.success = bool(ok)
        resp.message = str(msg)
        return resp


def main():
    rclpy.init()
    node = MissionNavNode()
    ex = MultiThreadedExecutor(num_threads=3)
    ex.add_node(node)
    try:
        ex.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
