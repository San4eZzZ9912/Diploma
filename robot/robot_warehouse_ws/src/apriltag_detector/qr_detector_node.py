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
      u_center (px), w_px (px), area (px^2)
    """
    if pts is None or len(pts) < 2:
        return None, None, None

    u_center = float(np.mean(pts[:, 0]))

    rect = cv2.minAreaRect(pts.reshape(-1, 1, 2))
    (w, h) = rect[1]
    w_px = float(max(w, h))
    area = float(w * h)
    return u_center, w_px, area


class QRDetectorNode(Node):
    """
    - Subscribes to camera image
    - Always keeps ONLY the latest frame (no backlog)
    - Decodes QR via pyzbar
    - Publishes:
        /qr/valid (Bool)
        /qr/u     (Float32)  center x in pixels
        /qr/w     (Float32)  "width" of QR in pixels (max side of minAreaRect)
        /qr/data  (String)   decoded payload
    - valid_hold_sec: keep valid True for a short time after last detection
      to avoid QR_FOCUS stopping due to brief decode drop.
    """

    def __init__(self):
        super().__init__("qr_detector_node")

        # ---- params ----
        self.declare_parameter("image_topic", "/camera/color/image_raw")
        self.declare_parameter("publish_hz", 20.0)          # publish + decode tick rate
        self.declare_parameter("valid_hold_sec", 0.9)       # how long we keep qr_valid True after last detection
        self.declare_parameter("only_qrcode_type", True)    # ignore other barcodes

        image_topic = self.get_parameter("image_topic").value
        publish_hz = float(self.get_parameter("publish_hz").value)
        publish_hz = 20.0 if publish_hz <= 0 else publish_hz

        # ---- qos: keep only last frame, best effort (sensor-like) ----
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )

        self.sub = self.create_subscription(Image, image_topic, self.on_image, qos)

        self.pub_valid = self.create_publisher(Bool, "/qr/valid", 10)
        self.pub_u = self.create_publisher(Float32, "/qr/u", 10)
        self.pub_w = self.create_publisher(Float32, "/qr/w", 10)
        self.pub_data = self.create_publisher(String, "/qr/data", 10)

        self.bridge = CvBridge()

        if zbar_decode is None:
            self.get_logger().error("pyzbar not available. Install: sudo apt-get install libzbar0 && pip3 install pyzbar")

        self._target_payload = ""  # normalized "SKU/MANUFACTURER"
        self.create_subscription(String, "/qr/target", self._on_target, 10)
            
        # latest frame storage (no backlog)
        self._latest_img_msg = None
        self._latest_seq = 0
        self._processed_seq = 0

        # last detection (latched)
        self._last_det_t = 0.0
        self._last_u = None
        self._last_w = None
        self._last_data = ""

        self.timer = self.create_timer(1.0 / publish_hz, self.tick)

        self.get_logger().info(
            f"QR detector started. image_topic={image_topic}, publish_hz={publish_hz}, valid_hold_sec={self.get_parameter('valid_hold_sec').value}"
        )

    @staticmethod
    def _norm_payload(s: str) -> str:
        if s is None:
            return ""
        s = s.strip().upper()
        s = s.replace(" / ", "/").replace("/ ", "/").replace(" /", "/")
        return s

    def _on_target(self, msg: String):
        self._target_payload = self._norm_payload(msg.data)
        self.get_logger().info(f"QR target set to: '{self._target_payload}'")
        
    def on_image(self, msg: Image):
        # keep only latest
        self._latest_img_msg = msg
        self._latest_seq += 1

    def _decode_qr_from_gray(self, gray):
        if zbar_decode is None:
            return None

        target = self._target_payload  # already normalized

        results = zbar_decode(gray)
        if not results:
            return None

        only_qr = bool(self.get_parameter("only_qrcode_type").value)

        best = None
        best_area = -1.0
        best_u = None
        best_w = None
        best_data = None

        for r in results:
            try:
                r_type = getattr(r, "type", "")
            except Exception:
                r_type = ""

            if only_qr and r_type and r_type.upper() != "QRCODE":
                continue

            # payload
            try:
                data = r.data.decode("utf-8", errors="replace")
            except Exception:
                data = str(r.data)

            data_n = self._norm_payload(data)

            # Если target задан — игнорируем все чужие QR
            if target != "" and data_n != target:
                continue

            # geometry
            if hasattr(r, "polygon") and r.polygon:
                pts = _poly_to_np(r.polygon)
                u, w, area = _geom_from_polygon(pts)
            else:
                rect = getattr(r, "rect", None)
                if rect is None:
                    continue
                x, y, ww, hh = rect.left, rect.top, rect.width, rect.height
                u = float(x + ww / 2.0)
                w = float(max(ww, hh))
                area = float(ww * hh)

            if u is None or w is None or area is None:
                continue

            # choose the largest (most likely the target we're approaching)
            if area > best_area:
                best_area = area
                best = r
                best_u = u
                best_w = w
                best_data = data

        if best is None:
            return None

        return (best_u, best_w, best_data)

    def tick(self):
        now = time.time()
        hold = float(self.get_parameter("valid_hold_sec").value)
        if hold < 0:
            hold = 0.0

        # process newest frame (if exists)
        if self._latest_img_msg is not None and self._latest_seq != self._processed_seq:
            self._processed_seq = self._latest_seq

            try:
                bgr = self.bridge.imgmsg_to_cv2(self._latest_img_msg, desired_encoding="bgr8")
                gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            except Exception as e:
                self.get_logger().warn(f"cv_bridge/convert error: {e}")
                gray = None

            if gray is not None:
                det = self._decode_qr_from_gray(gray)
                if det is not None:
                    u, w, data = det
                    self._last_u = float(u)
                    self._last_w = float(w)
                    self._last_data = str(data)
                    self._last_det_t = now

        # publish (latched-valid behavior)
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
