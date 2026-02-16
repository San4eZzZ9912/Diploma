#!/usr/bin/env python3
import time
import threading

import rclpy
from rclpy.node import Node

from std_srvs.srv import Trigger
from std_msgs.msg import Bool, String

# Yahboom / Rosmaster
try:
    from Rosmaster_Lib.Rosmaster_Lib import Rosmaster
except Exception:
    Rosmaster = None


class ArmControllerNode(Node):
    """
    PLACE верх/низ:
      - FSM публикует /arm/target_level = "UPPER" или "LOWER"
      - /arm/place выбирает нужную последовательность поз
    """

    def __init__(self):
        super().__init__("arm_controller_node")

        # ---- params ----
        self.declare_parameter("settle_sec", 0.35)
        self.declare_parameter("final_settle_sec", 0.70)
        self.declare_parameter("cmd_repeat", 2)
        self.declare_parameter("cmd_repeat_gap_sec", 0.06)

        # времена шагов (мс)
        self.declare_parameter("pick_pre_ms", 5000)
        self.declare_parameter("pick_grasp_ms", 5000)
        self.declare_parameter("pick_post_ms", 6500)

        self.declare_parameter("place_above_ms", 5000)
        self.declare_parameter("place_pre_ms", 5000)
        self.declare_parameter("place_release_ms", 4500)
        self.declare_parameter("place_post_ms", 6000)

        # ---- state ----
        self.busy = False
        self.has_cube = False
        self.place_level = "UPPER"  # default

        self._seq = []
        self._seq_i = 0
        self._step_deadline = 0.0

        # ---- connect robot ----
        self.car = None
        if Rosmaster is not None:
            try:
                self.car = Rosmaster()
                self.get_logger().info("Rosmaster connected (arm controller)")
            except Exception as e:
                self.get_logger().error(f"Rosmaster connection failed: {e}")

        # ===== ARM POSES =====
        # PICK
        self.arm_home_pick = [93, 180, 0, 0, 90, 30]
        self.arm_pre_pick  = [93, 90, 80, 5, 90, 30]
        self.arm_grasp     = [93, 90, 80, 5, 90, 112]
        self.arm_post_pick = [93, 180, 0, 0, 90, 112]

        # PLACE UPPER (как у тебя)
        self.arm_above_place_upper = [93, 90, 90, 5, 90, 112]
        self.arm_pre_place_upper   = [93, 90, 80, 5, 90, 112]
        self.arm_release_upper     = [93, 90, 80, 5, 90, 30]
        self.arm_post_place_upper  = [93, 180, 0, 0, 90, 30]

        # PLACE LOWER (ПО УМОЛЧАНИЮ = UPPER, потом подстроишь)
        self.arm_above_place_lower = [93, 40, 0, 160, 90, 112]
        self.arm_pre_place_lower   = [93, 40, 0, 147, 90, 112]
        self.arm_release_lower     = [93, 40, 0, 147, 90, 30]
        self.arm_post_place_lower  = [93, 180, 0, 0, 90, 30]

        # ---- topics ----
        self.pub_has_cube = self.create_publisher(Bool, "/arm/has_cube", 10)
        self.pub_busy = self.create_publisher(Bool, "/arm/busy", 10)

        self.create_subscription(String, "/arm/target_level", self.on_target_level, 10)

        # ---- services ----
        self.srv_pick = self.create_service(Trigger, "/arm/pick", self.handle_pick)
        self.srv_place = self.create_service(Trigger, "/arm/place", self.handle_place)

        # ---- timers ----
        self.timer = self.create_timer(0.02, self.update)
        self.status_timer = self.create_timer(0.10, self.publish_status)

        self.get_logger().info("Arm controller node started")
        self._send_pose(self.arm_home_pick, 3000)

    def on_target_level(self, msg: String):
        lvl = (msg.data or "").strip().upper()
        if lvl not in ("UPPER", "LOWER"):
            return
        self.place_level = lvl
        self.get_logger().info(f"ARM target level -> {self.place_level}")

    # ================= SERVICES =================

    def handle_pick(self, request, response):
        if self.busy:
            response.success = False
            response.message = "Arm busy"
            return response
        if self.has_cube:
            response.success = False
            response.message = "Already holding a cube"
            return response

        settle = float(self.get_parameter("settle_sec").value)
        final_settle = float(self.get_parameter("final_settle_sec").value)

        pre_ms = int(self.get_parameter("pick_pre_ms").value)
        grasp_ms = int(self.get_parameter("pick_grasp_ms").value)
        post_ms = int(self.get_parameter("pick_post_ms").value)

        self._seq = [
            {"pose": self.arm_pre_pick,  "ms": pre_ms,   "settle": settle,       "on_finish": None},
            {"pose": self.arm_grasp,     "ms": grasp_ms, "settle": settle,       "on_finish": None},
            {"pose": self.arm_post_pick, "ms": post_ms,  "settle": final_settle, "on_finish": self._mark_cube_taken},
        ]
        self._start_sequence("PICK")

        response.success = True
        response.message = "Pick started"
        return response

    def handle_place(self, request, response):
        if self.busy:
            response.success = False
            response.message = "Arm busy"
            return response
        if not self.has_cube:
            response.success = False
            response.message = "No cube to place"
            return response

        # выбрать позы по уровню
        if self.place_level == "LOWER":
            above = self.arm_above_place_lower
            pre   = self.arm_pre_place_lower
            rel   = self.arm_release_lower
            post  = self.arm_post_place_lower
            seq_name = "PLACE_LOWER"
        else:
            above = self.arm_above_place_upper
            pre   = self.arm_pre_place_upper
            rel   = self.arm_release_upper
            post  = self.arm_post_place_upper
            seq_name = "PLACE_UPPER"

        settle = float(self.get_parameter("settle_sec").value)
        final_settle = float(self.get_parameter("final_settle_sec").value)

        above_ms = int(self.get_parameter("place_above_ms").value)
        pre_ms   = int(self.get_parameter("place_pre_ms").value)
        rel_ms   = int(self.get_parameter("place_release_ms").value)
        post_ms  = int(self.get_parameter("place_post_ms").value)

        self._seq = [
            {"pose": above, "ms": above_ms, "settle": settle,       "on_finish": None},
            {"pose": pre,   "ms": pre_ms,   "settle": settle,       "on_finish": None},
            {"pose": rel,   "ms": rel_ms,   "settle": settle,       "on_finish": None},
            {"pose": post,  "ms": post_ms,  "settle": final_settle, "on_finish": self._mark_cube_released},
        ]
        self._start_sequence(seq_name)

        response.success = True
        response.message = f"{seq_name} started"
        return response

    # ================= UPDATE LOOP =================

    def update(self):
        if not self.busy:
            return
        now = self._now()
        if now < self._step_deadline:
            return

        self._seq_i += 1
        if self._seq_i >= len(self._seq):
            self._finish("Sequence done")
            return
        self._start_step(now)

    # ================= HELPERS =================

    def publish_status(self):
        b1 = Bool(); b1.data = bool(self.has_cube)
        b2 = Bool(); b2.data = bool(self.busy)
        self.pub_has_cube.publish(b1)
        self.pub_busy.publish(b2)

    def _start_sequence(self, name: str):
        self.busy = True
        self._seq_i = 0
        now = self._now()
        self.get_logger().info(f"ARM: start {name}")
        self._start_step(now)

    def _start_step(self, now: float):
        step = self._seq[self._seq_i]
        pose = step["pose"]
        ms = int(step["ms"])
        settle = float(step.get("settle", 0.0))

        self._send_pose(pose, ms)
        self._step_deadline = now + (ms / 1000.0) + max(0.0, settle)

    def _mark_cube_taken(self):
        self.has_cube = True

    def _mark_cube_released(self):
        self.has_cube = False

    def _finish(self, msg: str):
        if self._seq:
            last = self._seq[-1]
            fn = last.get("on_finish", None)
            if callable(fn):
                fn()

        self.busy = False
        self._seq = []
        self._seq_i = 0
        self._step_deadline = 0.0
        self.get_logger().info(f"ARM: {msg} (busy=False has_cube={self.has_cube})")

    def _send_pose(self, pose, run_time_ms: int):
        if self.car is None:
            self.get_logger().warn(f"ARM pose {pose} (simulated)")
            return

        repeat = max(1, int(self.get_parameter("cmd_repeat").value))
        gap = max(0.0, float(self.get_parameter("cmd_repeat_gap_sec").value))

        def worker():
            for i in range(repeat):
                try:
                    self.car.set_uart_servo_angle_array(angle_s=pose, run_time=int(run_time_ms))
                except Exception as e:
                    self.get_logger().error(f"set_uart_servo_angle_array failed: {e}")
                if i < repeat - 1:
                    time.sleep(gap)

        threading.Thread(target=worker, daemon=True).start()

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9


def main():
    rclpy.init()
    node = ArmControllerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
