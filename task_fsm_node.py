#!/usr/bin/env python3
import math
import threading
import requests
import rclpy
from rclpy.node import Node

from std_msgs.msg import Bool, Float32, String, Int32
from geometry_msgs.msg import Vector3
from sensor_msgs.msg import CameraInfo
from std_srvs.srv import Trigger

# Yahboom / Rosmaster
try:
    from Rosmaster_Lib.Rosmaster_Lib import Rosmaster
except Exception:
    Rosmaster = None


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def signed_floor_abs(v: float, min_abs: float) -> float:
    """Guarantee a minimum absolute speed (deadband bypass) while keeping sign."""
    if abs(v) < 1e-9:
        return 0.0
    return math.copysign(max(abs(v), min_abs), v)


class TaskFSMNode(Node):
    """
    FSM:
      1) Approach AprilTag up to pre-QR distance (tag_goal_z_pre_qr)
      2) Switch to QR focusing (center by u_target, approach by qr_target_w_px)
      3) Hold stability for pregrasp_wait seconds
      4) Call /arm/pick
      5) Back off after pick (new)
      6) For placing: approach AprilTag to goal_z, search free slot by strafe + QR check, then /arm/place
    """

    def __init__(self):
        super().__init__("task_fsm_node")

        # ===== AprilTag ID filtering =====
        # If enabled, the node will only consider AprilTag measurements whose id matches
        # the tag id assigned to the current PICK shelf (pick_shelf_name) or PLACE shelf (place_shelf_name).
        # Set shelf_A_tag_id / shelf_B_tag_id to your real AprilTag IDs (or keep -1 to accept any).
        self.declare_parameter("use_tag_id_filter", True)
        self.declare_parameter("tag_id_topic", "/tag/id")
        self.declare_parameter("shelf_A_tag_id", 1)
        self.declare_parameter("shelf_B_tag_id", 2)

        # timers / stamps
        self.state_enter_t = None

        # shelf routing
        self.current_shelf_id = None      # id тега текущего стеллажа (если нужно)
        self.target_shelf_id = None       # куда едем ставить (другой стеллаж)

        # slots memory (пока простая модель)
        # допустим два места: left/right
        self.shelf_slots = {
            "A": {"left": False, "right": False},   # True=свободно
            "B": {"left": True, "right": True},
        }
        self.pick_shelf_name = "A"
        self.place_shelf_name = "B"

        # where we plan to place
        self.place_side = None  # "left" or "right"

        # ===== AprilTag approach params =====
        self.declare_parameter("goal_z", 0.34)
        self.declare_parameter("z_tolerance", 0.03)
        self.declare_parameter("x_tolerance", 0.01)
        self.declare_parameter("ang_tolerance", 0.03)

        # IMPORTANT: compensates RGB camera optical axis offset to the right of the robot base center
        self.declare_parameter("camera_offset_right_m", 0.019)

        self.declare_parameter("k_ang", 0.6)
        self.declare_parameter("k_x", 0.5)
        self.declare_parameter("k_z", 0.35)

        self.declare_parameter("max_vx", 0.12)
        self.declare_parameter("max_vy", 0.25)
        self.declare_parameter("max_vz", 0.80)

        self.declare_parameter("min_vx", 0.015)
        self.declare_parameter("min_vy", 0.004)
        self.declare_parameter("min_vz", 0.020)

        # ===== MCU motion PID (optional) =====
        self.declare_parameter("use_motion_pid", True)
        self.declare_parameter("motion_kp", 1.2)
        self.declare_parameter("motion_ki", 0.25)
        self.declare_parameter("motion_kd", 0.40)
        self.declare_parameter("motion_pid_forever", False)

        # ===== Pick anti-spam / re-arm =====
        self.declare_parameter("rearm_lost_sec", 0.5)

        # ===== QR focusing params =====
        self.declare_parameter("tag_goal_z_pre_qr", 0.34)     # distance at which we stop Tag-approach and start QR focus
        self.declare_parameter("pre_qr_z_margin", 0.03)       # allow a little margin to switch to QR

        self.declare_parameter("pregrasp_wait", 2.0)          # hold time in QR-ready pose before pick

        self.declare_parameter("qr_target_w_px", 185.0)       # target QR width at grasp distance (pixels)
        self.declare_parameter("qr_u_tol_px", 25.0)
        # Hysteresis: once centered, keep it centered until error exceeds this threshold
        self.declare_parameter("qr_u_tol_exit_px", 35.0)
        self.declare_parameter("qr_w_tol_px", 15.0)

        self.declare_parameter("qr_k_y", 0.25)                # strafe gain (u-error)
        self.declare_parameter("qr_k_x", 0.20)                # forward gain (w-error)

        self.declare_parameter("qr_max_vy", 0.02)
        self.declare_parameter("qr_max_vx", 0.04)
        self.declare_parameter("qr_min_vy", 0.006)
        self.declare_parameter("qr_min_vx", 0.006)

        # Filter QR measurements to reduce jitter (same idea as in monolithic node)
        self.declare_parameter("qr_u_alpha", 1)
        self.declare_parameter("qr_w_alpha", 1)

        # Low-pass for commanded velocities to reduce overshoot (0..1, higher = snappier)
        self.declare_parameter("vel_alpha_tag", 0.0)   # было "как раньше"
        self.declare_parameter("vel_alpha_qr", 0.1)   # сглаживание только для QR

        self.declare_parameter("qr_timeout", 0.2)             # sec; qr must be updated recently
        self.declare_parameter("qr_target_payload", "")     # "" accepts any payload, else strict match

        # CameraInfo topic (same as in your monolithic version)
        self.declare_parameter("camera_info_topic", "/camera/color/camera_info")

        # ===== Geometry params (for full tag/QR fit in jaw) =====
        self.declare_parameter("jaw_width", 0.05)  # gripper jaw width, m
        self.declare_parameter("tag_size", 0.04)   # AprilTag size, m
        self.declare_parameter("grasp_margin", 0.005)  # extra margin for tolerances, m (for AprilTag)
        self.declare_parameter("qr_u_tol_margin_px", 5.0)  # extra pixel margin for QR tol

        # ===== New params for back-off after pick =====
        self.declare_parameter("back_off_distance", 0.45)  # m to back off after pick
        self.declare_parameter("back_off_speed", 0.10)     # vx negative speed for back-off
        self.declare_parameter("back_off_timeout", 13.0)    # max sec for back-off (safety)

        # ===== New params for back-off after place =====
        self.declare_parameter("place_back_off_speed", 0.10)  # vx negative speed after place
        self.declare_parameter("place_back_off_sec", 2.0)     # sec to back off after place
        self.declare_parameter("place_turn_speed", 0.6)       # vz speed for post-place turn
        self.declare_parameter("place_turn_sec", 5.0)         # sec to turn after place
        self.declare_parameter("place_release_timeout", 2.0)


        # ===== New params for slot search on shelf =====
        self.declare_parameter("slot_strafe_distance", 0.03)  # m to strafe to check slot
        self.declare_parameter("slot_strafe_speed", 0.02)     # vy speed for strafe
        self.declare_parameter("slot_qr_absent_sec", 0.6)     # sec without QR to consider slot free
        self.declare_parameter("prefer_left_slot", True)      # start with left

        # New param to invert strafe signs (if robot turns wrong way)
        self.declare_parameter("left_strafe_sign", 1.0)  # -1.0 for negative vy = left, +1.0 to invert

        # New param for slot QR check tol (to ignore off-center QR)
        self.declare_parameter("slot_qr_u_tol_px", 50.0)  # if |u_err| > this, ignore QR (it's from other slot)

        # ===== REST backend (warehouse state) =====
        self.declare_parameter("rest_enable", True)
        self.declare_parameter("rest_base_url", "http://192.168.0.128:8080")  # поменяешь на IP ПК
        self.declare_parameter("rest_timeout_sec", 0.6)
        self.declare_parameter("rest_robot_id", "R1")
        self.declare_parameter("rest_cube_qr_fallback", "Lower shelf")

        # ===== Read params =====
        self.rest_enable = bool(self.get_parameter("rest_enable").value)
        self.rest_base_url = str(self.get_parameter("rest_base_url").value).rstrip("/")
        self.rest_timeout = float(self.get_parameter("rest_timeout_sec").value)
        self.rest_robot_id = str(self.get_parameter("rest_robot_id").value)
        self.rest_cube_qr_fallback = str(self.get_parameter("rest_cube_qr_fallback").value)
        self.backend_cleared_once = False

        # Tag ID filtering
        self.use_tag_id_filter = bool(self.get_parameter("use_tag_id_filter").value)
        self.tag_id_topic = str(self.get_parameter("tag_id_topic").value)
        self.shelf_tag_id = {
            "A": int(self.get_parameter("shelf_A_tag_id").value),
            "B": int(self.get_parameter("shelf_B_tag_id").value),
        }

        self.goal_z = float(self.get_parameter("goal_z").value)
        self.z_tol = float(self.get_parameter("z_tolerance").value)
        self.ang_tol = float(self.get_parameter("ang_tolerance").value)
        self.cam_off = float(self.get_parameter("camera_offset_right_m").value)

        self.k_ang = float(self.get_parameter("k_ang").value)
        self.k_x = float(self.get_parameter("k_x").value)
        self.k_z = float(self.get_parameter("k_z").value)

        self.max_vx = float(self.get_parameter("max_vx").value)
        self.max_vy = float(self.get_parameter("max_vy").value)
        self.max_vz = float(self.get_parameter("max_vz").value)

        self.min_vx = float(self.get_parameter("min_vx").value)
        self.min_vy = float(self.get_parameter("min_vy").value)
        self.min_vz = float(self.get_parameter("min_vz").value)

        self.rearm_lost_sec = float(self.get_parameter("rearm_lost_sec").value)

        # Geometry
        self.jaw_width = float(self.get_parameter("jaw_width").value)
        self.tag_size = float(self.get_parameter("tag_size").value)
        self.jaw_half = self.jaw_width / 2.0
        self.tag_half = self.tag_size / 2.0
        self.grasp_margin = float(self.get_parameter("grasp_margin").value)
        self.qr_u_tol_margin_px = float(self.get_parameter("qr_u_tol_margin_px").value)

        # New place back-off
        self.place_back_off_speed = float(self.get_parameter("place_back_off_speed").value)
        self.place_back_off_sec = float(self.get_parameter("place_back_off_sec").value)
        self.place_turn_speed = float(self.get_parameter("place_turn_speed").value)
        self.place_turn_sec = float(self.get_parameter("place_turn_sec").value)
        self.place_release_timeout = float(self.get_parameter("place_release_timeout").value)

        # Grasp tol for AprilTag (in world meters)
        self.grasp_x_tol = self.jaw_half - self.tag_half + self.grasp_margin

        # New back-off
        self.back_off_dist = float(self.get_parameter("back_off_distance").value)
        self.back_off_speed = float(self.get_parameter("back_off_speed").value)
        self.back_off_timeout = float(self.get_parameter("back_off_timeout").value)

        # New slot search
        self.slot_strafe_dist = float(self.get_parameter("slot_strafe_distance").value)
        self.slot_strafe_speed = float(self.get_parameter("slot_strafe_speed").value)
        self.slot_qr_absent_sec = float(self.get_parameter("slot_qr_absent_sec").value)
        self.prefer_left = bool(self.get_parameter("prefer_left_slot").value)
        self.left_strafe_sign = float(self.get_parameter("left_strafe_sign").value)
        self.slot_qr_u_tol_px = float(self.get_parameter("slot_qr_u_tol_px").value)

        # ===== Camera intrinsics (for QR u_target) =====
        self.fx = None
        self.cx = None

        caminfo_topic = str(self.get_parameter("camera_info_topic").value)
        self.create_subscription(CameraInfo, caminfo_topic, self.on_caminfo, 10)

        # ===== State machine =====
        self.state = "WAIT_TAG"

        # latest tag data
        self.tag_seen = False
        self.tag_id = None  # int
        self.tag_t = None  # Vector3
        self.tag_ang = None  # float

        # latest qr data
        self.qr_valid = False
        self.qr_payload = None
        self.qr_u = None
        self.qr_w = None
        self.qr_last_t = 0.0
        self.z_qr_ref = None

        # filtered QR measurements
        self.qr_u_filt = None
        self.qr_w_filt = None

        # centered latch for hysteresis
        self.qr_centered_latched = False

        # QR hold timer (like qr_ready_since)
        self.qr_ready_since = None

        # pick/place futures
        self.pick_in_progress = False
        self.pick_future = None
        self.place_future = None

        # rearm
        self.rearm_seen_false_since = None

        # arm status
        self.arm_busy = False
        self.arm_has_cube = False

        # New for back-off
        self.back_off_start_t = None
        self.back_off_start_z = None

        # New for slot search
        self.slot_side = None  # 'left' or 'right'
        self.slot_strafe_start_t = None
        self.slot_strafe_start_x = None
        self.slot_checked_sides = set()  # to track checked sides

        # ===== Base (Rosmaster) =====
        self.car = None
        if Rosmaster is not None:
            try:
                self.car = Rosmaster()
                self.get_logger().info("Rosmaster connected (FSM)")
            except Exception as e:
                self.get_logger().error(f"Rosmaster connect failed: {e}")

        self.motion_pid_applied = False
        self._apply_mcu_motion_pid_once()

        # command smoothing (like vel_alpha in monolithic node)
        self.prev_vx = 0.0
        self.prev_vy = 0.0
        self.prev_vz = 0.0

        # ===== Subscriptions (AprilTag detector) =====
        self.create_subscription(Bool, "/tag/seen", self.on_tag_seen, 10)
        self.create_subscription(Int32, self.tag_id_topic, self.on_tag_id, 10)
        self.create_subscription(Vector3, "/tag/pose_t", self.on_tag_pose, 10)
        self.create_subscription(Float32, "/tag/ang_err_normal", self.on_tag_ang, 10)

        # ===== Subscriptions (QR detector) =====
        self.create_subscription(Bool, "/qr/valid", self.on_qr_valid, 10)
        self.create_subscription(Float32, "/qr/u", self.on_qr_u, 10)
        self.create_subscription(Float32, "/qr/w", self.on_qr_w, 10)
        self.create_subscription(String, "/qr/data", self.on_qr_data, 10)

        # ===== ARM services =====
        self.arm_pick = self.create_client(Trigger, "/arm/pick")
        self.arm_place = self.create_client(Trigger, "/arm/place")

        # ===== ARM status topics =====
        self.create_subscription(Bool, "/arm/busy", self.on_arm_busy, 10)
        self.create_subscription(Bool, "/arm/has_cube", self.on_arm_has_cube, 10)

        # ===== Main loop =====
        self.timer = self.create_timer(0.05, self.control_step)  # 20 Hz
        self.get_logger().info("Task FSM started: tag-preqr -> qr-focus -> pick -> back-off -> place with slot search")

    # -------------------- Tag ID filter helpers --------------------
    def _expected_tag_id_for_state(self):
        """Return the required AprilTag id for the current state (or None if no filtering)."""
        if not self.use_tag_id_filter:
            return None

        # During pick we want the tag of pick_shelf_name; during place we want tag of place_shelf_name.
        if self.state in ("FIND_TAG_FOR_PICK", "APPROACH_TAG_PREQR", "QR_FOCUS"):
            shelf = self.pick_shelf_name
        elif self.state in ("FIND_TAG_FOR_PLACE", "APPROACH_TAG_FOR_PLACE"):
            shelf = self.place_shelf_name
        else:
            return None

        tid = int(self.shelf_tag_id.get(shelf, -1))
        if tid < 0:
            return None
        return tid

    # -------------------- CameraInfo --------------------
    def on_caminfo(self, msg: CameraInfo):
        try:
            self.fx = float(msg.k[0])
            self.cx = float(msg.k[2])
        except Exception:
            self.fx = None
            self.cx = None

    # -------------------- Tag callbacks --------------------
    def on_tag_seen(self, msg: Bool):
        self.tag_seen = bool(msg.data)

    def on_tag_id(self, msg: Int32):
        try:
            self.tag_id = int(msg.data)
        except Exception:
            self.tag_id = None

    def on_tag_pose(self, msg: Vector3):
        self.tag_t = msg

    def on_tag_ang(self, msg: Float32):
        self.tag_ang = float(msg.data)

    # -------------------- QR callbacks --------------------
    def _touch_qr(self):
        self.qr_last_t = self._now_s()

    def on_qr_valid(self, msg: Bool):
        self.qr_valid = bool(msg.data)
        if self.qr_valid:
            self._touch_qr()

    def on_qr_u(self, msg: Float32):
        u = float(msg.data)
        a = float(self.get_parameter("qr_u_alpha").value)
        self.qr_u_filt = u if self.qr_u_filt is None else (1.0 - a) * self.qr_u_filt + a * u
        self.qr_u = float(self.qr_u_filt)
        self._touch_qr()

    def on_qr_w(self, msg: Float32):
        w = float(msg.data)
        a = float(self.get_parameter("qr_w_alpha").value)
        self.qr_w_filt = w if self.qr_w_filt is None else (1.0 - a) * self.qr_w_filt + a * w
        self.qr_w = float(self.qr_w_filt)
        self._touch_qr()

    def on_qr_data(self, msg: String):
        self.qr_payload = msg.data
        self._touch_qr()

    # -------------------- Arm status --------------------
    def on_arm_busy(self, msg: Bool):
        self.arm_busy = bool(msg.data)

    def on_arm_has_cube(self, msg: Bool):
        self.arm_has_cube = bool(msg.data)

    # -------------------- MCU PID --------------------
    def _apply_mcu_motion_pid_once(self):
        if self.car is None or self.motion_pid_applied:
            return

        use_pid = bool(self.get_parameter("use_motion_pid").value)
        if not use_pid:
            self.motion_pid_applied = True
            self.get_logger().info("MCU motion PID disabled (use_motion_pid=False)")
            return

        kp = float(self.get_parameter("motion_kp").value)
        ki = float(self.get_parameter("motion_ki").value)
        kd = float(self.get_parameter("motion_kd").value)
        forever = bool(self.get_parameter("motion_pid_forever").value)

        try:
            self.car.set_pid_param(kp, ki, kd, forever=forever)
            self.motion_pid_applied = True
            self.get_logger().info(f"MCU motion PID set: kp={kp} ki={ki} kd={kd} forever={forever}")
        except Exception as e:
            self.get_logger().warn(f"MCU motion PID set failed: {e}")

    # -------------------- Main FSM loop --------------------
    def _enter(self, new_state: str, now: float):
        if self.state != new_state:
            self.state = new_state
            self.state_enter_t = now
            self.get_logger().info(f"FSM -> {new_state}")

    def _elapsed(self, now: float) -> float:
        if self.state_enter_t is None:
            return 0.0
        return now - self.state_enter_t

    def control_step(self):
        now = self._now_s()

        # ----------------------------
        # 0) State init
        # ----------------------------
        if self.state_enter_t is None:
            self.state_enter_t = now

        # ----------------------------
        # 1) Hard-priority timed motions
        # ----------------------------
        if self.state == "BACK_OFF_2S":
            # назад 2 секунды, не зависим ни от tag, ни от qr, ни от arm_busy
            self._send(-self.back_off_speed, 0.0, 0.0)
            if self._elapsed(now) >= 2.0:
                self._stop()
                self._enter("TURN_5S", now)
            return

        if self.state == "TURN_5S":
            # поворот 1 секунду
            turn_vz = 0.6  # лучше вынести параметром
            self._send(0.0, 0.0, turn_vz)
            if self._elapsed(now) >= 5.0:
                self._stop()
                # после поворота ищем метку "другого" стеллажа
                self._enter("FIND_TAG_FOR_PLACE", now)
            return

        if self.state == "BACK_OFF_AFTER_PLACE":
            self._send(-self.place_back_off_speed, 0.0, 0.0)
            if self._elapsed(now) >= self.place_back_off_sec:
                self._stop()
                self._enter("TURN_AFTER_PLACE", now)
            return

        if self.state == "TURN_AFTER_PLACE":
            self._send(0.0, 0.0, self.place_turn_speed)
            if self._elapsed(now) >= self.place_turn_sec:
                self._stop()
                self._enter("FIND_TAG_FOR_PICK", now)
            return

        # ----------------------------
        # 2) If arm is moving - generally stop
        # (кроме состояний выше, мы их уже обработали)
        # ----------------------------
        if self.arm_busy:
            self._stop()
            return

        # ----------------------------
        # 3) Read tag if available (optional per state)
        # ----------------------------
        raw_tag_ok = (self.tag_seen and (self.tag_t is not None) and (self.tag_ang is not None))

        expected_tag_id = self._expected_tag_id_for_state()
        if raw_tag_ok and expected_tag_id is not None:
            tag_ok = (self.tag_id is not None and int(self.tag_id) == int(expected_tag_id))
        else:
            tag_ok = raw_tag_ok

        if tag_ok:
            z = float(self.tag_t.z)
            x_err = float(self.tag_t.x) - self.cam_off
            ang = float(self.tag_ang)

        # QR freshness
        qr_timeout = float(self.get_parameter("qr_timeout").value)
        qr_alive = (now - self.qr_last_t) <= qr_timeout
        qr_ok = qr_alive and self.qr_valid and (self.qr_u is not None) and (self.qr_w is not None)

        # ----------------------------
        # 4) Main FSM
        # ----------------------------
        if self.state == "WAIT":
            # ✅ Очистка backend 1 раз при первом входе в WAIT
            if self.rest_enable and not self.backend_cleared_once:
                self.get_logger().info("Clearing backend shelf state (one-time on FSM start)")
                for shelf_name in self.shelf_slots.keys():  # "A", "B"
                    for side_lr in ["left", "right"]:
                        self._report_clear_to_backend(shelf_name, side_lr)
                self.backend_cleared_once = True

            # старт: если нет куба -> идём забирать
            if not self.arm_has_cube:
                self._enter("FIND_TAG_FOR_PICK", now)
            else:
                self._enter("FIND_TAG_FOR_PLACE", now)
            return


        # ======== PICK ROUTE ========

        if self.state == "FIND_TAG_FOR_PICK":
            # просто ждём появления метки (нужного ID)
            self._stop()
            if tag_ok:
                self._enter("APPROACH_TAG_PREQR", now)
            return

        if self.state == "APPROACH_TAG_PREQR":
            if not tag_ok:
                self._stop()
                self._enter("FIND_TAG_FOR_PICK", now)
                return

            pre_goal = float(self.get_parameter("tag_goal_z_pre_qr").value)
            pre_margin = float(self.get_parameter("pre_qr_z_margin").value)

            z_err_pre = z - pre_goal
            vx, vy, vz = self._tag_control(x_err=x_err, z_err=z_err_pre, ang=ang)
            self._send(vx, vy, vz)

            ready_switch = (abs(ang) <= self.ang_tol and abs(x_err) <= self.grasp_x_tol and z <= (pre_goal + pre_margin))
            if ready_switch:
                self._stop()
                # теперь "забываем про метку" и работаем по QR
                self.qr_ready_since = None
                self.qr_centered_latched = False
                self._enter("QR_FOCUS", now)
            return

        if self.state == "QR_FOCUS":
            pre_goal = float(self.get_parameter("tag_goal_z_pre_qr").value)

            # Если QR временно потеряли:
            if not qr_ok:
                # 1) если тег ещё видим — НЕ откатываемся, а удерживаемся у тега на pre_goal
                if tag_ok:
                    z_err_pre = z - pre_goal
                    vx, vy, vz = self._tag_control(x_err=x_err, z_err=z_err_pre, ang=ang)
                    self._send(vx, vy, vz)
                    return

                # 2) если и тега нет — тогда уже откатываемся, но не через 1 секунду, а через 2.5
                self._stop()
                if self._elapsed(now) > 2.0:
                    self._enter("FIND_TAG_FOR_PICK", now)
                return

            # intrinsics required
            if self.fx is None or self.cx is None:
                self._stop()
                return

            z_used = z if tag_ok else None

            # --- Compute u_target ---
            # u_target = cx + fx*(cam_off/z)
            if z_used is None or z_used <= 1e-6:
                # без z — только центрируем по cx (грубая деградация)
                u_target = self.cx
            else:
                u_target = self.cx + self.fx * (self.cam_off / z_used)

            u_err = float(self.qr_u) - float(u_target)

            w_target = float(self.get_parameter("qr_target_w_px").value)
            w_err = w_target - float(self.qr_w)
            w_tol = float(self.get_parameter("qr_w_tol_px").value)

            # dynamic tol requires z; если z нет — используем фикс tol
            if z_used is None or z_used <= 1e-6:
                tol_px = float(self.get_parameter("qr_u_tol_px").value)
            else:
                qr_size_world = (self.qr_w * z_used) / self.fx
                qr_half_world = qr_size_world / 2.0
                tol_world = self.jaw_half - qr_half_world
                tol_px = max(0.0, (tol_world / z_used) * self.fx) + self.qr_u_tol_margin_px

            hyst_px = float(self.get_parameter("qr_u_tol_exit_px").value) - float(self.get_parameter("qr_u_tol_px").value)
            u_tol_exit = tol_px + hyst_px

            # hysteresis latch
            if self.qr_centered_latched:
                centered = abs(u_err) <= u_tol_exit
                if not centered:
                    self.qr_centered_latched = False
            else:
                centered = abs(u_err) <= tol_px
                if centered:
                    self.qr_centered_latched = True

            # vy
            if centered:
                v_y = 0.0
            else:
                k_y = float(self.get_parameter("qr_k_y").value)
                max_vy = float(self.get_parameter("qr_max_vy").value)
                min_vy = float(self.get_parameter("qr_min_vy").value)
                u_norm = u_err / max(float(self.fx), 1e-6)
                vy_cmd = clamp(-k_y * u_norm, -max_vy, max_vy)
                v_y = signed_floor_abs(vy_cmd, min_vy) if abs(u_err) > 2.0 * tol_px else vy_cmd

            # vx: только если centered
            if not centered:
                v_x = 0.0
            else:
                if w_err > w_tol:
                    k_x = float(self.get_parameter("qr_k_x").value)
                    max_vx = float(self.get_parameter("qr_max_vx").value)
                    min_vx = float(self.get_parameter("qr_min_vx").value)
                    w_norm = w_err / max(w_target, 1e-6)
                    vx_cmd = clamp(k_x * (w_norm ** 2), 0.0, max_vx)
                    v_x = max(vx_cmd, min_vx)
                else:
                    v_x = 0.0

            self._send(v_x, v_y, 0.0)

            qr_ready = centered and (w_err <= w_tol)
            if qr_ready:
                self._stop()
                if self.qr_ready_since is None:
                    self.qr_ready_since = now
                hold = float(self.get_parameter("pregrasp_wait").value)
                if (now - self.qr_ready_since) >= hold:
                    self._enter("CALL_PICK", now)
            else:
                self.qr_ready_since = None
            return

        if self.state == "CALL_PICK":
            self._stop()
            if not self.arm_pick.wait_for_service(timeout_sec=0.2):
                self.get_logger().warn("/arm/pick not ready")
                return
            self.pick_future = self.arm_pick.call_async(Trigger.Request())
            self._enter("WAIT_PICK_DONE", now)
            return

        if self.state == "WAIT_PICK_DONE":
            self._stop()

            # 1) ждём, пока сервис хотя бы ответит (если он ответит “started” — это ок)
            if self.pick_future is not None and self.pick_future.done():
                try:
                    res = self.pick_future.result()
                    self.get_logger().info(f"pick resp: success={res.success} msg='{res.message}'")
                except Exception as e:
                    self.get_logger().error(f"pick future error: {e}")
                self.pick_future = None

            # 2) критерий "захват реально закончился": arm_busy False и has_cube True
            if (not self.arm_busy) and self.arm_has_cube:
                self._enter("BACK_OFF_2S", now)
                return

            # если рука закончила, но куба нет — значит неудача
            if (not self.arm_busy) and (not self.arm_has_cube) and self._elapsed(now) > 1.0:
                self.get_logger().warn("Pick finished but has_cube=False -> retry")
                self._enter("FIND_TAG_FOR_PICK", now)
            return

        # ======== PLACE ROUTE ========

        if self.state == "FIND_TAG_FOR_PLACE":
            self._stop()
            if tag_ok:
                self._enter("APPROACH_TAG_FOR_PLACE", now)
            return

        if self.state == "APPROACH_TAG_FOR_PLACE":
            if not tag_ok:
                self._stop()
                self._enter("FIND_TAG_FOR_PLACE", now)
                return

            z_err = z - self.goal_z
            vx, vy, vz = self._tag_control(x_err=x_err, z_err=z_err, ang=ang)
            self._send(vx, vy, vz)

            arrived = (abs(ang) <= self.ang_tol and abs(x_err) <= self.grasp_x_tol and abs(z_err) <= self.z_tol)
            if arrived:
                self._stop()
                self._enter("CHOOSE_SLOT", now)
            return

        if self.state == "CHOOSE_SLOT":
            self._stop()
            # пока простая логика: берём первый свободный
            slots = self.shelf_slots[self.place_shelf_name]
            self.get_logger().info(f"CHOOSE_SLOT: place_shelf={self.place_shelf_name} slots={self.shelf_slots[self.place_shelf_name]}")

            if slots["left"]:
                self.place_side = "left"
                self.get_logger().info(f"CHOOSE_SLOT: chosen place_side={self.place_side}")
                self._enter("STRAFE_TO_SLOT", now)
            elif slots["right"]:
                self.place_side = "right"
                self.get_logger().info(f"CHOOSE_SLOT: chosen place_side={self.place_side}")
                self._enter("STRAFE_TO_SLOT", now)
                
            else:
                self.get_logger().warn("No free slots -> wait")
                # можно вернуться в WAIT или сделать другую стратегию
                self._enter("WAIT", now)
            return

        if self.state == "STRAFE_TO_SLOT":
            # упрощение: едем фиксированное время/или по tag_t.x как раньше
            # пока по времени 2 сек
            v_y = 0.02 if self.place_side == "left" else -0.02
            self._send(0.0, v_y, 0.0)
            if self._elapsed(now) >= 3.0:
                self._stop()
                self._enter("CALL_PLACE", now)
            return

        if self.state == "CALL_PLACE":
            self._stop()
            if not self.arm_has_cube:
                self._enter("WAIT", now)
                return
            if not self.arm_place.wait_for_service(timeout_sec=0.2):
                self.get_logger().warn("/arm/place not ready")
                return
            self.place_future = self.arm_place.call_async(Trigger.Request())
            self._enter("WAIT_PLACE_DONE", now)
            return

        if self.state == "WAIT_PLACE_DONE":
            self._stop()
            if self.place_future is not None and self.place_future.done():
                try:
                    res = self.place_future.result()
                    self.get_logger().info(f"place resp: success={res.success} msg='{res.message}'")
                except Exception as e:
                    self.get_logger().error(f"place future error: {e}")
                self.place_future = None

                # обновляем "память" слотов
                if self.place_side:
                    self.shelf_slots[self.place_shelf_name][self.place_side] = False
                    self.get_logger().info(f"AFTER PLACE: shelf={self.place_shelf_name} updated slots={self.shelf_slots[self.place_shelf_name]}")

                    # ✅ REST: сообщаем backend, куда положили
                    self._report_place_to_backend(self.place_shelf_name, self.place_side)

                # меняем стеллажи местами: следующий цикл будет "туда-обратно"
                # self.pick_shelf_name, self.place_shelf_name = self.place_shelf_name, self.pick_shelf_name
                self.place_side = None

                self._enter("WAIT_PLACE_RELEASE", now)
            return

        if self.state == "WAIT_PLACE_RELEASE":
            self._stop()
            if not self.arm_has_cube:
                self._enter("BACK_OFF_AFTER_PLACE", now)
                return

            if self._elapsed(now) >= self.place_release_timeout:
                self.get_logger().warn("Place release timeout: arm_has_cube still True -> continuing")
                self._enter("BACK_OFF_AFTER_PLACE", now)
            return

        # fallback
        self._stop()
        self._enter("WAIT", now)


    def _rest_post_async(self, path: str, payload: dict):
        """Fire-and-forget POST to backend without blocking the FSM loop."""
        if not self.rest_enable:
            return

        url = f"{self.rest_base_url}{path}"

        def worker():
            try:
                r = requests.post(url, json=payload, timeout=self.rest_timeout)
                if r.status_code >= 400:
                    self.get_logger().warn(f"REST {path} -> {r.status_code}: {r.text[:200]}")
                else:
                    self.get_logger().info(f"REST {path} -> {r.status_code}")
            except Exception as e:
                self.get_logger().warn(f"REST {path} failed: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _report_place_to_backend(self, shelf_code: str, side_lr: str):
        """Send placement event to backend: /api/robot/place"""
        side_enum = "LEFT" if side_lr == "left" else "RIGHT"
        cube_qr = self.qr_payload if self.qr_payload else self.rest_cube_qr_fallback

        payload = {
            "shelfCode": str(shelf_code).strip().upper(),
            "side": side_enum,
            "cubeQr": cube_qr,
            "robotId": self.rest_robot_id,
        }
        self._rest_post_async("/api/robot/place", payload)

    def _report_clear_to_backend(self, shelf_code: str, side_lr: str):
        """Send clear event to backend: /api/robot/clear"""
        if not shelf_code or not side_lr:
            return

        side_enum = "LEFT" if side_lr == "left" else "RIGHT"

        payload = {
            "shelfCode": str(shelf_code).strip().upper(),
            "side": side_enum,
            "robotId": self.rest_robot_id,
        }

        self._rest_post_async("/api/robot/clear", payload)

    # -------------------- Controllers --------------------
    def _tag_control(self, x_err: float, z_err: float, ang: float):
        # yaw (поворот)
        if abs(ang) > self.ang_tol:
            vz_cmd = clamp(-self.k_ang * ang, -self.max_vz, self.max_vz)
            vz = signed_floor_abs(vz_cmd, self.min_vz)
        else:
            vz = 0.0

        # strafe (в бок)
        if abs(x_err) > self.grasp_x_tol:
            vy_cmd = clamp(-self.k_x * x_err, -self.max_vy, self.max_vy)
            vy = signed_floor_abs(vy_cmd, self.min_vy)
        else:
            vy = 0.0

        # forward (вперёд) — теперь едем сразу, корректируя себя по yaw и x одновременно
        if z_err > 0.0:
            vx_cmd = clamp(self.k_z * z_err, 0.0, self.max_vx)

            # Чем сильнее ошибка по углу/смещению — тем меньше скорость вперёд.
            # 4.0 — “мягкость”: чем больше, тем дольше робот сохраняет vx даже при ошибках.
            ang_slow = max(self.ang_tol * 4.0, 1e-6)
            x_slow = max(self.grasp_x_tol * 4.0, 1e-6)

            ang_scale = clamp(1.0 - (abs(ang) / ang_slow), 0.0, 1.0)
            x_scale = clamp(1.0 - (abs(x_err) / x_slow), 0.0, 1.0)

            scale = min(ang_scale, x_scale)

            vx = vx_cmd * scale

            # Минималка вперёд — только если scale не совсем “в ноль” (чтобы не ехать при больших ошибках)
            if vx > 0.0 and vx < self.min_vx and scale > 0.25:
                vx = self.min_vx
        else:
            vx = 0.0

        return vx, vy, vz

    # -------------------- Base I/O --------------------
    def _send(self, vx: float, vy: float, vz: float):
        # choose smoothing alpha per mode
        if self.state in ("QR_FOCUS", "READY_FOR_PICK"):
            alpha = float(self.get_parameter("vel_alpha_qr").value)
        else:
            alpha = float(self.get_parameter("vel_alpha_tag").value)

        if alpha > 0.0:
            self.prev_vx = self.prev_vx + alpha * (vx - self.prev_vx)
            self.prev_vy = self.prev_vy + alpha * (vy - self.prev_vy)
            self.prev_vz = self.prev_vz + alpha * (vz - self.prev_vz)
            vx, vy, vz = self.prev_vx, self.prev_vy, self.prev_vz
        else:
            # IMPORTANT: reset filter so QR doesn't inherit stale tag speeds
            self.prev_vx, self.prev_vy, self.prev_vz = vx, vy, vz

        if self.car is None:
            self.get_logger().info(f"CMD vx={vx:.3f} vy={vy:.3f} vz={vz:.3f} state={self.state}")
            return
        try:
            self.car.set_car_motion(float(vx), float(vy), float(vz))
        except Exception as e:
            self.get_logger().warn(f"set_car_motion failed: {e}")

    def _stop(self):
        self._send(0.0, 0.0, 0.0)

    def _now_s(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9


def main():
    rclpy.init()
    node = TaskFSMNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node._stop()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
