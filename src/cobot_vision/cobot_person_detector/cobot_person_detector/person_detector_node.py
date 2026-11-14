"""
핑키 정면 카메라 영상에서 YOLO(ultralytics)로 사람을 찾아 bbox 를 발행하는 노드.

- 핑키와 연결된 PC 에서 실행한다 (로봇 라즈베리파이에서 돌리기엔 느림).
- 입력: image_topic (sensor_msgs/Image 또는 use_compressed=True 면 CompressedImage)
- 출력: output_topic (vision_msgs/Detection2DArray). header 는 입력 영상 header 를 그대로 쓴다.
- 영상은 최신 것만 보관하고 max_rate 로 처리한다 (밀린 프레임은 버림).
"""
from cv_bridge import CvBridge
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, Image
from vision_msgs.msg import Detection2D, Detection2DArray, ObjectHypothesisWithPose

from .detector_utils import RateGate, select_person_boxes


class PersonDetectorNode(Node):
    """카메라 영상 -> YOLO -> 사람 bbox."""

    def __init__(self):
        """파라미터 선언, 모델 로드, 구독·발행 생성."""
        super().__init__('person_detector_node')
        self.declare_parameter('model_path', '')
        self.declare_parameter('image_topic', 'camera/image_raw')
        self.declare_parameter('use_compressed', False)
        self.declare_parameter('output_topic', 'person_detections')
        self.declare_parameter('person_class', 0)
        self.declare_parameter('min_confidence', 0.5)
        self.declare_parameter('min_box_height', 20.0)     # [px] 너무 작은(먼) 사람은 무시
        self.declare_parameter('imgsz', 640)
        self.declare_parameter('device', 'cpu')            # 'cpu', '0'(GPU) ...
        self.declare_parameter('max_rate', 5.0)            # [Hz]

        gp = self.get_parameter
        model_path = gp('model_path').value
        if not model_path:
            raise RuntimeError('model_path 파라미터가 비어 있습니다 (YOLO .pt 파일 경로)')
        self.person_class = gp('person_class').value
        self.min_conf = gp('min_confidence').value
        self.min_h = gp('min_box_height').value
        self.imgsz = gp('imgsz').value
        self.device = gp('device').value
        self.compressed = gp('use_compressed').value

        from ultralytics import YOLO   # 무거워서 노드 생성 시점에 불러온다
        self.model = YOLO(model_path)
        self.bridge = CvBridge()
        self.gate = RateGate(1.0 / gp('max_rate').value)
        self.latest = None

        self.pub = self.create_publisher(Detection2DArray, gp('output_topic').value, 10)
        msg_type = CompressedImage if self.compressed else Image
        self.create_subscription(msg_type, gp('image_topic').value, self._image_cb,
                                 qos_profile_sensor_data)
        self.create_timer(0.02, self._tick)
        self.get_logger().info(
            f'person_detector 시작: model={model_path}, image={gp("image_topic").value}'
            f'{" (compressed)" if self.compressed else ""}, device={self.device}')

    def _image_cb(self, msg):
        self.latest = msg

    def _tick(self):
        msg = self.latest
        if msg is None or not self.gate.ready(self.get_clock().now().nanoseconds * 1e-9):
            return
        self.latest = None
        if self.compressed:
            frame = self.bridge.compressed_imgmsg_to_cv2(msg, 'bgr8')
        else:
            frame = self.bridge.imgmsg_to_cv2(msg, 'bgr8')
        result = self.model.predict(frame, imgsz=self.imgsz, device=self.device,
                                    classes=[self.person_class], verbose=False)[0]
        boxes = result.boxes
        persons = select_person_boxes(boxes.xywh.tolist(), boxes.conf.tolist(),
                                      boxes.cls.tolist(), self.person_class,
                                      self.min_conf, self.min_h)
        out = Detection2DArray()
        out.header = msg.header
        for cx, cy, w, h, conf in persons:
            det = Detection2D()
            det.header = msg.header
            det.bbox.center.position.x = cx
            det.bbox.center.position.y = cy
            det.bbox.size_x = w
            det.bbox.size_y = h
            hyp = ObjectHypothesisWithPose()
            hyp.hypothesis.class_id = 'person'
            hyp.hypothesis.score = conf
            det.results.append(hyp)
            out.detections.append(det)
        self.pub.publish(out)


def main(args=None):
    """노드 진입점."""
    rclpy.init(args=args)
    node = PersonDetectorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # 종료 중 Ctrl+C 가 한 번 더 와도 traceback 없이 끝낸다.
        try:
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
