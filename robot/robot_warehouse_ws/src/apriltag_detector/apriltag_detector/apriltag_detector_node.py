#!/usr/bin/env python3
import math
import numpy as np
import cv2

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile

from sensor_msgs.msg import Image, CameraInfo
from std_msgs.msg import Bool, Float32, Int32
from geometry_msgs.msg import Vector3
from cv_bridge import CvBridge

from pupil_apriltags import Detector


class AprilTagDetectorNode(Node):
    """
    Publishes a single "best" tag:
      /tag/seen (Bool)
      /tag/pose_t (Vector3)   camera frame translation to tag
      /tag/u_px (Float32)     tag center u in pixels
      /tag/ang_err_normal (Float32) yaw-ish error from tag normal

    Runtime target id control:
      /tag/target_id (Int32)
        -1 => no filtering (choose best by rule)
        >=0 => publish only that tag id (if visible)
    """

    def __init__(self):
        super().__init__("apriltag_detector_node")

        # --- params ---
        self.declare_parameter("image_topic", "/camera/color/image_raw")
        self.declare_parameter("camera_info_topic", "/camera/color/camera_info")
        self.declare_parameter("tag_size", 0.04)
        self.declare_parameter("family", "tag36h11")

        # optional static allow list (works together with target_id)
        self.declare_parameter("allowed_ids", [])  # [] => accept any

        # if multiple tags: how to choose best (when not target-filtering)
        # "min_z" = closest in depth (recommended)
        # "max_area" = largest quad area (fallback if you want)
        self.declare_parameter("best_rule", "min_z")

        # runtime target topic
        self.declare_parameter("target_id_topic", "/tag/target_id")

        self.image_topic = str(self.get_parameter("image_topic").value)
        self.caminfo_topic = str(self.get_parameter("camera_info_topic").value)
        self.tag_size = float(self.get_parameter("tag_size").value)
        self.family = str(self.get_parameter("family").value)
        self.allowed_ids = list(self.get_parameter("allowed_ids").value)
        self.best_rule = str(self.get_parameter("best_rule").value).strip().lower()
        self.target_id_topic = str(self.get_parameter("target_id_topic").value)

        # --- runtime target id ---
        self.target_id = -1  # -1 => no filter

        # --- state ---
        self.bridge = CvBridge()
        self.cam_K = None  # 3x3

        # --- detector ---
        self.detector = Detector(
            families=self.family,
            nthreads=2,
            quad_decimate=2.0,
            quad_sigma=0.0,
            refine_edges=True,
            decode_sharpening=0.25,
        )

        # --- pubs ---
        self.pub_seen = self.create_publisher(Bool, "/tag/seen", 10)
        self.pub_pose_t = self.create_publisher(Vector3, "/tag/pose_t", 10)
        self.pub_u = self.create_publisher(Float32, "/tag/u_px", 10)
        self.pub_ang = self.create_publisher(Float32, "/tag/ang_err_normal", 10)
        self.pub_id = self.create_publisher(Int32, "/tag/id", 10)  # чтобы FSM мог читать id

        qos = QoSProfile(depth=10)

        # --- subs ---
        self.create_subscription(CameraInfo, self.caminfo_topic, self.on_caminfo, qos)
        self.create_subscription(Image, self.image_topic, self.on_image, qos)
        self.create_subscription(Int32, self.target_id_topic, self.on_target_id, 10)

        self.get_logger().info(
            f"AprilTag detector started. image={self.image_topic} caminfo={self.caminfo_topic} "
            f"tag_size={self.tag_size} family={self.family} allowed_ids={self.allowed_ids} "
            f"best_rule={self.best_rule} target_id_topic={self.target_id_topic}"
        )

    def on_target_id(self, msg: Int32):
        try:
            self.target_id = int(msg.data)
        except Exception:
            self.target_id = -1
        self.get_logger().info(f"Target tag id set to: {self.target_id}")

    def on_caminfo(self, msg: CameraInfo):
        self.cam_K = np.array(msg.k, dtype=np.float64).reshape(3, 3)

    def _choose_best(self, dets):
        if not dets:
            return None

        if self.best_rule == "max_area":
            # area of quad from corners (pixel^2)
            def area(d):
                pts = np.array(d.corners, dtype=np.float64).reshape(4, 2)
                return float(cv2.contourArea(pts))
            return max(dets, key=area)

        # default: closest in z
        def z_of(d):
            t = np.array(d.pose_t, dtype=np.float64).reshape(3)
            return float(t[2])
        return min(dets, key=z_of)

    def on_image(self, msg: Image):
        if self.cam_K is None:
            return

        try:
            img = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as e:
            self.get_logger().warning(f"cv_bridge error: {e}")
            return

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        fx = float(self.cam_K[0, 0])
        fy = float(self.cam_K[1, 1])
        cx = float(self.cam_K[0, 2])
        cy = float(self.cam_K[1, 2])

        dets = self.detector.detect(
            gray,
            estimate_tag_pose=True,
            camera_params=[fx, fy, cx, cy],
            tag_size=self.tag_size,
        )

        # 1) static allow list
        if self.allowed_ids:
            dets = [d for d in dets if int(d.tag_id) in set(int(x) for x in self.allowed_ids)]

        # 2) runtime target filter
        if self.target_id is not None and int(self.target_id) >= 0:
            dets = [d for d in dets if int(d.tag_id) == int(self.target_id)]

        best = self._choose_best(dets)

        seen_msg = Bool()
        seen_msg.data = (best is not None)
        self.pub_seen.publish(seen_msg)

        if best is None:
            return

        # publish id
        mid = Int32()
        mid.data = int(best.tag_id)
        self.pub_id.publish(mid)

        # pose
        t = np.array(best.pose_t, dtype=np.float64).reshape(3)
        R = np.array(best.pose_R, dtype=np.float64).reshape(3, 3)
        u_px = float(best.center[0])

        # yaw error by tag normal: atan2(nx, nz) where normal is R[:,2]
        n = R[:, 2]
        ang_err_normal = math.atan2(float(n[0]), float(n[2]))

        vt = Vector3()
        vt.x = float(t[0])
        vt.y = float(t[1])
        vt.z = float(t[2])
        self.pub_pose_t.publish(vt)

        mu = Float32()
        mu.data = u_px
        self.pub_u.publish(mu)

        ma = Float32()
        ma.data = float(ang_err_normal)
        self.pub_ang.publish(ma)


def main():
    rclpy.init()
    node = AprilTagDetectorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
