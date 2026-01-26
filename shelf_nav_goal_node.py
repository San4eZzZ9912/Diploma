#!/usr/bin/env python3
import math

import rclpy
from rclpy.node import Node

from geometry_msgs.msg import PoseStamped
from std_msgs.msg import String, Bool


def yaw_to_quat(yaw: float):
    half = yaw * 0.5
    return 0.0, 0.0, math.sin(half), math.cos(half)


class ShelfNavGoalNode(Node):
    def __init__(self):
        super().__init__("shelf_nav_goal_node")

        self.declare_parameter("goal_topic", "/nav/goal_pose")
        self.declare_parameter("target_topic", "/nav/shelf_target")
        self.declare_parameter("goal_reached_topic", "/nav/goal_reached")
        self.declare_parameter("frame_id", "map")

        self.declare_parameter("shelf_A_x", 0.0)
        self.declare_parameter("shelf_A_y", 0.0)
        self.declare_parameter("shelf_A_yaw", 0.0)

        self.declare_parameter("shelf_B_x", 1.0)
        self.declare_parameter("shelf_B_y", 0.0)
        self.declare_parameter("shelf_B_yaw", 0.0)

        self.goal_topic = str(self.get_parameter("goal_topic").value)
        self.target_topic = str(self.get_parameter("target_topic").value)
        self.goal_reached_topic = str(self.get_parameter("goal_reached_topic").value)
        self.frame_id = str(self.get_parameter("frame_id").value)

        self.goal_pub = self.create_publisher(PoseStamped, self.goal_topic, 10)
        self.goal_reached_pub = self.create_publisher(Bool, self.goal_reached_topic, 10)
        self.create_subscription(String, self.target_topic, self.on_target, 10)

        self.get_logger().info("ShelfNavGoalNode ready: waits for shelf targets and publishes pose goals.")

    def _shelf_pose(self, shelf: str):
        if shelf == "A":
            x = float(self.get_parameter("shelf_A_x").value)
            y = float(self.get_parameter("shelf_A_y").value)
            yaw = float(self.get_parameter("shelf_A_yaw").value)
        elif shelf == "B":
            x = float(self.get_parameter("shelf_B_x").value)
            y = float(self.get_parameter("shelf_B_y").value)
            yaw = float(self.get_parameter("shelf_B_yaw").value)
        else:
            raise ValueError(f"Unknown shelf '{shelf}'")
        return x, y, yaw

    def on_target(self, msg: String):
        shelf = msg.data.strip().upper()
        try:
            x, y, yaw = self._shelf_pose(shelf)
        except ValueError as exc:
            self.get_logger().warn(str(exc))
            return

        pose = PoseStamped()
        pose.header.frame_id = self.frame_id
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.pose.position.x = x
        pose.pose.position.y = y
        pose.pose.position.z = 0.0
        qx, qy, qz, qw = yaw_to_quat(yaw)
        pose.pose.orientation.x = qx
        pose.pose.orientation.y = qy
        pose.pose.orientation.z = qz
        pose.pose.orientation.w = qw

        self.goal_pub.publish(pose)
        self.get_logger().info(f"Published nav goal for shelf {shelf}: x={x:.2f} y={y:.2f} yaw={yaw:.2f}")

        reached = Bool()
        reached.data = False
        self.goal_reached_pub.publish(reached)


def main():
    rclpy.init()
    node = ShelfNavGoalNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
