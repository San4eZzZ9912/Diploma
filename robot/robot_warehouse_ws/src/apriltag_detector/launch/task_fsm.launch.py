# launch/task_fsm_launch.py
from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    package_dir = get_package_share_directory('apriltag_detector')  # замени на имя твоего пакета
    config_path = os.path.join(package_dir, 'config', 'task_fsm_params.yaml')

    return LaunchDescription([
        Node(
            package='apriltag_detector',
            executable='task_fsm_node',
            name='task_fsm_node',
            output='screen',
            parameters=[config_path],           # ← вот здесь магия
        )
    ])