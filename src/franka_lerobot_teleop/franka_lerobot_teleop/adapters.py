"""Message normalization helpers used by the recorder."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Dict, Optional

from PIL import Image as PILImage
import numpy as np


@dataclass(frozen=True)
class ImagePayload:
    """Normalized image payload that is ready to be written as JPEG."""

    image: PILImage.Image
    width: int
    height: int
    encoding: str
    frame_id: str


def stamp_to_ns(stamp: Any) -> Optional[int]:
    """Convert a ROS time stamp to nanoseconds when available."""
    if stamp is None:
        return None
    if hasattr(stamp, 'sec') and hasattr(stamp, 'nanosec'):
        return int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)
    return None


def source_timestamp_ns(message: Any) -> Optional[int]:
    """Extract a source timestamp from a message header when present."""
    header = getattr(message, 'header', None)
    if header is None:
        return None
    return stamp_to_ns(getattr(header, 'stamp', None))


def adapt_joint_state(message: Any) -> Dict[str, Any]:
    """Normalize a JointState message."""
    return {
        'joint_names': list(message.name),
        'joint_position': [float(value) for value in message.position],
        'joint_velocity': [float(value) for value in message.velocity],
        'joint_effort': [float(value) for value in message.effort],
        'frame_id': str(message.header.frame_id),
    }


def adapt_pose_stamped(message: Any) -> Dict[str, Any]:
    """Normalize a PoseStamped message."""
    return {
        'frame_id': str(message.header.frame_id),
        'position': [
            float(message.pose.position.x),
            float(message.pose.position.y),
            float(message.pose.position.z),
        ],
        'orientation_xyzw': [
            float(message.pose.orientation.x),
            float(message.pose.orientation.y),
            float(message.pose.orientation.z),
            float(message.pose.orientation.w),
        ],
    }


def adapt_wrench_stamped(message: Any) -> Dict[str, Any]:
    """Normalize a WrenchStamped message."""
    return {
        'frame_id': str(message.header.frame_id),
        'wrench_base': [
            float(message.wrench.force.x),
            float(message.wrench.force.y),
            float(message.wrench.force.z),
            float(message.wrench.torque.x),
            float(message.wrench.torque.y),
            float(message.wrench.torque.z),
        ],
    }


def adapt_twist_stamped(message: Any) -> Dict[str, Any]:
    """Normalize a TwistStamped message."""
    return {
        'frame_id': str(message.header.frame_id),
        'twist': [
            float(message.twist.linear.x),
            float(message.twist.linear.y),
            float(message.twist.linear.z),
            float(message.twist.angular.x),
            float(message.twist.angular.y),
            float(message.twist.angular.z),
        ],
    }


def adapt_camera_info(message: Any) -> Dict[str, Any]:
    """Normalize a CameraInfo message."""
    return {
        'frame_id': str(message.header.frame_id),
        'width': int(message.width),
        'height': int(message.height),
        'distortion_model': str(message.distortion_model),
        'd': [float(value) for value in message.d],
        'k': [float(value) for value in message.k],
        'r': [float(value) for value in message.r],
        'p': [float(value) for value in message.p],
        'binning_x': int(message.binning_x),
        'binning_y': int(message.binning_y),
    }


def _reshape_image_buffer(message: Any, channels: int) -> np.ndarray:
    """Reshape image bytes into an HWC array and account for row padding."""
    row_bytes = int(message.width) * channels
    data = np.frombuffer(message.data, dtype=np.uint8)
    padded = data.reshape(int(message.height), int(message.step))
    return padded[:, :row_bytes].reshape(int(message.height), int(message.width), channels)


def adapt_image(message: Any) -> ImagePayload:
    """Normalize a sensor_msgs Image message into a JPEG-ready image payload."""
    encoding = str(message.encoding).lower()
    frame_id = str(message.header.frame_id)

    if encoding == 'rgb8':
        image = PILImage.fromarray(_reshape_image_buffer(message, 3), mode='RGB')
    elif encoding == 'bgr8':
        image = PILImage.fromarray(
            _reshape_image_buffer(message, 3)[:, :, ::-1],
            mode='RGB',
        )
    elif encoding == 'rgba8':
        image = PILImage.fromarray(
            _reshape_image_buffer(message, 4),
            mode='RGBA',
        ).convert('RGB')
    elif encoding == 'bgra8':
        image = PILImage.fromarray(_reshape_image_buffer(message, 4)[:, :, [2, 1, 0, 3]], mode='RGBA')
        image = image.convert('RGB')
    elif encoding == 'mono8':
        array = np.frombuffer(message.data, dtype=np.uint8).reshape(int(message.height), int(message.step))
        image = PILImage.fromarray(array[:, : int(message.width)], mode='L').convert('RGB')
    else:
        raise ValueError(f'Unsupported image encoding: {message.encoding}')

    return ImagePayload(
        image=image,
        width=int(message.width),
        height=int(message.height),
        encoding=str(message.encoding),
        frame_id=frame_id,
    )


def adapt_json_string(message: Any) -> Dict[str, Any]:
    """Normalize a JSON string message for gripper command mirroring."""
    payload = json.loads(message.data)
    if not isinstance(payload, dict):
        raise ValueError('Expected a JSON object in the gripper command mirror topic.')

    return {
        'command_type': str(payload.get('command_type', 'none')),
        'width_cmd': _optional_float(payload.get('width_cmd')),
        'speed_cmd': _optional_float(payload.get('speed_cmd')),
        'force_cmd': _optional_float(payload.get('force_cmd')),
        'epsilon_inner': _optional_float(payload.get('epsilon_inner')),
        'epsilon_outer': _optional_float(payload.get('epsilon_outer')),
        'source_action': payload.get('source_action'),
        'sent_at_ns': _optional_int(payload.get('sent_at_ns')),
    }


def _optional_float(value: Any) -> Optional[float]:
    """Convert a value into an optional float."""
    if value is None:
        return None
    return float(value)


def _optional_int(value: Any) -> Optional[int]:
    """Convert a value into an optional integer."""
    if value is None:
        return None
    return int(value)


ADAPTERS: Dict[str, Callable[[Any], Any]] = {
    'joint_state': adapt_joint_state,
    'pose_stamped': adapt_pose_stamped,
    'wrench_stamped': adapt_wrench_stamped,
    'twist_stamped': adapt_twist_stamped,
    'camera_info': adapt_camera_info,
    'image': adapt_image,
    'json_string': adapt_json_string,
}


def get_adapter(name: str) -> Callable[[Any], Any]:
    """Return the named adapter callable."""
    return ADAPTERS[name]
