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
    # yaw from quaternion
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def ang_wrap(a: float) -> float:
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a


class MissionNavNode(Node):
    """
    Хранит 2 точки (pick/place) В КОДЕ.
    Их можно обновлять в runtime через топики:
      /mission/pick_pose2d   geometry_msgs/Pose2D  {x,y,theta}
      /mission/place_pose2d  geometry_msgs/Pose2D

    Навигация:
      публикуем PoseStamped в /robot1/goal_pose
      и ждём “приехали” по /amcl_pose (по порогам + стабильность + таймаут)

    Сервисы:
      /mission/nav_pick  (Trigger)  -> ехать в pick
      /mission/nav_place (Trigger)  -> ехать в place
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

        # --- дефолтные точки (можешь оставить 0, потом будет приходить из БД) ---
        self.declare_parameter("default_pick_x", -0.1)
        self.declare_parameter("default_pick_y", -1.0)
        self.declare_parameter("default_pick_yaw", -1.57)
        self.declare_parameter("default_place_x", -1.0)
        self.declare_parameter("default_place_y", -1.0)
        self.declare_parameter("default_place_yaw", 3.14)

        # --- REST backend shelves coordinates ---
        self.declare_parameter("rest_enable", True)
        self.declare_parameter("rest_base_url", "http://192.168.0.109:8080")  # на роботе будет IP ПК
        self.declare_parameter("rest_shelves_path", "/api/shelves")
        self.declare_parameter("rest_timeout_sec", 1.0)

        # какие shelves использовать как точки
        self.declare_parameter("pick_shelf_code", "A")
        self.declare_parameter("place_shelf_code", "B")

        self.rest_enable = bool(self.get_parameter("rest_enable").value)
        self.rest_base_url = str(self.get_parameter("rest_base_url").value).rstrip("/")
        self.rest_shelves_path = str(self.get_parameter("rest_shelves_path").value)
        self.rest_timeout = float(self.get_parameter("rest_timeout_sec").value)

        self.pick_shelf_code = str(self.get_parameter("pick_shelf_code").value).strip().upper()
        self.place_shelf_code = str(self.get_parameter("place_shelf_code").value).strip().upper()


        self.goal_topic = str(self.get_parameter("goal_pose_topic").value)
        self.amcl_topic = str(self.get_parameter("amcl_pose_topic").value)
        self.frame_id = str(self.get_parameter("frame_id").value)

        # --- храним цели в переменных ---
        self.pick = Pose2D()
        self.pick.x = float(self.get_parameter("default_pick_x").value)
        self.pick.y = float(self.get_parameter("default_pick_y").value)
        self.pick.theta = float(self.get_parameter("default_pick_yaw").value)

        self.place = Pose2D()
        self.place.x = float(self.get_parameter("default_place_x").value)
        self.place.y = float(self.get_parameter("default_place_y").value)
        self.place.theta = float(self.get_parameter("default_place_yaw").value)

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

        self.create_subscription(Pose2D, "/mission/pick_pose2d", self.on_pick_pose, 10, callback_group=self.cb)
        self.create_subscription(Pose2D, "/mission/place_pose2d", self.on_place_pose, 10, callback_group=self.cb)
        self.create_subscription(PoseWithCovarianceStamped, self.amcl_topic, self.on_amcl, 10, callback_group=self.cb)

        # --- services ---
        self.create_service(Trigger, "/mission/nav_pick", self.srv_nav_pick, callback_group=self.cb)
        self.create_service(Trigger, "/mission/nav_place", self.srv_nav_place, callback_group=self.cb)

        # load pick/place from backend once at startup
        self.load_points_from_backend()

        self._publish_state("READY")
        self.get_logger().info(f"MissionNavNode started. goal_topic={self.goal_topic} amcl_topic={self.amcl_topic}")

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _publish_state(self, s: str):
        m = String()
        m.data = s
        self.pub_state.publish(m)

    # ---- callbacks ----
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

    def _fetch_shelves(self):
        """GET /api/shelves -> returns dict code -> (x,y,yaw)"""
        url = f"{self.rest_base_url}{self.rest_shelves_path}"
        r = requests.get(url, timeout=self.rest_timeout)
        r.raise_for_status()
        data = r.json()

        # Ожидаем список вида:
        # [{"shelfCode":"A","x":1.0,"y":2.0,"yaw":1.57}, ...]
        out = {}
        for it in data:
            code = str(it.get("shelfCode", "")).strip().upper()
            if not code:
                continue
            x = float(it.get("mapX"))
            y = float(it.get("mapY"))
            yaw = float(it.get("mapYaw"))
            out[code] = (x, y, yaw)
        return out

    def load_points_from_backend(self):
        """Load shelves coords and set self.pick/self.place."""
        if not self.rest_enable:
            self.get_logger().info("REST disabled: using default pick/place params")
            return

        try:
            shelves = self._fetch_shelves()
        except Exception as e:
            self.get_logger().warn(f"Failed to fetch shelves from backend: {e}")
            return

        # PICK from shelfCode
        if self.pick_shelf_code in shelves:
            x, y, yaw = shelves[self.pick_shelf_code]
            self.pick.x, self.pick.y, self.pick.theta = x, y, yaw
            self.pick_stamp = self._now()
            self.get_logger().info(
                f"PICK loaded from DB shelf={self.pick_shelf_code}: x={x:.2f} y={y:.2f} yaw={yaw:.2f}"
            )
        else:
            self.get_logger().warn(f"PICK shelfCode={self.pick_shelf_code} not found in DB response")

        # PLACE from shelfCode
        if self.place_shelf_code in shelves:
            x, y, yaw = shelves[self.place_shelf_code]
            self.place.x, self.place.y, self.place.theta = x, y, yaw
            self.place_stamp = self._now()
            self.get_logger().info(
                f"PLACE loaded from DB shelf={self.place_shelf_code}: x={x:.2f} y={y:.2f} yaw={yaw:.2f}"
            )
        else:
            self.get_logger().warn(f"PLACE shelfCode={self.place_shelf_code} not found in DB response")



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
        ok, msg = self._navigate_to(self.pick, "PICK")
        resp.success = bool(ok)
        resp.message = str(msg)
        return resp

    def srv_nav_place(self, req, resp):
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
