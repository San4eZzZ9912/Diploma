from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    pkg = get_package_share_directory('apriltag_detector')

    return LaunchDescription([
        # 1. AprilTag detector
        Node(
            package='apriltag_detector',
            executable='apriltag_detector_node',
            name='apriltag_detector',
            output='screen',
        ),

        # 2. QR detector
        Node(
            package='apriltag_detector',
            executable='qr_detector_node',
            name='qr_detector',
            output='screen',
        ),

        # 4. Arm controller (если он тоже в этом пакете)
        Node(
            package='apriltag_detector',
            executable='arm_controller_node',
            name='arm_controller',
            output='screen',
        ),

        # 3. Debug overlay
        Node(
            package='apriltag_detector',
            executable='debug_overlay_node',
            name='debug_overlay',
            output='screen',
        ),

        # Добавь сюда другие ноды, если они есть
        Node(
            package='apriltag_detector',
            executable='mission_nav_node',
            name='mission_nav',
            output='screen',
        ),

        # 5. Task FSM (основная логика робота)
        #Node(
        #    package='apriltag_detector',
        #    executable='task_fsm_node',
        #    name='task_fsm_node',
        #    output='screen',
        #    parameters=[config],
        #),
    ])