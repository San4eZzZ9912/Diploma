#!/usr/bin/env python3
import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile
import math

from sensor_msgs.msg import Image, CameraInfo
from std_msgs.msg import Bool, Float32, String
from geometry_msgs.msg import Vector3
from cv_bridge import CvBridge

class DebugOverlayNode(Node):
    def __init__(self):
        super().__init__('debug_overlay_node')

        # --- Parameters ---
        self.declare_parameter('image_topic', '/camera/color/image_raw')
        self.declare_parameter('camera_info_topic', '/camera/color/camera_info')
        self.declare_parameter('tag_size', 0.04)
        self.declare_parameter('jaw_width', 0.05)
        self.declare_parameter('camera_offset_right_m', 0.021)
        self.declare_parameter('qr_target_w_px', 185.0)
        self.declare_parameter('goal_z', 0.35)
        self.declare_parameter('tag_goal_z_pre_qr', 0.40)

        self.image_topic = self.get_parameter('image_topic').value
        self.caminfo_topic = self.get_parameter('camera_info_topic').value
        self.tag_size = float(self.get_parameter('tag_size').value)
        self.jaw_width = float(self.get_parameter('jaw_width').value)
        self.cam_off = float(self.get_parameter('camera_offset_right_m').value)
        self.qr_target_w_px = float(self.get_parameter('qr_target_w_px').value)
        self.goal_z = float(self.get_parameter('goal_z').value)
        self.tag_goal_z_pre_qr = float(self.get_parameter('tag_goal_z_pre_qr').value)

        # --- State ---
        self.bridge = CvBridge()
        self.cam_K = None  # 3x3 intrinsics

        # AprilTag data
        self.tag_seen = False
        self.tag_t = None  # Vector3 (x, y, z)
        self.tag_u_px = None  # float
        self.tag_ang = None  # float

        # QR data
        self.qr_valid = False
        self.qr_u = None  # float
        self.qr_w = None  # float
        self.qr_payload = None  # string

        # --- Publishers ---
        self.pub_overlay = self.create_publisher(Image, '/debug/overlay_image', 10)

        # --- Subscribers ---
        qos = QoSProfile(depth=10)

        # Image and caminfo
        self.create_subscription(Image, self.image_topic, self.on_image, qos)
        self.create_subscription(CameraInfo, self.caminfo_topic, self.on_caminfo, qos)

        # AprilTag topics
        self.create_subscription(Bool, '/tag/seen', self.on_tag_seen, qos)
        self.create_subscription(Vector3, '/tag/pose_t', self.on_tag_pose, qos)
        self.create_subscription(Float32, '/tag/u_px', self.on_tag_u, qos)
        self.create_subscription(Float32, '/tag/ang_err_normal', self.on_tag_ang, qos)

        # QR topics
        self.create_subscription(Bool, '/qr/valid', self.on_qr_valid, qos)
        self.create_subscription(Float32, '/qr/u', self.on_qr_u, qos)
        self.create_subscription(Float32, '/qr/w', self.on_qr_w, qos)
        self.create_subscription(String, '/qr/data', self.on_qr_data, qos)

        self.get_logger().info('Debug overlay node started. Publishing to /debug/overlay_image')

    # --- Callbacks for caminfo and image ---
    def on_caminfo(self, msg: CameraInfo):
        self.cam_K = np.array(msg.k, dtype=np.float64).reshape(3, 3)

    def on_image(self, msg: Image):
        if self.cam_K is None:
            return

        try:
            img = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as e:
            self.get_logger().warning(f'cv_bridge error: {e}')
            return

        # Overlay detections and zones
        overlay_img = self.draw_overlays(img)

        # Publish overlay
        overlay_msg = self.bridge.cv2_to_imgmsg(overlay_img, encoding='bgr8')
        overlay_msg.header = msg.header
        self.pub_overlay.publish(overlay_msg)

    # --- Draw function ---
    def draw_overlays(self, img):
        h, w, _ = img.shape
        fx = self.cam_K[0, 0]
        cx = self.cam_K[0, 2]

        # --- Draw AprilTag if seen ---
        if self.tag_seen and self.tag_t is not None and self.tag_u_px is not None:
            z = float(self.tag_t.z)
            x = float(self.tag_t.x)
            ang = self.tag_ang if self.tag_ang is not None else 0.0

            # Draw tag center
            u = int(self.tag_u_px)
            cv2.circle(img, (u, int(h / 2)), 5, (0, 255, 0), 2)  # Green dot at tag center

            # Estimate tag width in pixels (approx)
            tag_w_px = (self.tag_size / z) * fx

            # Draw tag box (approx square)
            half_w = int(tag_w_px / 2)
            cv2.rectangle(img, (u - half_w, int(h / 2) - half_w), (u + half_w, int(h / 2) + half_w), (0, 255, 0), 2)

            # Text: distance, angle
            cv2.putText(img, f'Tag Z: {z:.2f}m X: {x:.2f}m Ang: {math.degrees(ang):.1f}deg', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # --- Draw QR if valid ---
        if self.qr_valid and self.qr_u is not None and self.qr_w is not None:
            u = int(self.qr_u)
            qr_w_px = self.qr_w

            # Draw QR box (approx square)
            half_w = int(qr_w_px / 2)
            cv2.rectangle(img, (u - half_w, int(h / 2) - half_w), (u + half_w, int(h / 2) + half_w), (255, 0, 0), 2)

            # Draw QR center
            cv2.circle(img, (u, int(h / 2)), 5, (255, 0, 0), 2)  # Blue dot

            # Text: payload if available
            payload = self.qr_payload if self.qr_payload else 'N/A'
            cv2.putText(img, f'QR W: {qr_w_px:.1f}px Payload: {payload}', (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)

        # --- Draw target zones ---
        # Grip zone (purple) - based on cam_off and jaw_width
        if self.tag_t is not None:
            z = float(self.tag_t.z) if self.tag_t else self.goal_z  # Use current z or goal

            # Target u for center (with offset)
            u_target = int(cx + fx * (self.cam_off / max(z, 1e-3)))

            # Jaw width in pixels at current z
            jaw_w_px = (self.jaw_width / z) * fx
            half_jaw_px = int(jaw_w_px / 2)

            # Draw purple grip zone (vertical rectangle in center y)
            cv2.rectangle(img, (u_target - half_jaw_px, int(h * 0.4)), (u_target + half_jaw_px, int(h * 0.6)), (128, 0, 128), 2)

            cv2.putText(img, 'Grip Zone', (u_target - half_jaw_px, int(h * 0.4) - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (128, 0, 128), 2)

        # Target QR width line (for reference)
        qr_target_half = int(self.qr_target_w_px / 2)
        cv2.line(img, (int(cx - qr_target_half), int(h / 2 - 10)), (int(cx - qr_target_half), int(h / 2 + 10)), (0, 0, 255), 2)
        cv2.line(img, (int(cx + qr_target_half), int(h / 2 - 10)), (int(cx + qr_target_half), int(h / 2 + 10)), (0, 0, 255), 2)
        cv2.putText(img, f'Target QR W: {self.qr_target_w_px:.1f}px', (int(cx - qr_target_half), int(h / 2 - 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        # Pre-QR zone (optional, horizontal line for distance)
        pre_z = self.tag_goal_z_pre_qr
        cv2.putText(img, f'Pre-QR Z: {pre_z:.2f}m', (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

        return img

    # --- Data callbacks ---
    def on_tag_seen(self, msg: Bool):
        self.tag_seen = msg.data

    def on_tag_pose(self, msg: Vector3):
        self.tag_t = msg

    def on_tag_u(self, msg: Float32):
        self.tag_u_px = msg.data

    def on_tag_ang(self, msg: Float32):
        self.tag_ang = msg.data

    def on_qr_valid(self, msg: Bool):
        self.qr_valid = msg.data

    def on_qr_u(self, msg: Float32):
        self.qr_u = msg.data

    def on_qr_w(self, msg: Float32):
        self.qr_w = msg.data

    def on_qr_data(self, msg: String):
        self.qr_payload = msg.data

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

if __name__ == '__main__':
    main()