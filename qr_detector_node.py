#!/usr/bin/env python3
import time
import numpy as np
import cv2

import rclpy
from rclpy.node import Node

from sensor_msgs.msg import Image
from std_msgs.msg import String, Float32, Bool
from cv_bridge import CvBridge

# pyzbar
try:
    from pyzbar.pyzbar import decode as zbar_decode
except Exception:
    zbar_decode = None


class QRDetectorNode(Node):
    def __init__(self):
        super().__init__('qr_detector_node')

        # --- Params ---
        self.declare_parameter('image_topic', '/camera/color/image_raw')
        self.declare_parameter('out_topic', '/qr/data')
        self.declare_parameter('qr_u', '/qr/u')
        self.declare_parameter('qr_w', '/qr/w')
        self.declare_parameter('qr_valid', '/qr/valid')

        self.declare_parameter('max_fps', 20.0)            # обработка кадров
        self.declare_parameter('publish_rate_hz', 10.0)    # частота публикации (heartbeat)

        self.declare_parameter('only_on_change', False)

        # Strict target payload (only publish when this exact text is found)
        self.declare_parameter('target_payload', "Lower shelf")

        # Latch / anti-drop
        self.declare_parameter('latch_sec', 2)             # сколько секунд держим последнее валидное измерение
        self.declare_parameter('max_miss', 8)              # сколько кадров подряд можно "не видеть" QR (для статистики)

        # Smoothing
        self.declare_parameter('ema_alpha', 0.60)          # 0..1, больше -> быстрее реагирует

        image_topic = self.get_parameter('image_topic').value
        out_topic = self.get_parameter('out_topic').value
        pub_qr_u = self.get_parameter('qr_u').value
        pub_qr_w = self.get_parameter('qr_w').value
        pub_qr_valid = self.get_parameter('qr_valid').value

        self.target_payload = self.get_parameter('target_payload').value

        # --- ROS I/O ---
        self.sub = self.create_subscription(Image, image_topic, self.on_image, 10)
        self.pub_text = self.create_publisher(String, out_topic, 10)
        self.pub_u = self.create_publisher(Float32, pub_qr_u, 10)
        self.pub_w = self.create_publisher(Float32, pub_qr_w, 10)
        self.pub_valid = self.create_publisher(Bool, pub_qr_valid, 10)

        # --- CV ---
        self.bridge = CvBridge()

        if zbar_decode is None:
            self.get_logger().error(
                "pyzbar is not available. Install: sudo apt-get install libzbar0 && pip install pyzbar"
            )

        # --- State ---
        self._last_frame_t = 0.0
        self._last_payload_pub = None

        # last good detection (latched)
        self.last_good_payload = None
        self.last_good_u = None
        self.last_good_w = None
        self.last_good_t = 0.0

        # EMA filtered values
        self.u_f = None
        self.w_f = None

        self.miss_count = 0

        # publish timer (heartbeat)
        rate = float(self.get_parameter('publish_rate_hz').value)
        rate = 10.0 if rate <= 0 else rate
        self.timer = self.create_timer(1.0 / rate, self.publish_tick)

        self.get_logger().info(
            f"QR detector (pyzbar) started. Sub: {image_topic} | Pub: {out_topic}, {pub_qr_u}, {pub_qr_w}, {pub_qr_valid} | "
            f"target_payload='{self.target_payload}'"
        )

    def _fps_limit(self) -> bool:
        max_fps = float(self.get_parameter('max_fps').value)
        now = time.time()
        if max_fps > 0 and (now - self._last_frame_t) < (1.0 / max_fps):
            return False
        self._last_frame_t = now
        return True

    @staticmethod
    def _poly_to_np(poly) -> np.ndarray:
        """
        poly from pyzbar is a list of Points (x,y). Can be 4 points, but may be >4.
        returns Nx2 float32
        """
        pts = []
        for p in poly:
            # p may have attributes x,y or be tuple-like
            if hasattr(p, "x") and hasattr(p, "y"):
                pts.append([float(p.x), float(p.y)])
            else:
                pts.append([float(p[0]), float(p[1])])
        return np.array(pts, dtype=np.float32)

    @staticmethod
    def _geom_from_points(pts: np.ndarray):
        """
        Compute u_center and w_px from polygon points.
        - u_center: mean x
        - w_px: width of the QR in pixels (robust):
            * if >=4 points: minAreaRect width (max side)
        """
        if pts is None or len(pts) < 2:
            return None, None

        u_center = float(np.mean(pts[:, 0]))

        # robust width using minAreaRect (handles 4..N points)
        rect = cv2.minAreaRect(pts.reshape(-1, 1, 2))
        (w, h) = rect[1]
        w_px = float(max(w, h))  # take larger side as "width"

        return u_center, w_px

    def on_image(self, msg: Image):
        if not self._fps_limit():
            return

        if zbar_decode is None:
            # can't decode, count miss
            self.miss_count += 1
            return

        # Convert image
        try:
            img = self.bridge.imgmsg_to_cv2(msg, desired_encoding='rgb8')
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        except Exception as e:
            self.get_logger().warning(f"cv_bridge error: {e}")
            return

        # Decode all symbols in frame
        results = zbar_decode(gray)
        if not results:
            self.miss_count += 1
            return

        target = (self.get_parameter('target_payload').value or "").strip()

        chosen = None
        chosen_payload = None
        chosen_pts = None

        # pick first matching
        for r in results:
            try:
                payload = r.data.decode('utf-8', errors='ignore')
            except Exception:
                payload = str(r.data)

            payload_stripped = payload.strip()

            if target == "":
                # ANY: take first non-empty
                if payload_stripped != "":
                    chosen = r
                    chosen_payload = payload
                    break
            else:
                # STRICT: exact match
                if payload == target:
                    chosen = r
                    chosen_payload = payload
                    break

        if chosen is None:
            self.miss_count += 1
            return

        # Get polygon points if available, else fallback to rect
        if hasattr(chosen, "polygon") and chosen.polygon:
            pts = self._poly_to_np(chosen.polygon)
        else:
            # fallback to rect: left, top, width, height
            rect = getattr(chosen, "rect", None)
            if rect is None:
                self.miss_count += 1
                return
            x, y, w, h = rect.left, rect.top, rect.width, rect.height
            pts = np.array(
                [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
                dtype=np.float32
            )

        u_center, w_px = self._geom_from_points(pts)
        if u_center is None or w_px is None:
            self.miss_count += 1
            return

        # EMA smoothing
        a = float(self.get_parameter('ema_alpha').value)
        a = max(0.0, min(1.0, a))

        self.u_f = u_center if self.u_f is None else (1.0 - a) * self.u_f + a * u_center
        self.w_f = w_px     if self.w_f is None else (1.0 - a) * self.w_f + a * w_px

        # Save as last good (latched)
        self.last_good_payload = chosen_payload
        self.last_good_u = float(self.u_f)
        self.last_good_w = float(self.w_f)
        self.last_good_t = time.time()
        self.miss_count = 0

    def publish_tick(self):
        """Publish at fixed rate; latch last_good for latch_sec."""
        now = time.time()
        latch_sec = float(self.get_parameter('latch_sec').value)
        latch_sec = 0.0 if latch_sec < 0 else latch_sec

        valid = False
        if self.last_good_payload is not None and (now - self.last_good_t) <= latch_sec:
            valid = True

        # valid flag
        vb = Bool()
        vb.data = bool(valid)
        self.pub_valid.publish(vb)

        if not valid:
            return

        # publish u/w every tick (stable control)
        mu = Float32()
        mu.data = float(self.last_good_u)
        self.pub_u.publish(mu)

        mw = Float32()
        mw.data = float(self.last_good_w)
        self.pub_w.publish(mw)

        # publish payload (optionally only on change)
        payload = self.last_good_payload
        only_on_change = bool(self.get_parameter('only_on_change').value)
        if not (only_on_change and payload == self._last_payload_pub):
            self._last_payload_pub = payload
            s = String()
            s.data = payload
            self.pub_text.publish(s)
            self.get_logger().info(
                f"QR latched: '{payload}' | u={self.last_good_u:.1f}px w={self.last_good_w:.1f}px "
                f"(miss_count={self.miss_count})"
            )


def main():
    rclpy.init()
    node = QRDetectorNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
