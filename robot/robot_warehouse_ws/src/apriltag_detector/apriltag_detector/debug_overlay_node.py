#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from typing import Optional

import rclpy
from rclpy.node import Node

from sensor_msgs.msg import Image, CameraInfo
from std_msgs.msg import Bool, Float32, String, Int32
from geometry_msgs.msg import Vector3

import cv2
import numpy as np
from cv_bridge import CvBridge


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class DebugOverlayNode(Node):
    """
    Input (camera):
      - /camera/color/image_raw (sensor_msgs/Image)
      - /camera/color/camera_info (sensor_msgs/CameraInfo)

    Input (AprilTag, as in apriltag_detector_node.py):
      - /tag/seen (std_msgs/Bool)
      - /tag/id (std_msgs/Int32)
      - /tag/pose_t (geometry_msgs/Vector3)
      - /tag/u_px (std_msgs/Float32)
      - /tag/ang_err_normal (std_msgs/Float32)

    Input (QR, as in qr_detector_node.py):
      - /qr/valid (std_msgs/Bool)
      - /qr/u (std_msgs/Float32)
      - /qr/w (std_msgs/Float32)
      - /qr/data (std_msgs/String)

    Output:
      - /debug/overlay_image (sensor_msgs/Image)
    """

    def __init__(self):
        super().__init__("debug_overlay_node")

        # -------- topics --------
        self.declare_parameter("image_topic", "/camera/color/image_raw")
        self.declare_parameter("camera_info_topic", "/camera/color/camera_info")
        self.declare_parameter("out_topic", "/debug/overlay_image")

        # -------- grasp zone (fixed rectangle, ratios of image size) --------
        self.declare_parameter("zone_center_x", 0.5)
        self.declare_parameter("zone_center_y", 0.5)
        self.declare_parameter("zone_width", 0.35)
        self.declare_parameter("zone_height", 0.35)

        # -------- dynamic overlay controls --------
        self.declare_parameter("draw_dynamic_tag_band", True)
        self.declare_parameter("draw_qr_markers", True)

        # -------- geometry / tolerances (similar to your FSM logic) --------
        self.declare_parameter("jaw_width", 0.05)               # m
        self.declare_parameter("tag_size", 0.04)                # m
        self.declare_parameter("camera_offset_right_m", 0.005)  # m
        self.declare_parameter("grasp_margin", 0.005)           # m

        # Optional: show "ready" status using these tolerances
        self.declare_parameter("ang_tolerance", 0.03)           # rad
        self.declare_parameter("z_goal_pre_qr", 0.32)           # m (for display only)
        self.declare_parameter("z_goal_place", 0.34)            # m (for display only)
        self.declare_parameter("z_tolerance", 0.03)             # m

        # -------- freshness (to avoid lying with stale data) --------
        self.declare_parameter("tag_timeout", 0.5)  # sec
        self.declare_parameter("qr_timeout", 0.5)   # sec

        # -------- ROS I/O --------
        self.bridge = CvBridge()
        self.pub = self.create_publisher(Image, str(self.get_parameter("out_topic").value), 10)

        self.create_subscription(CameraInfo, str(self.get_parameter("camera_info_topic").value), self.on_caminfo, 10)
        self.create_subscription(Image, str(self.get_parameter("image_topic").value), self.on_image, 10)

        # AprilTag subs
        self.create_subscription(Bool, "/tag/seen", self.on_tag_seen, 10)
        self.create_subscription(Int32, "/tag/id", self.on_tag_id, 10)
        self.create_subscription(Vector3, "/tag/pose_t", self.on_tag_pose_t, 10)
        self.create_subscription(Float32, "/tag/u_px", self.on_tag_u_px, 10)
        self.create_subscription(Float32, "/tag/ang_err_normal", self.on_tag_ang, 10)

        # QR subs
        self.create_subscription(Bool, "/qr/valid", self.on_qr_valid, 10)
        self.create_subscription(Float32, "/qr/u", self.on_qr_u, 10)
        self.create_subscription(Float32, "/qr/w", self.on_qr_w, 10)
        self.create_subscription(String, "/qr/data", self.on_qr_data, 10)

        # -------- cached camera intrinsics --------
        self.fx: Optional[float] = None
        self.cx: Optional[float] = None

        # -------- cached tag --------
        self.tag_seen = False
        self.tag_id: Optional[int] = None
        self.tag_t: Optional[Vector3] = None
        self.tag_u_px: Optional[float] = None
        self.tag_ang: Optional[float] = None
        self.tag_last_ts = 0.0

        # -------- cached qr --------
        self.qr_valid = False
        self.qr_u: Optional[float] = None
        self.qr_w: Optional[float] = None
        self.qr_data: Optional[str] = None
        self.qr_last_ts = 0.0

        # FPS
        self._last_frame_wall = time.time()
        self._fps = 0.0

        self.get_logger().info(
            f"debug_overlay_node started. in={self.get_parameter('image_topic').value} "
            f"caminfo={self.get_parameter('camera_info_topic').value} out={self.get_parameter('out_topic').value}"
        )

    # ---------------- time helpers ----------------
    def _now_s(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    # ---------------- camera info ----------------
    def on_caminfo(self, msg: CameraInfo):
        try:
            self.fx = float(msg.k[0])
            self.cx = float(msg.k[2])
        except Exception:
            self.fx = None
            self.cx = None

    # ---------------- tag callbacks ----------------
    def _touch_tag(self):
        self.tag_last_ts = self._now_s()

    def on_tag_seen(self, msg: Bool):
        self.tag_seen = bool(msg.data)
        self._touch_tag()

    def on_tag_id(self, msg: Int32):
        self.tag_id = int(msg.data)
        self._touch_tag()

    def on_tag_pose_t(self, msg: Vector3):
        self.tag_t = msg
        self._touch_tag()

    def on_tag_u_px(self, msg: Float32):
        self.tag_u_px = float(msg.data)
        self._touch_tag()

    def on_tag_ang(self, msg: Float32):
        self.tag_ang = float(msg.data)
        self._touch_tag()

    # ---------------- qr callbacks ----------------
    def _touch_qr(self):
        self.qr_last_ts = self._now_s()

    def on_qr_valid(self, msg: Bool):
        self.qr_valid = bool(msg.data)
        self._touch_qr()

    def on_qr_u(self, msg: Float32):
        self.qr_u = float(msg.data)
        self._touch_qr()

    def on_qr_w(self, msg: Float32):
        self.qr_w = float(msg.data)
        self._touch_qr()

    def on_qr_data(self, msg: String):
        self.qr_data = msg.data
        self._touch_qr()

    # ---------------- drawing helpers ----------------
    @staticmethod
    def _draw_text_block(img, lines, x, y, line_h=18):
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.5
        thickness = 1

        widths = []
        for s in lines:
            (tw, _), _ = cv2.getTextSize(s, font, scale, thickness)
            widths.append(tw)
        w = (max(widths) if widths else 0) + 12
        h = (len(lines) * line_h) + 10

        cv2.rectangle(img, (x, y), (x + w, y + h), (0, 0, 0), -1)
        cv2.rectangle(img, (x, y), (x + w, y + h), (255, 255, 255), 1)

        yy = y + 22
        for s in lines:
            cv2.putText(img, s, (x + 6, yy), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)
            yy += line_h

    def _draw_fixed_zone(self, img, w, h, ready: bool):
        cx = float(self.get_parameter("zone_center_x").value)
        cy = float(self.get_parameter("zone_center_y").value)
        zw = float(self.get_parameter("zone_width").value)
        zh = float(self.get_parameter("zone_height").value)

        x0 = int((cx - zw / 2.0) * w)
        y0 = int((cy - zh / 2.0) * h)
        x1 = int((cx + zw / 2.0) * w)
        y1 = int((cy + zh / 2.0) * h)

        x0 = int(clamp(x0, 0, w - 1))
        y0 = int(clamp(y0, 0, h - 1))
        x1 = int(clamp(x1, 0, w - 1))
        y1 = int(clamp(y1, 0, h - 1))

        color = (0, 255, 0) if ready else (0, 0, 255)
        cv2.rectangle(img, (x0, y0), (x1, y1), color, 2)
        cv2.putText(img, "GRASP ZONE", (x0 + 6, max(20, y0 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

    def _draw_dynamic_tag_band(self, img, w, h, tag_alive: bool):
        """
        рисует:
          - u_target (зелёная линия)
          - полосу допуска u_target +/- tol_px (жёлтые границы + легкая заливка)
          - фактический tag_u_px (голубая линия)
        """
        if not bool(self.get_parameter("draw_dynamic_tag_band").value):
            return
        if not tag_alive:
            return
        if self.fx is None or self.cx is None:
            return
        if self.tag_t is None:
            return

        z = float(self.tag_t.z)
        if z <= 1e-6:
            return

        jaw_width = float(self.get_parameter("jaw_width").value)
        tag_size = float(self.get_parameter("tag_size").value)
        cam_off = float(self.get_parameter("camera_offset_right_m").value)
        grasp_margin = float(self.get_parameter("grasp_margin").value)

        jaw_half = jaw_width / 2.0
        tag_half = tag_size / 2.0

        tol_world = (jaw_half - tag_half) + grasp_margin
        tol_px = (tol_world / z) * float(self.fx)

        u_target = float(self.cx) + float(self.fx) * (cam_off / z)

        u0 = int(clamp(int(u_target - tol_px), 0, w - 1))
        u1 = int(clamp(int(u_target + tol_px), 0, w - 1))
        uT = int(clamp(int(u_target), 0, w - 1))

        # filled band
        overlay = img.copy()
        cv2.rectangle(overlay, (u0, 0), (u1, h - 1), (255, 255, 255), -1)
        cv2.addWeighted(overlay, 0.12, img, 0.88, 0, img)

        # borders + target
        cv2.line(img, (u0, 0), (u0, h - 1), (0, 255, 255), 2)
        cv2.line(img, (u1, 0), (u1, h - 1), (0, 255, 255), 2)
        cv2.line(img, (uT, 0), (uT, h - 1), (0, 220, 0), 2)
        cv2.putText(img, "u_target", (uT + 6, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 0), 2, cv2.LINE_AA)

        # actual tag u
        if self.tag_u_px is not None:
            ut = int(clamp(int(self.tag_u_px), 0, w - 1))
            cv2.line(img, (ut, 0), (ut, h - 1), (255, 200, 0), 2)
            cv2.putText(img, "tag_u", (ut + 6, 45),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 200, 0), 2, cv2.LINE_AA)

    def _draw_qr_markers(self, img, w, h, qr_alive: bool):
        if not bool(self.get_parameter("draw_qr_markers").value):
            return
        if not qr_alive or (self.qr_u is None):
            return
        u = int(clamp(int(self.qr_u), 0, w - 1))
        cv2.line(img, (u, 0), (u, h - 1), (255, 0, 255), 2)
        cv2.putText(img, "qr_u", (u + 6, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2, cv2.LINE_AA)

    # ---------------- main image callback ----------------
    def on_image(self, msg: Image):
        # FPS
        now_wall = time.time()
        dt = now_wall - self._last_frame_wall
        if dt > 1e-6:
            self._fps = 0.9 * self._fps + 0.1 * (1.0 / dt)
        self._last_frame_wall = now_wall

        try:
            img = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as e:
            self.get_logger().warn(f"cv_bridge img convert failed: {e}")
            return

        h, w = img.shape[:2]
        tnow = self._now_s()

        tag_timeout = float(self.get_parameter("tag_timeout").value)
        qr_timeout = float(self.get_parameter("qr_timeout").value)
        tag_alive = (tnow - self.tag_last_ts) <= tag_timeout
        qr_alive = (tnow - self.qr_last_ts) <= qr_timeout

        # compute "ready" by tag tolerances (как в FSM: ang + x + z)
        ready_tag = False
        x_err = None
        z = None

        jaw_width = float(self.get_parameter("jaw_width").value)
        tag_size = float(self.get_parameter("tag_size").value)
        cam_off = float(self.get_parameter("camera_offset_right_m").value)
        grasp_margin = float(self.get_parameter("grasp_margin").value)
        ang_tol = float(self.get_parameter("ang_tolerance").value)
        z_tol = float(self.get_parameter("z_tolerance").value)

        jaw_half = jaw_width / 2.0
        tag_half = tag_size / 2.0
        grasp_x_tol = (jaw_half - tag_half) + grasp_margin

        if tag_alive and self.tag_seen and self.tag_t is not None and self.tag_ang is not None:
            z = float(self.tag_t.z)
            x_err = float(self.tag_t.x) - cam_off
            # "ready" без привязки к конкретному goal_z (просто “в захватном коридоре”)
            ready_tag = (abs(float(self.tag_ang)) <= ang_tol) and (abs(x_err) <= grasp_x_tol)

        # draw fixed zone: green if ready_tag OR qr_valid (на твой вкус)
        ready_zone = bool(ready_tag) or (qr_alive and self.qr_valid)
        self._draw_fixed_zone(img, w, h, ready_zone)

        # dynamic tag band + tag_u
        self._draw_dynamic_tag_band(img, w, h, tag_alive)

        # qr marker
        self._draw_qr_markers(img, w, h, qr_alive)

        # text blocks
        sys_lines = [
            f"FPS {self._fps:.1f}",
            f"img {w}x{h}",
            f"fx={self.fx:.1f} cx={self.cx:.1f}" if (self.fx is not None and self.cx is not None) else "CameraInfo: none",
        ]

        tag_lines = [
            f"TAG alive={tag_alive} seen={self.tag_seen}",
            f"TAG id={self.tag_id}",
            f"TAG u_px={self.tag_u_px:.1f}" if self.tag_u_px is not None else "TAG u_px: none",
            f"TAG t: x={self.tag_t.x:.3f} y={self.tag_t.y:.3f} z={self.tag_t.z:.3f}" if self.tag_t is not None else "TAG t: none",
            f"TAG ang_err={self.tag_ang:.4f}" if self.tag_ang is not None else "TAG ang_err: none",
        ]
        if x_err is not None and z is not None and self.tag_ang is not None:
            tag_lines.append(f"x_err={x_err:.3f}m  grasp_x_tol={grasp_x_tol:.3f}m")
            tag_lines.append(f"ready_tag={ready_tag} (ang_tol={ang_tol:.3f})")

        qr_lines = [
            f"QR alive={qr_alive} valid={self.qr_valid}",
            f"QR u={self.qr_u:.1f}px" if self.qr_u is not None else "QR u: none",
            f"QR w={self.qr_w:.1f}px" if self.qr_w is not None else "QR w: none",
        ]
        if self.qr_data is not None:
            s = self.qr_data
            s = (s[:40] + "...") if len(s) > 43 else s
            qr_lines.append(f"QR data='{s}'")

        self._draw_text_block(img, sys_lines, 10, 10)
        self._draw_text_block(img, tag_lines, 10, 90)
        self._draw_text_block(img, qr_lines, 10, 90 + 140)

        # publish
        out = self.bridge.cv2_to_imgmsg(img, encoding="bgr8")
        out.header = msg.header
        self.pub.publish(out)


def main():
    rclpy.init()
    node = DebugOverlayNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
