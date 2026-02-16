#!/usr/bin/env python3
import math
import threading
import requests
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, Float32, String, Int32
from geometry_msgs.msg import Vector3, Pose2D
from sensor_msgs.msg import CameraInfo
from std_srvs.srv import Trigger
from rclpy.parameter import Parameter
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy


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
        super().__init__(
            "task_fsm_node",
            allow_undeclared_parameters=True,
            automatically_declare_parameters_from_overrides=True
        )

        # Публикаторы
        qos_target = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )

        self.pub_qr_target = self.create_publisher(String, "/qr/target", qos_target)
        self.pub_tag_target = self.create_publisher(Int32, "/tag/target_id", 10)
        self._last_sent_tag_target = None

        self._set_tag_target_id(-1)

        self.mission_nav_future = None
        self.nav_start_t = None

        # Состояние задачи
        self.current_task = None
        self.current_task_id = None
        self.current_target_side = None
        self.current_target_level = None
        self.current_target_apriltag_id = None
        self.place_side = None

        # Временные метки и состояние FSM
        self.state_enter_t = None
        self.state = "WAIT"

        # Последние данные сенсоров
        self.tag_seen = False
        self.tag_id = None
        self.tag_t = None
        self.tag_ang = None

        self.qr_valid = False
        self.qr_payload = None
        self.qr_u = None
        self.qr_w = None
        self.qr_last_t = 0.0
        self.expected_qr = None

        self.qr_u_filt = None
        self.qr_w_filt = None
        self.qr_centered_latched = False
        self.qr_ready_since = None

        # Статус манипулятора
        self.arm_busy = False
        self.arm_has_cube = False

        # Сглаживание скоростей
        self.prev_vx = 0.0
        self.prev_vy = 0.0
        self.prev_vz = 0.0

        # Подключение к Rosmaster
        self.car = None
        if Rosmaster is not None:
            try:
                self.car = Rosmaster()
                self.get_logger().info("Rosmaster connected (FSM)")
            except Exception as e:
                self.get_logger().error(f"Rosmaster connect failed: {e}")

        # Чтение всех параметров из yaml (или дефолты, если не найдены)
        self._load_parameters()

        self.motion_pid_applied = False
        self._apply_mcu_motion_pid_once()

        # Подписки
        self.create_subscription(CameraInfo, self.camera_info_topic, self.on_caminfo, 10)

        self.create_subscription(Bool, "/tag/seen", self.on_tag_seen, 10)
        self.create_subscription(Int32, self.tag_id_topic, self.on_tag_id, 10)
        self.create_subscription(Vector3, "/tag/pose_t", self.on_tag_pose, 10)
        self.create_subscription(Float32, "/tag/ang_err_normal", self.on_tag_ang, 10)

        self.create_subscription(Bool, "/qr/valid", self.on_qr_valid, 10)
        self.create_subscription(Float32, "/qr/u", self.on_qr_u, 10)
        self.create_subscription(Float32, "/qr/w", self.on_qr_w, 10)
        self.create_subscription(String, "/qr/data", self.on_qr_data, 10)

        self.create_subscription(Bool, "/arm/busy", self.on_arm_busy, 10)
        self.create_subscription(Bool, "/arm/has_cube", self.on_arm_has_cube, 10)

        self.pub_arm_target_level = self.create_publisher(String, "/arm/target_level", 10)

        # Клиенты сервисов
        self.arm_pick = self.create_client(Trigger, "/arm/pick")
        self.arm_place = self.create_client(Trigger, "/arm/place")

        self.nav_pick_cli = self.create_client(Trigger, self.mission_nav_pick_srv)
        self.nav_place_cli = self.create_client(Trigger, self.mission_nav_place_srv)

        # Таймер
        self.timer = self.create_timer(0.05, self.control_step)

        self.get_logger().info("Task FSM started")

    def _load_parameters(self):
        """Читает все необходимые параметры (загружены из yaml или берутся дефолты)"""
        # AprilTag & topics
        self.use_tag_id_filter = self.get_parameter_or("use_tag_id_filter", True).value
        self.tag_id_topic = self.get_parameter_or("tag_id_topic", "/tag/id").value

        # Camera & geometry
        self.camera_info_topic = self.get_parameter_or("camera_info_topic", "/camera/color/camera_info").value
        self.cam_off = self.get_parameter_or("camera_offset_right_m", 0.020).value
        self.jaw_width = self.get_parameter_or("jaw_width", 0.05).value
        self.tag_size = self.get_parameter_or("tag_size", 0.04).value
        self.grasp_margin = self.get_parameter_or("grasp_margin", 0.005).value
        self.qr_u_tol_margin_px = self.get_parameter_or("qr_u_tol_margin_px", 5.0).value

        # AprilTag approach
        self.tag_goal_z_pre_qr_upper = self.get_parameter_or("tag_goal_z_pre_qr_upper", 0.36).value
        self.tag_goal_z_pre_qr_lower = self.get_parameter_or("tag_goal_z_pre_qr_lower", 0.45).value
        self.z_tol = self.get_parameter_or("z_tolerance", 0.03).value
        self.ang_tol = self.get_parameter_or("ang_tolerance", 0.03).value
        self.k_ang = self.get_parameter_or("k_ang", 0.6).value
        self.k_x = self.get_parameter_or("k_x", 0.5).value
        self.k_z = self.get_parameter_or("k_z", 0.35).value
        self.max_vx = self.get_parameter_or("max_vx", 0.12).value
        self.max_vy = self.get_parameter_or("max_vy", 0.25).value
        self.max_vz = self.get_parameter_or("max_vz", 0.80).value
        self.min_vx = self.get_parameter_or("min_vx", 0.015).value
        self.min_vy = self.get_parameter_or("min_vy", 0.004).value
        self.min_vz = self.get_parameter_or("min_vz", 0.020).value

        # QR
        self.goal_z_upper = self.get_parameter_or("goal_z_upper", 0.34).value
        self.goal_z_lower = self.get_parameter_or("goal_z_lower", 0.45).value
        self.pre_qr_z_margin = self.get_parameter_or("pre_qr_z_margin", 0.03).value
        self.pregrasp_wait = self.get_parameter_or("pregrasp_wait", 2.0).value
        self.qr_target_w_px = self.get_parameter_or("qr_target_w_px", 170.0).value
        self.qr_target_w_px_lower = self.get_parameter_or("qr_target_w_px_lower", self.qr_target_w_px).value
        self.qr_u_tol_px = self.get_parameter_or("qr_u_tol_px", 25.0).value
        self.qr_u_tol_exit_px = self.get_parameter_or("qr_u_tol_exit_px", 35.0).value
        self.qr_w_tol_px = self.get_parameter_or("qr_w_tol_px", 15.0).value
        self.qr_k_y = self.get_parameter_or("qr_k_y", 0.25).value
        self.qr_k_x = self.get_parameter_or("qr_k_x", 0.20).value
        self.qr_max_vy = self.get_parameter_or("qr_max_vy", 0.02).value
        self.qr_max_vx = self.get_parameter_or("qr_max_vx", 0.04).value
        self.qr_min_vy = self.get_parameter_or("qr_min_vy", 0.006).value
        self.qr_min_vx = self.get_parameter_or("qr_min_vx", 0.006).value
        self.qr_u_alpha = self.get_parameter_or("qr_u_alpha", 1.0).value
        self.qr_w_alpha = self.get_parameter_or("qr_w_alpha", 1.0).value
        self.qr_timeout = self.get_parameter_or("qr_timeout", 0.2).value

        # Сглаживание
        self.vel_alpha_tag = self.get_parameter_or("vel_alpha_tag", 0.0).value
        self.vel_alpha_qr = self.get_parameter_or("vel_alpha_qr", 0.1).value

        # Back-off & timings
        self.back_off_dist = self.get_parameter_or("back_off_distance", 0.45).value
        self.back_off_speed = self.get_parameter_or("back_off_speed", 0.10).value
        self.place_back_off_speed = self.get_parameter_or("place_back_off_speed", 0.10).value
        self.place_back_off_sec = self.get_parameter_or("place_back_off_sec", 2.0).value
        self.place_turn_speed = self.get_parameter_or("place_turn_speed", 0.6).value
        self.place_turn_sec = self.get_parameter_or("place_turn_sec", 5.0).value
        self.place_release_timeout = self.get_parameter_or("place_release_timeout", 2.0).value
        self.arm_settle_after_pick_sec = self.get_parameter_or("arm_settle_after_pick_sec", 0.6).value

        # REST
        self.rest_enable = self.get_parameter_or("rest_enable", True).value
        self.rest_base_url = self.get_parameter_or("rest_base_url", "http://192.168.0.109:8080").value.rstrip("/")
        self.rest_timeout = self.get_parameter_or("rest_timeout_sec", 1.5).value
        self.rest_robot_id = self.get_parameter_or("rest_robot_id", "robot1").value
        self.rest_cube_qr_fallback = self.get_parameter_or("rest_cube_qr_fallback", "UNKNOWN/UNKNOWN").value

        # Pick shelf fallback
        self.pick_shelf_code = self.get_parameter_or("pick_shelf_code", "A").value.strip().upper()
        self.pick_shelf_name = self.pick_shelf_code

        # Mission nav
        self.use_mission_nav = self.get_parameter_or("use_mission_nav", True).value
        self.mission_nav_pick_srv = self.get_parameter_or("mission_nav_pick_srv", "/mission/nav_pick").value
        self.mission_nav_place_srv = self.get_parameter_or("mission_nav_place_srv", "/mission/nav_place").value
        self.mission_nav_retry_sec = self.get_parameter_or("mission_nav_retry_sec", 2.0).value

        # Геометрия захвата
        self.jaw_half = self.jaw_width / 2.0
        self.tag_half = self.tag_size / 2.0
        self.grasp_x_tol = self.jaw_half - self.tag_half + self.grasp_margin

    # -------------------- Tag ID filter helpers --------------------
    def _expected_tag_id_for_state(self):
        if not self.use_tag_id_filter:
            return None

        if self.state in ("FIND_TAG_FOR_PICK", "APPROACH_TAG_PREQR", "QR_FOCUS"):
            # Для pick — можно использовать фиксированный тег (параметр pick_tag_id)
            pick_tag = self.get_parameter_or("pick_tag_id", -1).value
            return pick_tag if pick_tag >= 0 else None

        elif self.state in ("FIND_TAG_FOR_PLACE", "APPROACH_TAG_FOR_PLACE"):
            if self.current_target_apriltag_id is not None and self.current_target_apriltag_id >= 0:
                return self.current_target_apriltag_id
            self.get_logger().warn("No valid targetApriltagId for PLACE → tag filtering off")
            return None

        return None

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

        use_pid = bool(self.get_parameter_or("use_motion_pid", True).value)
        if not use_pid:
            self.motion_pid_applied = True
            self.get_logger().info("MCU motion PID disabled (use_motion_pid=False)")
            return

        kp = float(self.get_parameter_or("motion_kp", 1.2).value)
        ki = float(self.get_parameter_or("motion_ki", 0.25).value)
        kd = float(self.get_parameter_or("motion_kd", 0.40).value)
        forever = bool(self.get_parameter_or("motion_pid_forever", False).value)

        try:
            self.car.set_pid_param(kp, ki, kd, forever=forever)
            self.motion_pid_applied = True
            self.get_logger().info(f"MCU motion PID set: kp={kp} ki={ki} kd={kd} forever={forever}")
        except Exception as e:
            self.get_logger().warn(f"MCU motion PID set failed: {e}")

    def _is_lower_level(self) -> bool:
        return str(self.current_target_level).strip().upper() == "LOWER"

    def _pre_qr_goal_z(self) -> float:
        return float(self.tag_goal_z_pre_qr_lower if self._is_lower_level() else self.tag_goal_z_pre_qr_upper)

    def _place_goal_z(self) -> float:
        return float(self.goal_z_lower if self._is_lower_level() else self.goal_z_upper)


    # -------------------- Main FSM loop --------------------
    def _enter(self, new_state: str, now: float):
        if self.state != new_state:
            self.state = new_state
            self.state_enter_t = now
            self.get_logger().info(f"FSM -> {new_state}")
            self._sync_tag_target_for_state()   # <-- ВАЖНО
        if new_state in ("NAV_TO_PICK_ZONE", "NAV_TO_PLACE_ZONE"):
            self.mission_nav_future = None

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
                self._enter("NAV_TO_PLACE_ZONE", now) if self.use_mission_nav else self._enter("FIND_TAG_FOR_PLACE", now)
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

        if self.state == "ARM_SETTLE_AFTER_PICK":
            self._stop()
            if self._elapsed(now) >= float(self.get_parameter("arm_settle_after_pick_sec").value):
                self._enter("BACK_OFF_2S", now)
            return

        if self.state == "BACK_OFF_AFTER_PLACE":
            self._send(-self.place_back_off_speed, 0.0, 0.0)
            if self._elapsed(now) >= self.place_back_off_sec:
                self._stop()
                self._enter("WAIT", now)
            return


        #if self.state == "TURN_AFTER_PLACE":
        #self._send(0.0, 0.0, self.place_turn_speed)
        #if self._elapsed(now) >= self.place_turn_sec:
        #    self._stop()
        #    self._enter("FIND_TAG_FOR_PICK", now)
        #return

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

        observed = self._normalize_observed_qr(self.qr_payload)
        payload_ok = (self.expected_qr is None) or (observed == self.expected_qr)

        qr_ok = qr_alive and self.qr_valid and (self.qr_u is not None) and (self.qr_w is not None) and payload_ok

        # ----------------------------
        # 4) Main FSM
        # ----------------------------
        if self.state == "WAIT":
            # если нет куба — значит начинаем новый цикл
            if not self.arm_has_cube:
                # если задачи ещё нет — попросим у backend
                if self.current_task is None:
                    t = self._fetch_next_task()
                    if t is None:
                        self._stop()
                        return  # задач нет — стоим в WAIT
                    self._apply_task(t)

                # задача есть — едем в pick-зону (A)
                self._set_tag_target_id(-1)
                self._enter("NAV_TO_PICK_ZONE", now) if self.use_mission_nav else self._enter("FIND_TAG_FOR_PICK", now)
                return

            # если куб уже есть — значит надо ехать на place по текущей задаче
            if self.current_task is None:
                # это аварийная ситуация: куб есть, а задачи нет
                self.get_logger().warn("arm_has_cube=True but current_task is None -> going WAIT")
                self._stop()
                return

            self._enter("NAV_TO_PLACE_ZONE", now) if self.use_mission_nav else self._enter("FIND_TAG_FOR_PLACE", now)
            return

        # ======== NAVIGATION WAYPOINTS ========
        # ----------------------------
        if self.use_mission_nav and self.state == "NAV_TO_PICK_ZONE":
            if self.mission_nav_future is None:
                if not self.nav_pick_cli.wait_for_service(timeout_sec=1.0):
                    self.get_logger().warn("/mission/nav_pick not ready → retry later")
                    return
                self.get_logger().info("Requesting navigation to PICK zone")
                self.mission_nav_future = self.nav_pick_cli.call_async(Trigger.Request())
                self.nav_start_t = self._now_s()  # для таймаута

            if self.mission_nav_future.done():
                try:
                    res = self.mission_nav_future.result()
                    self.get_logger().info(f"NAV_PICK result: success={res.success}, msg='{res.message}'")
                    if res.success:
                        self._enter("FIND_TAG_FOR_PICK", now)
                    else:
                        self._enter("WAIT", now)
                except Exception as e:
                    self.get_logger().error(f"NAV_PICK call failed: {e}")
                    self._enter("WAIT", now)
                self.mission_nav_future = None
                self.nav_start_t = None

            # Таймаут навигации (опционально)
            if self.nav_start_t is not None and (now - self.nav_start_t) > 180.0:
                self.get_logger().error("Navigation to PICK timeout → aborting")
                self.mission_nav_future = None
                self.nav_start_t = None
                self._enter("WAIT", now)
            return

        if self.use_mission_nav and self.state == "NAV_TO_PLACE_ZONE":
            if self.mission_nav_future is None:
                if not self.nav_place_cli.wait_for_service(timeout_sec=1.0):
                    self.get_logger().warn("/mission/nav_place not ready → retry later")
                    return
                self.get_logger().info("Requesting navigation to PLACE zone")
                self.mission_nav_future = self.nav_place_cli.call_async(Trigger.Request())
                self.nav_start_t = self._now_s()

            if self.mission_nav_future.done():
                try:
                    res = self.mission_nav_future.result()
                    self.get_logger().info(f"NAV_PLACE result: success={res.success} msg='{res.message}'")
                    if res.success:
                        self._enter("FIND_TAG_FOR_PLACE", now)
                    else:
                        self._enter("WAIT", now)
                except Exception as e:
                    self.get_logger().error(f"NAV_PLACE call failed: {e}")
                    self._enter("WAIT", now)
                self.mission_nav_future = None
                self.nav_start_t = None

            if self.nav_start_t is not None and (now - self.nav_start_t) > 180.0:
                self.get_logger().error("Navigation to PLACE timeout → aborting")
                self.mission_nav_future = None
                self.nav_start_t = None
                self._enter("WAIT", now)
            return

        # ======== PICK ROUTE ========
        if self.state == "FIND_TAG_FOR_PICK":
            # просто ждём появления метки (нужного ID)
            self._stop()
            if self.current_task is None:
                self._enter("WAIT", now)
                return
            if tag_ok:
                self._enter("APPROACH_TAG_PREQR", now)
            return

        if self.state == "APPROACH_TAG_PREQR":
            if not tag_ok:
                self._stop()
                self._enter("FIND_TAG_FOR_PICK", now)
                return

            pre_goal = self._pre_qr_goal_z()
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

                # сброс "последнего QR" в FSM, чтобы первые 1-2 тика не ехали по мусору
                self.qr_valid = False
                self.qr_payload = None
                self.qr_u = None
                self.qr_w = None
                self.qr_last_t = 0.0
                self._enter("QR_FOCUS", now)
            return

        if self.state == "QR_FOCUS":
            pre_goal = self._pre_qr_goal_z()

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

            if getattr(self, "current_pick_level", "UPPER") == "LOWER":
                w_target = float(self.qr_target_w_px_lower)
            else:
                w_target = float(self.qr_target_w_px)
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
                self._enter("ARM_SETTLE_AFTER_PICK", now)
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

            z_err = z - self._place_goal_z()
            vx, vy, vz = self._tag_control(x_err=x_err, z_err=z_err, ang=ang)
            self._send(vx, vy, vz)

            arrived = (abs(ang) <= self.ang_tol and abs(x_err) <= self.grasp_x_tol and abs(z_err) <= self.z_tol)
            if arrived:
                self._stop()
                self._enter("CHOOSE_SLOT", now)
            return

        if self.state == "CHOOSE_SLOT":
            self._stop()

            if self.current_task is None or self.current_target_side is None:
                self.get_logger().warn("No current task/target side -> back to WAIT")
                self._enter("WAIT", now)
                return

            self.place_side = self.current_target_side  # "left"/"right" from backend
            self.get_logger().info(f"CHOOSE_SLOT: from task side={self.place_side}, level={self.current_target_level}")
            self._enter("STRAFE_TO_SLOT", now)
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

            lvl = String()
            lvl.data = str(self.current_target_level or "UPPER")
            self.pub_arm_target_level.publish(lvl)

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

                # после того как place сервис отработал и ты переходишь дальше:
                observed_qr = self._normalize_observed_qr(self.qr_payload) or self._normalize_observed_qr(self.rest_cube_qr_fallback)
                # успех считаем по факту: куб пропал из лапы (arm_has_cube False) — можно чуть позже, но для старта так
                # проще: считаем success=True, если place service ответил success (если у тебя это есть)
                success = True

                self._complete_task_async(self.current_task_id, success, observed_qr)

                # сбрасываем текущую задачу
                self.current_task = None
                self.current_task_id = None
                self.current_target_side = None
                self.current_target_level = None
                self.current_target_apriltag_id = None

                # сбрасываем qr ожидания, чтобы не держать старую задачу
                self.expected_qr = None

                # если у тебя в QRDetector require_target=True — можно явно очистить target
                m = String()
                m.data = ""
                self.pub_qr_target.publish(m)

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

    def _sync_tag_target_for_state(self):
        exp = self._expected_tag_id_for_state()
        self._set_tag_target_id(exp if exp is not None else -1)

    def _fetch_next_task(self):
        """GET /api/robot/tasks/next?robotId=R1 -> dict or None (if 204)"""
        if not self.rest_enable:
            return None

        url = f"{self.rest_base_url}/api/robot/tasks/next"
        try:
            r = requests.get(url, params={"robotId": self.rest_robot_id}, timeout=self.rest_timeout)
            if r.status_code == 204:
                return None
            r.raise_for_status()
            return r.json()
        except Exception as e:
            self.get_logger().warn(f"REST next task failed: {e}")
            return None

    def _normalize_observed_qr(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        parts = cleaned.split("/", 1)
        if len(parts) != 2:
            return None
        sku, manufacturer = (part.strip() for part in parts)
        if not sku or not manufacturer:
            return None
        return f"{sku}/{manufacturer}"

    def _complete_task_async(self, task_id: int, success: bool, observed_qr: str | None):
        """POST /api/robot/tasks/{id}/complete"""
        if not self.rest_enable:
            return

        url = f"{self.rest_base_url}/api/robot/tasks/{int(task_id)}/complete"
        payload = {
            "robotId": self.rest_robot_id,
            "success": bool(success),
            "observedQr": observed_qr
        }

        def worker():
            try:
                r = requests.post(url, json=payload, timeout=self.rest_timeout)
                if r.status_code >= 400:
                    self.get_logger().warn(f"REST complete -> {r.status_code}: {r.text[:200]}")
                else:
                    self.get_logger().info(f"REST complete -> {r.status_code} taskId={task_id}")
            except Exception as e:
                self.get_logger().warn(f"REST complete failed: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _apply_task(self, task_json: dict):
        self.current_task = task_json
        self.current_task_id = int(task_json["taskId"])
        self.pick_shelf_name = self.pick_shelf_code

        # куда класть
        shelf_code = str(task_json["targetShelfCode"]).strip().upper()
        side = str(task_json["targetSide"]).strip().upper()      # LEFT/RIGHT
        level = str(task_json["targetLevel"]).strip().upper()    # UPPER/LOWER

        self.place_shelf_name = shelf_code
        self.current_target_level = level
        self.current_target_side = "left" if side == "LEFT" else "right"
        raw = task_json.get("targetApriltagId", None)
        try:
            self.current_target_apriltag_id = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            self.current_target_apriltag_id = None

        if self.current_target_apriltag_id is not None and self.current_target_apriltag_id >= 0:
            self._set_tag_target_id(self.current_target_apriltag_id);
        else:
            self._set_tag_target_id(-1)

        self.get_logger().info(
            f"Task accepted: id={self.current_task_id} place={shelf_code} {side} {level} "
        )

        sku = str(task_json.get("sku", "")).strip()
        mfr = str(task_json.get("manufacturer", "")).strip()
        target_payload = f"{sku}/{mfr}".strip()
        self.expected_qr = self._normalize_observed_qr(target_payload)

        msg = String()
        msg.data = target_payload
        self.pub_qr_target.publish(msg)

        self.get_logger().info(f"QR target published: {target_payload}")

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

    def _set_tag_target_id(self, tag_id: int):
        """Publish desired AprilTag id for detector. -1 disables filtering."""
        try:
            tag_id = int(tag_id)
        except Exception:
            tag_id = -1

        if self._last_sent_tag_target == tag_id:
            return  # не спамим

        m = Int32()
        m.data = tag_id
        self.pub_tag_target.publish(m)
        self._last_sent_tag_target = tag_id
        self.get_logger().info(f"Tag target id -> {tag_id}")

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
