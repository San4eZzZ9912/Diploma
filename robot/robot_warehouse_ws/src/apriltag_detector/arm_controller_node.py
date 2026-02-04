# ===================== arm_controller_node.py (замени файл целиком) =====================
#!/usr/bin/env python3
import time
import threading

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
    """ 
    Главная идея фикса:
      - /arm/busy НЕ должен становиться False сразу после отправки последней позы.
      - busy остаётся True до тех пор, пока (run_time_ms + settle) для последнего шага не пройдет.

    Это убирает гонку: FSM не уезжает назад, пока рука реально не сложилась.
    """

    def __init__(self):
        super().__init__("arm_controller_node")

        # ---- params ----
        self.declare_parameter("settle_sec", 0.35)          # пауза после каждого шага
        self.declare_parameter("final_settle_sec", 0.70)     # пауза после финального шага
        self.declare_parameter("cmd_repeat", 2)              # повторить отправку команды (повышает надёжность UART)
        self.declare_parameter("cmd_repeat_gap_sec", 0.06)   # задержка между повторами

        # времена шагов (мс) — можно подстроить под твою механику
        self.declare_parameter("pick_pre_ms", 5000)
        self.declare_parameter("pick_grasp_ms", 5000)
        self.declare_parameter("pick_post_ms", 6500)         # чуть больше, чтобы точно сложилась

        self.declare_parameter("place_above_ms", 5000)
        self.declare_parameter("place_pre_ms", 5000)
        self.declare_parameter("place_release_ms", 4500)
        self.declare_parameter("place_post_ms", 6000)

        # ---- flags/state ----
        self.busy = False
        self.has_cube = False

        self._seq = []            # list of steps: {pose, ms, settle, on_finish}
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

        # ---- publishers ----
        self.pub_has_cube = self.create_publisher(Bool, "/arm/has_cube", 10)
        self.pub_busy = self.create_publisher(Bool, "/arm/busy", 10)

        # ---- services ----
        self.srv_pick = self.create_service(Trigger, "/arm/pick", self.handle_pick)
        self.srv_place = self.create_service(Trigger, "/arm/place", self.handle_place)

        # ---- timer ----
        self.timer = self.create_timer(0.02, self.update)            # 50 Hz
        self.status_timer = self.create_timer(0.10, self.publish_status)  # 10 Hz

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

        settle = float(self.get_parameter("settle_sec").value)
        final_settle = float(self.get_parameter("final_settle_sec").value)

        pre_ms = int(self.get_parameter("pick_pre_ms").value)
        grasp_ms = int(self.get_parameter("pick_grasp_ms").value)
        post_ms = int(self.get_parameter("pick_post_ms").value)

        # шаги: pre -> grasp -> post
        self._seq = [
            {"pose": self.arm_pre_pick,  "ms": pre_ms,   "settle": settle,      "on_finish": None},
            {"pose": self.arm_grasp,     "ms": grasp_ms, "settle": settle,      "on_finish": None},
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
            response.message = "No cube to place (has_cube=False)"
            return response

        settle = float(self.get_parameter("settle_sec").value)
        final_settle = float(self.get_parameter("final_settle_sec").value)

        above_ms = int(self.get_parameter("place_above_ms").value)
        pre_ms = int(self.get_parameter("place_pre_ms").value)
        rel_ms = int(self.get_parameter("place_release_ms").value)
        post_ms = int(self.get_parameter("place_post_ms").value)

        self._seq = [
            {"pose": self.arm_above_place, "ms": above_ms, "settle": settle,      "on_finish": None},
            {"pose": self.arm_pre_place,   "ms": pre_ms,   "settle": settle,      "on_finish": None},
            {"pose": self.arm_release,     "ms": rel_ms,   "settle": settle,      "on_finish": None},
            {"pose": self.arm_post_place,  "ms": post_ms,  "settle": final_settle, "on_finish": self._mark_cube_released},
        ]

        self._start_sequence("PLACE")

        response.success = True
        response.message = "Place started"
        return response

    # ================= UPDATE LOOP =================

    def update(self):
        if not self.busy:
            return

        now = self._now()

        # Ждём, пока закончится текущий шаг
        if now < self._step_deadline:
            return

        # Текущий шаг закончился
        self._seq_i += 1

        # Если шагов больше нет — завершаем
        if self._seq_i >= len(self._seq):
            self._finish("Sequence done")
            return

        # Иначе запускаем следующий шаг
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

        # ВАЖНО: дедлайн = run_time + settle
        self._step_deadline = now + (ms / 1000.0) + max(0.0, settle)

        # Если у шага есть on_finish — выполним, но только когда шаг реально "дождался" дедлайна.
        # Поэтому сохраняем функцию, а вызов делаем на переходе к следующему шагу/завершении.
        # Здесь ничего не делаем.

        # Для последнего шага on_finish сработает при завершении всей последовательности.

    def _mark_cube_taken(self):
        self.has_cube = True

    def _mark_cube_released(self):
        self.has_cube = False

    def _finish(self, msg: str):
        # если последний шаг имеет on_finish — применяем его здесь
        if self._seq and 0 <= (len(self._seq) - 1) < len(self._seq):
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

        repeat = int(self.get_parameter("cmd_repeat").value)
        gap = float(self.get_parameter("cmd_repeat_gap_sec").value)
        repeat = max(1, repeat)
        gap = max(0.0, gap)

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
