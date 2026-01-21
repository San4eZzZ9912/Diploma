#!/usr/bin/env python3
import rclpy
from rclpy.node import Node

from std_srvs.srv import Trigger
from std_msgs.msg import Bool

# Yahboom / Rosmaster
try:
    from Rosmaster_Lib.Rosmaster_Lib import Rosmaster
except Exception:
    Rosmaster = None


class ArmControllerNode(Node):
    def __init__(self):
        super().__init__("arm_controller_node")

        # ---- flags/state ----
        self.busy = False
        self.mode = None          # "PICK" or "PLACE"
        self.stage = 0
        self.stage_start = 0.0

        # cube state flag
        self.has_cube = False

        # ---- connect robot ----
        self.car = None
        if Rosmaster is not None:
            try:
                self.car = Rosmaster()
                self.get_logger().info("Rosmaster connected (arm controller)")
            except Exception as e:
                self.get_logger().error(f"Rosmaster connection failed: {e}")

        # ===== ARM POSES (оставь свои реальные позы как в твоём проекте) =====
        # PICK
        self.arm_home_pick = [93, 180, 0, 0, 90, 30]
        self.arm_pre_pick  = [93, 90, 80, 5, 90, 30]
        self.arm_grasp     = [93, 90, 80, 5, 90, 112]
        self.arm_post_pick = [93, 180, 0, 0, 90, 112]

        # PLACE
        self.arm_above_place = [93, 90, 90, 5, 90, 112]
        self.arm_pre_place   = [93, 90, 80, 5, 90, 112]
        self.arm_release     = [93, 90, 80, 5, 90, 30]
        self.arm_post_place  = [93, 180, 0, 0, 90, 30]

        # timings (сек), чтобы проще менять
        self.stage_time = 5.0

        # ---- publishers ----
        self.pub_has_cube = self.create_publisher(Bool, "/arm/has_cube", 10)
        self.pub_busy = self.create_publisher(Bool, "/arm/busy", 10)

        # ---- services ----
        self.srv_pick = self.create_service(Trigger, "/arm/pick", self.handle_pick)
        self.srv_place = self.create_service(Trigger, "/arm/place", self.handle_place)

        # ---- timer ----
        self.timer = self.create_timer(0.05, self.update)  # 20 Hz
        self.status_timer = self.create_timer(0.2, self.publish_status)  # 5 Hz

        self.get_logger().info("Arm controller node started")
        self._send_pose(self.arm_home_pick, 3000)

    # ================= SERVICES =================

    def handle_pick(self, request, response):
        if self.busy:
            response.success = False
            response.message = "Arm busy"
            return response

        if self.has_cube:
            response.success = False
            response.message = "Already holding a cube (has_cube=True)"
            return response

        self.mode = "PICK"
        self.stage = 0
        self.stage_start = self._now()
        self.busy = True

        self.get_logger().info("ARM: start PICK")
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
            response.message = "No cube to place (has_cube=False)"
            return response

        self.mode = "PLACE"
        self.stage = 0
        self.stage_start = self._now()
        self.busy = True

        self.get_logger().info("ARM: start PLACE")
        response.success = True
        response.message = "Place started"
        return response

    # ================= UPDATE LOOP =================

    def update(self):
        if not self.busy:
            return

        now = self._now()

        # ===== PICK SEQUENCE =====
        if self.mode == "PICK":
            if self.stage == 0:
                self._send_pose(self.arm_pre_pick, 5000)
                self._next_stage(now)

            elif self.stage == 1 and (now - self.stage_start) >= self.stage_time:
                self._send_pose(self.arm_grasp, 5000)
                self._next_stage(now)

            elif self.stage == 2 and (now - self.stage_start) >= self.stage_time:
                self._send_pose(self.arm_post_pick, 5000)
                # ВАЖНО: считаем, что куб захвачен
                self.has_cube = True
                self._finish("PICK done (has_cube=True)")

        # ===== PLACE SEQUENCE =====
        elif self.mode == "PLACE":
            if self.stage == 0:
                self._send_pose(self.arm_above_place, 5000)
                self._next_stage(now)

            elif self.stage == 1 and (now - self.stage_start) >= self.stage_time:
                self._send_pose(self.arm_pre_place, 5000)
                self._next_stage(now)

            elif self.stage == 2 and (now - self.stage_start) >= self.stage_time:
                self._send_pose(self.arm_release, 5000)
                self._next_stage(now)

            elif self.stage == 3 and (now - self.stage_start) >= self.stage_time:
                self._send_pose(self.arm_post_place, 5000)
                # ВАЖНО: считаем, что куб отпущен
                self.has_cube = False
                self._finish("PLACE done (has_cube=False)")

    # ================= HELPERS =================

    def publish_status(self):
        b1 = Bool()
        b1.data = bool(self.has_cube)
        self.pub_has_cube.publish(b1)

        b2 = Bool()
        b2.data = bool(self.busy)
        self.pub_busy.publish(b2)

    def _send_pose(self, pose, run_time_ms):
        if self.car is None:
            self.get_logger().warn(f"ARM pose {pose} (simulated)")
            return
        try:
            self.car.set_uart_servo_angle_array(angle_s=pose, run_time=run_time_ms)
        except Exception as e:
            self.get_logger().error(f"set_uart_servo_angle_array failed: {e}")

    def _next_stage(self, now):
        self.stage += 1
        self.stage_start = now

    def _finish(self, msg):
        self.busy = False
        self.mode = None
        self.stage = 0
        self.stage_start = 0.0
        self.get_logger().info(f"ARM: {msg}")

    def _now(self) -> float:
        # точное время в секундах
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
