#!/usr/bin/env python3
import time
import numpy as np
import cv2

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy

from sensor_msgs.msg import Image
from std_msgs.msg import String, Float32, Bool
from cv_bridge import CvBridge

try:
    from pyzbar.pyzbar import decode as zbar_decode
except Exception:
    zbar_decode = None


def _poly_to_np(poly) -> np.ndarray:
    pts = []
    for p in poly:
        if hasattr(p, "x") and hasattr(p, "y"):
            pts.append([float(p.x), float(p.y)])
        else:
            pts.append([float(p[0]), float(p[1])])
    return np.array(pts, dtype=np.float32)


def _geom_from_polygon(pts: np.ndarray):
    """
    Returns:
      u_center (px), v_center (px), w_px (px), area (px^2)
    """
    if pts is None or len(pts) < 2:
        return None, None, None, None

    u_center = float(np.mean(pts[:, 0]))
    v_center = float(np.mean(pts[:, 1]))

    rect = cv2.minAreaRect(pts.reshape(-1, 1, 2))
    (w, h) = rect[1]
    w_px = float(max(w, h))
    area = float(w * h)
    return u_center, v_center, w_px, area


class QRDetectorNode(Node):
    """
    LOCK-ON QR detector:

    - Декодируем QR через pyzbar.
    - Если target задан, берём только QR с таким payload.
    - Если в кадре несколько одинаковых target-QR:
        1) если лока нет -> выбираем "лучший" (по умолчанию самый крупный area)
        2) если лок есть -> выбираем QR, который ближе всего к прошлой позиции (u,v) в пределах "окна"
    - Если QR кратковременно пропал (камера) -> НЕ переключаемся на другой.
    - Сбрасываем лок, если цели не видно дольше lock_release_sec.
    """

    def __init__(self):
        super().__init__("qr_detector_node")

        # ---- params ----
        self.declare_parameter("image_topic", "/camera/color/image_raw")
        self.declare_parameter("publish_hz", 20.0)
        self.declare_parameter("valid_hold_sec", 0.9)       # держим valid True после последней детекции
        self.declare_parameter("only_qrcode_type", True)

        # target control
        self.declare_parameter("require_target", True)     # если True и target пустой -> ничего не детектим

        # lock-on tuning
        self.declare_parameter("lock_enable", True)
        self.declare_parameter("lock_gate_px_min", 50.0)    # минимум "окна" в пикселях
        self.declare_parameter("lock_gate_k_w", 0.8)        # добавка окна пропорционально размеру QR (w_px)
        self.declare_parameter("lock_release_sec", 2.0)     # сколько ждать потерю до сброса лока

        # first acquire rule: "max_area" or "closest_center"
        self.declare_parameter("acquire_rule", "max_area")

        image_topic = self.get_parameter("image_topic").value
        publish_hz = float(self.get_parameter("publish_hz").value)
        publish_hz = 20.0 if publish_hz <= 0 else publish_hz

        # ---- qos: keep only last frame ----
        qos_img = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.sub = self.create_subscription(Image, image_topic, self.on_image, qos_img)

        self.pub_valid = self.create_publisher(Bool, "/qr/valid", 10)
        self.pub_u = self.create_publisher(Float32, "/qr/u", 10)
        self.pub_w = self.create_publisher(Float32, "/qr/w", 10)
        self.pub_data = self.create_publisher(String, "/qr/data", 10)

        self.bridge = CvBridge()

        if zbar_decode is None:
            self.get_logger().error("pyzbar not available. Install: sudo apt-get install libzbar0 && pip3 install pyzbar")

        self._target_payload = ""  # normalized "SKU/MANUFACTURER"
        qos_target = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )

        self.create_subscription(String, "/qr/target", self._on_target, qos_target)

        # latest frame storage
        self._latest_img_msg = None
        self._latest_seq = 0
        self._processed_seq = 0

        # last published detection (latched for valid_hold_sec)
        self._last_det_t = 0.0
        self._last_u = None
        self._last_w = None
        self._last_data = ""

        # lock state (track one of identical QR)
        self._lock_active = False
        self._lock_u = None
        self._lock_v = None
        self._lock_w = None
        self._lock_last_seen_t = 0.0  # when lock was last confirmed

        self.timer = self.create_timer(1.0 / publish_hz, self.tick)
        self.get_logger().info(
            f"QR detector started. image_topic={image_topic}, publish_hz={publish_hz}, hold={self.get_parameter('valid_hold_sec').value}"
        )

    @staticmethod
    def _norm_payload(s: str) -> str:
        if s is None:
            return ""
        s = s.strip().upper()
        s = s.replace(" / ", "/").replace("/ ", "/").replace(" /", "/")
        return s

    def _reset_lock_and_last(self):
        self._last_u = None
        self._last_w = None
        self._last_data = ""
        self._last_det_t = 0.0

        self._lock_active = False
        self._lock_u = None
        self._lock_v = None
        self._lock_w = None
        self._lock_last_seen_t = 0.0

    def _on_target(self, msg: String):
        self._target_payload = self._norm_payload(msg.data)
        self.get_logger().info(f"QR target set to: '{self._target_payload}'")
        # при смене цели нельзя ехать по старой/чужой детекции
        self._reset_lock_and_last()

    def on_image(self, msg: Image):
        self._latest_img_msg = msg
        self._latest_seq += 1

    def _decode_all(self, gray):
        """
        Returns list of detections:
          [{"u":..., "v":..., "w":..., "area":..., "data":..., "data_n":...}, ...]
        already filtered by target (if set)
        """
        if zbar_decode is None:
            return []

        target = self._target_payload
        require_target = bool(self.get_parameter("require_target").value)
        if require_target and target == "":
            return []

        results = zbar_decode(gray)
        if not results:
            return []

        only_qr = bool(self.get_parameter("only_qrcode_type").value)

        dets = []
        for r in results:
            try:
                r_type = getattr(r, "type", "")
            except Exception:
                r_type = ""

            if only_qr and r_type and r_type.upper() != "QRCODE":
                continue

            try:
                data = r.data.decode("utf-8", errors="replace")
            except Exception:
                data = str(r.data)

            data_n = self._norm_payload(data)

            # target filter (если target задан — оставляем только совпадающие)
            if target != "" and data_n != target:
                continue

            # geometry
            if hasattr(r, "polygon") and r.polygon:
                pts = _poly_to_np(r.polygon)
                u, v, w, area = _geom_from_polygon(pts)
            else:
                rect = getattr(r, "rect", None)
                if rect is None:
                    continue
                x, y, ww, hh = rect.left, rect.top, rect.width, rect.height
                u = float(x + ww / 2.0)
                v = float(y + hh / 2.0)
                w = float(max(ww, hh))
                area = float(ww * hh)

            if u is None or v is None or w is None or area is None:
                continue

            dets.append({"u": u, "v": v, "w": w, "area": area, "data": data, "data_n": data_n})

        return dets

    def _gate_px(self):
        gate_min = float(self.get_parameter("lock_gate_px_min").value)
        k = float(self.get_parameter("lock_gate_k_w").value)
        w = float(self._lock_w) if (self._lock_w is not None) else 0.0
        return max(gate_min, k * w)

    def _select_detection(self, dets, img_w, img_h):
        """
        Pick one detection to publish.
        """
        if not dets:
            return None

        lock_enable = bool(self.get_parameter("lock_enable").value)

        # 1) If locked: pick the detection closest to last lock position within gate
        if lock_enable and self._lock_active and (self._lock_u is not None) and (self._lock_v is not None):
            gate = self._gate_px()

            def in_gate(d):
                return (abs(d["u"] - self._lock_u) <= gate) and (abs(d["v"] - self._lock_v) <= gate)

            candidates = [d for d in dets if in_gate(d)]
            if candidates:
                # choose nearest to previous (u,v)
                def dist2(d):
                    du = d["u"] - self._lock_u
                    dv = d["v"] - self._lock_v
                    return du * du + dv * dv

                best = min(candidates, key=dist2)
                return best

            # if none in gate -> do not switch immediately (let lock timeout handle it)
            return None

        # 2) Not locked yet: acquire one
        rule = str(self.get_parameter("acquire_rule").value).strip().lower()
        if rule == "closest_center":
            cx = float(img_w) * 0.5
            cy = float(img_h) * 0.5

            def dcenter(d):
                du = d["u"] - cx
                dv = d["v"] - cy
                return du * du + dv * dv

            best = min(dets, key=dcenter)
        else:
            # default max_area (usually closest cube)
            best = max(dets, key=lambda d: float(d["area"]))

        return best

    def tick(self):
        now = time.time()
        hold = float(self.get_parameter("valid_hold_sec").value)
        if hold < 0:
            hold = 0.0

        # process newest frame
        if self._latest_img_msg is not None and self._latest_seq != self._processed_seq:
            self._processed_seq = self._latest_seq

            gray = None
            img_w, img_h = 0, 0
            try:
                bgr = self.bridge.imgmsg_to_cv2(self._latest_img_msg, desired_encoding="bgr8")
                img_h, img_w = bgr.shape[:2]
                gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            except Exception as e:
                self.get_logger().warn(f"cv_bridge/convert error: {e}")
                gray = None

            if gray is not None:
                dets = self._decode_all(gray)
                chosen = self._select_detection(dets, img_w, img_h)

                lock_enable = bool(self.get_parameter("lock_enable").value)
                release_sec = float(self.get_parameter("lock_release_sec").value)

                if chosen is not None:
                    # update last publish
                    self._last_u = float(chosen["u"])
                    self._last_w = float(chosen["w"])
                    self._last_data = str(chosen["data"])
                    self._last_det_t = now

                    # update lock
                    if lock_enable:
                        self._lock_active = True
                        self._lock_u = float(chosen["u"])
                        self._lock_v = float(chosen["v"])
                        self._lock_w = float(chosen["w"])
                        self._lock_last_seen_t = now

                else:
                    # no chosen: maybe locked but temporarily lost -> release if too long
                    if lock_enable and self._lock_active:
                        if (now - self._lock_last_seen_t) > release_sec:
                            self._lock_active = False
                            self._lock_u = None
                            self._lock_v = None
                            self._lock_w = None
                            self._lock_last_seen_t = 0.0

        # publish (latched valid)
        valid = (self._last_u is not None) and ((now - self._last_det_t) <= hold)

        vb = Bool()
        vb.data = bool(valid)
        self.pub_valid.publish(vb)

        if not valid:
            return

        mu = Float32()
        mu.data = float(self._last_u)
        self.pub_u.publish(mu)

        mw = Float32()
        mw.data = float(self._last_w)
        self.pub_w.publish(mw)

        ms = String()
        ms.data = self._last_data
        self.pub_data.publish(ms)


def main():
    rclpy.init()
    node = QRDetectorNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
