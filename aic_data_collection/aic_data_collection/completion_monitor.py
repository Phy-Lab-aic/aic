"""Task completion monitoring via insertion_event + TF check."""

import math
from enum import Enum


class CompletionResult(Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    TIMEOUT = "timeout"
    ACTION_FAILED = "action_failed"

    def is_success(self) -> bool:
        return self in (CompletionResult.SUCCESS, CompletionResult.PARTIAL)


def check_tf_completion(
    plug_pos: tuple[float, float, float],
    port_pos: tuple[float, float, float],
    plug_quat: tuple[float, float, float, float],
    port_quat: tuple[float, float, float, float],
    distance_threshold: float = 0.005,
    orientation_threshold: float = 0.1,
) -> bool:
    """Check if plug is within distance and orientation threshold of port.

    Args:
        plug_pos/port_pos: (x, y, z) positions
        plug_quat/port_quat: (x, y, z, w) quaternions
        distance_threshold: meters
        orientation_threshold: radians
    """
    dx = plug_pos[0] - port_pos[0]
    dy = plug_pos[1] - port_pos[1]
    dz = plug_pos[2] - port_pos[2]
    distance = math.sqrt(dx * dx + dy * dy + dz * dz)

    if distance > distance_threshold:
        return False

    # Quaternion angle difference: angle = 2 * acos(|dot|)
    dot = (plug_quat[0] * port_quat[0] + plug_quat[1] * port_quat[1] +
           plug_quat[2] * port_quat[2] + plug_quat[3] * port_quat[3])
    dot = min(1.0, max(-1.0, abs(dot)))
    angle_diff = 2.0 * math.acos(dot)

    return angle_diff <= orientation_threshold
