import pytest
import math

from aic_data_collection.completion_monitor import CompletionResult, check_tf_completion


class TestCheckTfCompletion:
    def test_success_within_threshold(self):
        plug_pos = (0.1, 0.2, 0.3)
        port_pos = (0.1, 0.2, 0.303)  # 3mm away
        plug_quat = (0.0, 0.0, 0.0, 1.0)
        port_quat = (0.0, 0.0, 0.0, 1.0)
        result = check_tf_completion(plug_pos, port_pos, plug_quat, port_quat,
                                     distance_threshold=0.005, orientation_threshold=0.1)
        assert result is True

    def test_fail_distance_too_large(self):
        plug_pos = (0.1, 0.2, 0.3)
        port_pos = (0.1, 0.2, 0.31)  # 10mm away
        plug_quat = (0.0, 0.0, 0.0, 1.0)
        port_quat = (0.0, 0.0, 0.0, 1.0)
        result = check_tf_completion(plug_pos, port_pos, plug_quat, port_quat,
                                     distance_threshold=0.005, orientation_threshold=0.1)
        assert result is False

    def test_fail_orientation_too_large(self):
        plug_pos = (0.1, 0.2, 0.3)
        port_pos = (0.1, 0.2, 0.301)
        plug_quat = (0.0, 0.0, 0.0, 1.0)
        # ~0.2 rad rotation around z
        port_quat = (0.0, 0.0, math.sin(0.1), math.cos(0.1))
        result = check_tf_completion(plug_pos, port_pos, plug_quat, port_quat,
                                     distance_threshold=0.005, orientation_threshold=0.1)
        assert result is False


class TestCompletionResult:
    def test_success(self):
        r = CompletionResult.SUCCESS
        assert r.is_success()

    def test_partial_is_success(self):
        r = CompletionResult.PARTIAL
        assert r.is_success()

    def test_timeout_is_not_success(self):
        r = CompletionResult.TIMEOUT
        assert not r.is_success()

    def test_action_failed_is_not_success(self):
        r = CompletionResult.ACTION_FAILED
        assert not r.is_success()
