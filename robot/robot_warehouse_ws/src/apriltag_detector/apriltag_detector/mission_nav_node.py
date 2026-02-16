#!/usr/bin/env python3
import math
import time
import requests

import rclpy
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.action import ActionClient

from std_srvs.srv import Trigger
from std_msgs.msg import String
from geometry_msgs.msg import PoseStamped, Pose2D, PoseWithCovarianceStamped

from nav2_msgs.action import NavigateToPose
from action_msgs.msg import GoalStatus


def yaw_to_quat(yaw: float):
    return (0.0, 0.0, math.sin(yaw * 0.5), math.cos(yaw * 0.5))


def quat_to_yaw(x, y, z, w):
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


class MissionNavNode(Node):
    """
    MissionNavNode:
      - Получает точки из backend по REST при каждом вызове сервисов:
          /mission/nav_pick  -> GET /api/robot/nav/pick?robotId=...
          /mission/nav_place -> GET /api/robot/nav/place?robotId=...
      - Навигация через Nav2 action NavigateToPose:
          SUCCESS = GoalStatus.STATUS_SUCCEEDED (то же, что пишет bt_navigator)
      - Публикует /mission/state для дебага
      - (Опционально) подписывается на AMCL только для логов/диагностики, но не влияет на SUCCESS
    """

    def __init__(self):
        super().__init__("mission_nav_node")
        self.cb = ReentrantCallbackGroup()

        # --- goal publication (debug) ---
        self.declare_parameter("goal_pose_topic", "/robot1/goal_pose")
        self.declare_parameter("frame_id", "map")
        self.declare_parameter("publish_goal_topic", True)

        # --- Nav2 action ---
        # Проверь ros2 action list | grep navigate
        self.declare_parameter("nav_action_name", "/robot1/navigate_to_pose")
        self.declare_parameter("nav_timeout_sec", 170.0)

        # --- AMCL (optional debug only) ---
        self.declare_parameter("amcl_pose_topic", "/amcl_pose")

        # --- REST ---
        self.declare_parameter("rest_enable", True)
        self.declare_parameter("rest_base_url", "http://192.168.0.107:8080")
        self.declare_parameter("rest_timeout_sec", 1.0)
        self.declare_parameter("rest_robot_id", "robot1")
        self.declare_parameter("rest_pick_path", "/api/robot/nav/pick")
        self.declare_parameter("rest_place_path", "/api/robot/nav/place")

        # --- read params ---
        self.goal_topic = str(self.get_parameter("goal_pose_topic").value)
        self.frame_id = str(self.get_parameter("frame_id").value)
        self.publish_goal_topic = bool(self.get_parameter("publish_goal_topic").value)

        self.nav_action_name = str(self.get_parameter("nav_action_name").value)
        self.nav_timeout = float(self.get_parameter("nav_timeout_sec").value)

        self.amcl_topic = str(self.get_parameter("amcl_pose_topic").value)

        self.rest_enable = bool(self.get_parameter("rest_enable").value)
        self.rest_base_url = str(self.get_parameter("rest_base_url").value).rstrip("/")
        self.rest_timeout = float(self.get_parameter("rest_timeout_sec").value)
        self.rest_robot_id = str(self.get_parameter("rest_robot_id").value).strip()
        self.rest_pick_path = str(self.get_parameter("rest_pick_path").value)
        self.rest_place_path = str(self.get_parameter("rest_place_path").value)

        # --- stored targets ---
        self.pick = Pose2D()
        self.place = Pose2D()

        # --- latest amcl (debug only) ---
        self.amcl_ok = False
        self.amcl_x = 0.0
        self.amcl_y = 0.0
        self.amcl_yaw = 0.0
        self.amcl_stamp = 0.0

        # --- pubs/subs ---
        self.pub_goal = self.create_publisher(PoseStamped, self.goal_topic, 10)
        self.pub_state = self.create_publisher(String, "/mission/state", 10)

        # debug overrides
        self.create_subscription(Pose2D, "/mission/pick_pose2d", self.on_pick_pose, 10, callback_group=self.cb)
        self.create_subscription(Pose2D, "/mission/place_pose2d", self.on_place_pose, 10, callback_group=self.cb)

        # AMCL debug
        self.create_subscription(PoseWithCovarianceStamped, self.amcl_topic, self.on_amcl, 10, callback_group=self.cb)

        # --- Nav2 action client ---
        self.nav_client = ActionClient(self, NavigateToPose, self.nav_action_name, callback_group=self.cb)

        # --- services ---
        self.create_service(Trigger, "/mission/nav_pick", self.srv_nav_pick, callback_group=self.cb)
        self.create_service(Trigger, "/mission/nav_place", self.srv_nav_place, callback_group=self.cb)

        self._publish_state("READY")
        self.get_logger().info(
            f"MissionNavNode started. action={self.nav_action_name} goal_topic={self.goal_topic} "
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
        self.get_logger().info(f"Updated PICK from topic: x={msg.x:.2f} y={msg.y:.2f} yaw={msg.theta:.2f}")

    def on_place_pose(self, msg: Pose2D):
        self.place = msg
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
        Expected JSON (your backend):
          {"mapX":..., "mapY":..., "mapYaw":...}
        Also supports:
          {"x":..., "y":..., "yaw":...} or {"theta":...}
        If 204 -> None
        """
        if not self.rest_enable:
            return None

        url = f"{self.rest_base_url}{path}"
        r = requests.get(url, params={"robotId": self.rest_robot_id}, timeout=self.rest_timeout)

        if r.status_code == 204:
            return None

        try:
            r.raise_for_status()
        except Exception:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")

        try:
            data = r.json()
        except Exception:
            raise RuntimeError(f"Bad JSON: {r.text[:300]}")

        def get_any(d, *keys):
            for k in keys:
                if k in d and d[k] is not None:
                    return d[k]
            return None

        x = get_any(data, "mapX", "x")
        y = get_any(data, "mapY", "y")
        yaw = get_any(data, "mapYaw", "yaw", "theta")

        if x is None or y is None or yaw is None:
            raise KeyError(f"Missing fields in nav pose: keys={list(data.keys())}, body={str(data)[:200]}")

        p = Pose2D()
        p.x = float(x)
        p.y = float(y)
        p.theta = float(yaw)
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

    def _navigate_to(self, target: Pose2D, label: str):
        """
        Navigation success is based on Nav2 action result:
          STATUS_SUCCEEDED -> success
        """
        # wait nav2 server
        if not self.nav_client.wait_for_server(timeout_sec=2.0):
            self.get_logger().warn(f"Nav2 action server not ready: {self.nav_action_name}")
            self._publish_state(f"NAV_FAIL:{label}:action_not_ready")
            return False, "action_not_ready"

        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = self._pose2d_to_stamped(target)

        # optional debug publish
        if self.publish_goal_topic:
            self.pub_goal.publish(goal_msg.pose)

        self._publish_state(f"NAV_START:{label}")

        # send goal
        send_future = self.nav_client.send_goal_async(goal_msg)

        t_send0 = self._now()
        while rclpy.ok() and not send_future.done():
            if (self._now() - t_send0) > 5.0:
                self._publish_state(f"NAV_FAIL:{label}:send_timeout")
                return False, "send_timeout"
            time.sleep(0.05)

        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            self._publish_state(f"NAV_FAIL:{label}:rejected")
            return False, "rejected"

        # wait result
        result_future = goal_handle.get_result_async()

        t0 = self._now()
        while rclpy.ok() and not result_future.done():
            if (self._now() - t0) > self.nav_timeout:
                # cancel on timeout
                try:
                    goal_handle.cancel_goal_async()
                except Exception:
                    pass
                self._publish_state(f"NAV_FAIL:{label}:timeout")
                return False, "timeout"
            time.sleep(0.08)

        res = result_future.result()
        status = int(res.status)

        if status == GoalStatus.STATUS_SUCCEEDED:
            self._publish_state(f"NAV_OK:{label}")
            return True, "succeeded"
        elif status == GoalStatus.STATUS_CANCELED:
            self._publish_state(f"NAV_FAIL:{label}:canceled")
            return False, "canceled"
        else:
            self._publish_state(f"NAV_FAIL:{label}:status_{status}")
            return False, f"status_{status}"

    # ---- services ----
    def srv_nav_pick(self, req, resp):
        if self.rest_enable:
            try:
                p = self._fetch_nav_pose(self.rest_pick_path)
                if p is None:
                    resp.success = False
                    resp.message = "no_pick_pose"
                    return resp
                self.pick = p
                self.get_logger().info(f"PICK fetched: x={p.x:.2f} y={p.y:.2f} yaw={p.theta:.2f}")
            except Exception as e:
                self.get_logger().warn(f"Failed to fetch PICK pose: {e}")
                resp.success = False
                resp.message = "pick_fetch_failed"
                return resp
        else:
            self.get_logger().info("REST disabled: using stored PICK pose")

        ok, msg = self._navigate_to(self.pick, "PICK")
        resp.success = bool(ok)
        resp.message = str(msg)
        return resp

    def srv_nav_place(self, req, resp):
        if self.rest_enable:
            try:
                p = self._fetch_nav_pose(self.rest_place_path)
                if p is None:
                    resp.success = False
                    resp.message = "no_active_task"
                    return resp
                self.place = p
                self.get_logger().info(f"PLACE fetched: x={p.x:.2f} y={p.y:.2f} yaw={p.theta:.2f}")
            except Exception as e:
                self.get_logger().warn(f"Failed to fetch PLACE pose: {e}")
                resp.success = False
                resp.message = "place_fetch_failed"
                return resp
        else:
            self.get_logger().info("REST disabled: using stored PLACE pose")

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
