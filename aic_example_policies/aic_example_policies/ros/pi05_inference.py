#
#  Copyright (C) 2026
#  Licensed under the Apache License, Version 2.0
#

"""ROS-free π0.5 inference core for the AIC cable-insertion task.

Extracted out of MyPi05Policy so the inference pipeline (image preprocessing,
joint reordering, batch assembly, action chunk consumption) can be unit-tested
on Colab / vanilla CPython without rclpy or aic_interfaces.

Layered design:
    [ROS adapter — MyPi05Policy.py]   ← imports rclpy + aic_msgs
        ↓ delegates
    [Pi05InferenceCore — this file]   ← imports lerobot + torch only
        ↓ delegates
    [lerobot PI05Policy]              ← upstream

Schema must match rosbag-to-lerobot/src/config.json (training contract):
  - State 7D: 6 UR5e arm joints + gripper/left_finger_joint
  - Action 7D: same order, absolute joint targets
  - Image keys: observation.images.cam_{center,left,right}
  - Prompt key: task (string per episode)

See project_inference_deployment.md for the full data contract.
"""

from __future__ import annotations

import threading
from typing import List, Mapping, Sequence

import numpy as np
import torch

# UR5e arm joint order — authoritative from rosbag-to-lerobot/src/config.json.
TRAINING_JOINT_ORDER: List[str] = [
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_joint",
    "wrist_1_joint",
    "wrist_2_joint",
    "wrist_3_joint",
    "gripper/left_finger_joint",
]
ARM_JOINT_NAMES: List[str] = TRAINING_JOINT_ORDER[:6]
GRIPPER_JOINT_NAME: str = TRAINING_JOINT_ORDER[6]

# lerobot batch dict keys — authoritative from ur5e_dataconfig RepackTransform.
IMG_KEY_CENTER = "observation.images.cam_center"
IMG_KEY_LEFT = "observation.images.cam_left"
IMG_KEY_RIGHT = "observation.images.cam_right"
STATE_KEY = "observation.state"
TASK_KEY = "task"

# AIC trial tick rate.
POLICY_HZ = 20
CONTROL_DT_S = 1.0 / POLICY_HZ

# Default chunk_size for AIC (B1 decision: 10 steps × 50ms = 0.5s lookahead).
DEFAULT_CHUNK_SIZE = 10
DEFAULT_MAX_STATE_DIM = 32
DEFAULT_MAX_ACTION_DIM = 32
DEFAULT_IMAGE_RESOLUTION = (224, 224)


# --------------------------------------------------------------------------- #
# Pure functions — testable without any model
# --------------------------------------------------------------------------- #


def numpy_image_to_chw(img_hwc: np.ndarray) -> torch.Tensor:
    """Convert a uint8 (H, W, 3) RGB image to torch (3, H, W) float32 in [0, 1].

    lerobot PI05Policy._preprocess_images applies the [0,1] → [-1,1] shift and
    resize_with_pad to (224, 224) internally, so callers should not duplicate
    those steps. RGB ordering is verified by basler_camera_macro.xacro:99
    (`<format>R8G8B8</format>`) plus RunACT.py absence of cvtColor.
    """
    if img_hwc.ndim != 3 or img_hwc.shape[2] != 3:
        raise ValueError(
            f"expected (H, W, 3) image, got shape {img_hwc.shape}"
        )
    if img_hwc.dtype != np.uint8:
        raise ValueError(f"expected uint8 image, got {img_hwc.dtype}")
    return torch.from_numpy(img_hwc.copy()).permute(2, 0, 1).float().div_(255.0)


def joint_dict_to_state(
    name_to_position: Mapping[str, float],
    joint_order: Sequence[str] = TRAINING_JOINT_ORDER,
) -> np.ndarray:
    """Reorder a {joint_name: position} mapping into the training state vector.

    sensor_msgs/JointState packs name[i] and position[i] in parallel but does
    not guarantee any particular ordering, so a name-aware lookup is
    mandatory. Missing joints raise KeyError so misconfigured adapters fail
    loudly instead of silently feeding wrong state to the model.
    """
    try:
        return np.asarray(
            [name_to_position[n] for n in joint_order], dtype=np.float32
        )
    except KeyError as missing:
        observed = sorted(name_to_position.keys())
        raise KeyError(
            f"joint {missing} missing from observation; saw {observed}"
        ) from None


def build_prompt(plug_type: str, port_name: str, target_module_name: str) -> str:
    """Compose the canonical AIC task prompt string."""
    return (
        f"Insert the {plug_type} plug into port {port_name} on {target_module_name}."
    )


DEFAULT_TOKENIZER_NAME = "google/paligemma-3b-pt-224"
DEFAULT_LANG_LEN = 200  # PI05Config.tokenizer_max_length default


def build_pi05_batch(
    img_center: np.ndarray,
    img_left: np.ndarray,
    img_right: np.ndarray,
    state: np.ndarray,
    prompt: str,
    device: torch.device | str = "cpu",
    *,
    tokenizer=None,
    max_lang_len: int = DEFAULT_LANG_LEN,
) -> dict:
    """Assemble a lerobot PI05 batch from raw numpy arrays.

    Inputs are expected as uint8 (H, W, 3) for images and float32 (7,) for state.
    Returns a dict whose keys match ur5e_dataconfig's RepackTransform RHS so a
    PI05Policy will accept it directly.

    Language tokenization
    ---------------------
    PI05Policy.predict_action_chunk reads pre-tokenized language directly from
    the batch (PI05Processor bypassed). Two paths:

    - **Production**: pass ``tokenizer=transformers.AutoTokenizer.from_pretrained(
      "google/paligemma-3b-pt-224")``. Real input_ids / attention_mask are
      written into the batch so the trained model behaves correctly.
    - **Smoke / random-init test**: leave ``tokenizer=None``. Zero-valued
      placeholders are written instead — shape contract flows but model
      output is meaningless (which is fine for shape tests).
    """
    if state.shape != (7,):
        raise ValueError(f"state must be shape (7,), got {state.shape}")

    if tokenizer is None:
        lang_tokens = torch.zeros(1, max_lang_len, dtype=torch.long, device=device)
        lang_mask = torch.zeros(1, max_lang_len, dtype=torch.bool, device=device)
    else:
        # transformers PreTrainedTokenizer interface — works for AutoTokenizer
        encoded = tokenizer(
            prompt,
            max_length=max_lang_len,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )
        lang_tokens = encoded["input_ids"].to(device)
        lang_mask = encoded["attention_mask"].to(device).bool()
        if lang_tokens.shape != (1, max_lang_len):
            raise ValueError(
                f"tokenizer returned input_ids shape {tuple(lang_tokens.shape)}, "
                f"expected (1, {max_lang_len})"
            )

    return {
        IMG_KEY_CENTER: numpy_image_to_chw(img_center).unsqueeze(0).to(device),
        IMG_KEY_LEFT: numpy_image_to_chw(img_left).unsqueeze(0).to(device),
        IMG_KEY_RIGHT: numpy_image_to_chw(img_right).unsqueeze(0).to(device),
        STATE_KEY: torch.from_numpy(state).unsqueeze(0).to(device),
        "observation.language.tokens": lang_tokens,
        "observation.language.attention_mask": lang_mask,
        TASK_KEY: [prompt],
    }


def slice_arm_action(action_padded: torch.Tensor) -> np.ndarray:
    """Extract the 6 arm-joint dims from a PI05 padded action tensor.

    PI05 outputs (max_action_dim,) per step. We trained on 7D (6 arm + gripper)
    and B3 deferred gripper handling — drop action[6] and any padding beyond.
    """
    if action_padded.ndim == 0 or action_padded.shape[-1] < 6:
        raise ValueError(
            f"action must have last dim >= 6, got {tuple(action_padded.shape)}"
        )
    return action_padded[..., :6].float().cpu().numpy().reshape(6)


# --------------------------------------------------------------------------- #
# Stateful inference wrapper
# --------------------------------------------------------------------------- #


class Pi05InferenceCore:
    """Thin stateful wrapper around lerobot PI05Policy with sane AIC defaults.

    Holds the model, the GPU lock (for thread safety in MultiThreadedExecutor
    deployments), and forwards select_action / predict_action_chunk calls.
    Construction is split between (a) ``from_pretrained`` for production use
    with a real checkpoint and (b) ``from_random_init`` for unit/Colab smoke
    tests where shape contract matters more than weight quality.
    """

    def __init__(self, policy, device: torch.device | str, *, tokenizer=None):
        """tokenizer: transformers PreTrainedTokenizer or None (zero placeholders)."""
        self.policy = policy
        self.device = torch.device(device) if not isinstance(device, torch.device) else device
        self.tokenizer = tokenizer
        self._cuda_lock = threading.Lock()

    @classmethod
    def from_pretrained(
        cls,
        ckpt_dir: str,
        *,
        device: torch.device | str | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_state_dim: int = DEFAULT_MAX_STATE_DIM,
        max_action_dim: int = DEFAULT_MAX_ACTION_DIM,
        image_resolution: tuple[int, int] = DEFAULT_IMAGE_RESOLUTION,
        tokenizer=None,
        tokenizer_name: str = DEFAULT_TOKENIZER_NAME,
    ) -> "Pi05InferenceCore":
        """Production path — load from a converted lerobot checkpoint dir.

        The checkpoint is expected to be the output of
        ``toolkits/lerobot_conversion/convert_rlinf_to_lerobot.py`` (Phase 3.7).

        Tokenizer:
            - If ``tokenizer`` is provided, use it as-is.
            - Else load ``transformers.AutoTokenizer.from_pretrained(tokenizer_name)``.
              Default ``tokenizer_name`` = "google/paligemma-3b-pt-224". The
              Dockerfile pre-caches this in the image layer (B5 decision) so
              first-run download does not race the AIC trial timeout.
        """
        cfg = _build_config(
            chunk_size=chunk_size,
            max_state_dim=max_state_dim,
            max_action_dim=max_action_dim,
            image_resolution=image_resolution,
        )
        from lerobot.policies.pi05.modeling_pi05 import PI05Policy

        device = torch.device(device) if device is not None else _default_device()
        policy = PI05Policy.from_pretrained(ckpt_dir, config=cfg).eval().to(device)

        if tokenizer is None:
            from transformers import AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)

        return cls(policy, device, tokenizer=tokenizer)

    @classmethod
    def from_random_init(
        cls,
        *,
        device: torch.device | str | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_state_dim: int = DEFAULT_MAX_STATE_DIM,
        max_action_dim: int = DEFAULT_MAX_ACTION_DIM,
        image_resolution: tuple[int, int] = DEFAULT_IMAGE_RESOLUTION,
        tokenizer=None,
    ) -> "Pi05InferenceCore":
        """Test path — build PI05Policy with random weights.

        Validates the shape contract (state, image, prompt → action) without
        requiring a 5GB checkpoint download. Suitable for unit tests + Colab
        smoke. Output values are nonsense; only shapes/dtypes/throughput are
        meaningful.

        Tokenizer is left as None by default — ``build_pi05_batch`` writes
        zero placeholders so tests do not pay the (small) tokenizer download
        cost. Pass an explicit tokenizer for tests that exercise the real
        tokenization path.
        """
        cfg = _build_config(
            chunk_size=chunk_size,
            max_state_dim=max_state_dim,
            max_action_dim=max_action_dim,
            image_resolution=image_resolution,
        )
        from lerobot.policies.pi05.modeling_pi05 import PI05Policy

        device = torch.device(device) if device is not None else _default_device()
        policy = PI05Policy(cfg).eval().to(device)
        return cls(policy, device, tokenizer=tokenizer)

    def reset(self) -> None:
        """Clear lerobot's internal action queue between AIC trials."""
        self.policy.reset()

    def warm_up(self) -> None:
        """Cold-start mitigation: dummy forward pass to JIT compile.

        Call once at trial start (after PI05 ckpt load) to absorb the 500-1000ms
        first-forward latency (vision encoder JIT + flow 10-step denoise) into
        the warm-up window rather than the first real chunk. Track B Production
        TODO #4 from the Colab smoke findings.

        The dummy batch goes through the same ``infer_arm`` path so any state
        that gets initialised lazily is exercised. ``reset()`` is called at
        the end so the action queue starts empty for the real trial.
        """
        h, w = DEFAULT_IMAGE_RESOLUTION
        dummy_img = np.zeros((h, w, 3), dtype=np.uint8)
        dummy_state = np.zeros(7, dtype=np.float32)
        # Use a benign prompt — content does not matter for warm-up.
        self.infer_arm(dummy_img, dummy_img, dummy_img, dummy_state, "warmup")
        # Action queue from warm-up has stale values — clear so the trial
        # starts fresh.
        self.policy.reset()

    @torch.inference_mode()
    def select_action(self, batch: dict) -> torch.Tensor:
        """Single-step inference. Returns ``(max_action_dim,)`` tensor on device."""
        with self._cuda_lock:
            action_t = self.policy.select_action(batch)
        return action_t[0]

    def infer_arm(
        self,
        img_center: np.ndarray,
        img_left: np.ndarray,
        img_right: np.ndarray,
        state: np.ndarray,
        prompt: str,
    ) -> np.ndarray:
        """End-to-end: numpy obs → 6D arm joint targets (np.float32, shape (6,)).

        Uses ``self.tokenizer`` (set in ``__init__``) to tokenise the prompt.
        If tokenizer is None (e.g. ``from_random_init`` default), zero-valued
        placeholders are used and the language head sees no real signal.
        """
        batch = build_pi05_batch(
            img_center, img_left, img_right, state, prompt,
            device=self.device,
            tokenizer=self.tokenizer,
        )
        action_t = self.select_action(batch)
        return slice_arm_action(action_t)


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _build_config(
    *,
    chunk_size: int,
    max_state_dim: int,
    max_action_dim: int,
    image_resolution: tuple[int, int],
    state_dim: int = 7,
    action_dim: int = 7,
):
    """Build a PI05Config with input/output features wired for the AIC contract.

    PI05Policy._preprocess_images consults config.input_features to decide
    which batch keys are images. Without explicit input_features, the random-init
    construction path lands with image_features={} and the model rejects every
    batch as "All image features are missing". from_pretrained populates this
    via config.json so production loads don't trip on it; for tests/random-init
    we must provide it ourselves.
    """
    from lerobot.configs.types import FeatureType, NormalizationMode, PolicyFeature
    from lerobot.policies.pi05.configuration_pi05 import PI05Config

    h, w = image_resolution
    image_shape = (3, h, w)

    input_features = {
        IMG_KEY_CENTER: PolicyFeature(type=FeatureType.VISUAL, shape=image_shape),
        IMG_KEY_LEFT: PolicyFeature(type=FeatureType.VISUAL, shape=image_shape),
        IMG_KEY_RIGHT: PolicyFeature(type=FeatureType.VISUAL, shape=image_shape),
        STATE_KEY: PolicyFeature(type=FeatureType.STATE, shape=(state_dim,)),
    }
    output_features = {
        "action": PolicyFeature(type=FeatureType.ACTION, shape=(action_dim,)),
    }

    # IDENTITY across the board — random-init smoke has no normalization stats,
    # and even for from_pretrained the on-disk config.json carries the right
    # normalization_mapping. Tests just need shapes to flow.
    normalization_mapping = {
        FeatureType.VISUAL: NormalizationMode.IDENTITY,
        FeatureType.STATE: NormalizationMode.IDENTITY,
        FeatureType.ACTION: NormalizationMode.IDENTITY,
    }

    return PI05Config(
        paligemma_variant="gemma_2b",
        action_expert_variant="gemma_300m",
        dtype="bfloat16",
        chunk_size=chunk_size,
        n_action_steps=chunk_size,
        max_state_dim=max_state_dim,
        max_action_dim=max_action_dim,
        image_resolution=image_resolution,
        rtc_config=None,  # v1: cold refill; RTC enabled in a later iteration
        input_features=input_features,
        output_features=output_features,
        normalization_mapping=normalization_mapping,
    )


def _default_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")
