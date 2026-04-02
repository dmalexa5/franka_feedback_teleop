import rclpy
from rclpy.node import Node
from std_msgs.msg import String

class LerobotExportNode(Node):
    def __init__(self):
        # Initialize the node with the name 'lerobot_export'
        super().__init__('lerobot_export')
        
        # Create a publisher that sends String messages on the 'lerobot_status' topic
        self.publisher_ = self.create_publisher(String, 'lerobot_status', 10)
        
        # Create a timer that calls the callback every 1.0 seconds
        timer_period = 1.0  # seconds
        self.timer = self.create_timer(timer_period, self.timer_callback)
        
        self.get_logger().info('Lerobot Export Node has been started.')

    def timer_callback(self):
        msg = String()
        msg.data = 'Hello from Franka-LeRobot Teleop!'
        self.publisher_.publish(msg)
        self.get_logger().info('Publishing: "%s"' % msg.data)

def main(args=None):
    rclpy.init(args=args)
    
    node = LerobotExportNode()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()