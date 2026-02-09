from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    pkg_dir = get_package_share_directory('apriltag_detector')
    config = os.path.join(pkg_dir, 'config', 'task_fsm_params.yaml')

    return LaunchDescription([
        Node(
            package='apriltag_detector',
            executable='task_fsm_node',
            name='task_fsm_node',
            output='screen',
            parameters=[config],
        ),
    ])