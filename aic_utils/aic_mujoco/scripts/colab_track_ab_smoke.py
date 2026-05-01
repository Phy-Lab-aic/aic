#!/usr/bin/env python3
"""Colab integration smoke for Track A (AIC MuJoCo env) + Track B (lerobot PI05 inference).

End-to-end loop on a Colab GPU instance, with no AIC ROS / pixi / Docker needed.
Validates the architecture before any RL training is attempted.

Tests:
  T1: AIC MuJoCo scene loads + steps (Track A foundation)
  T2: AICMuJoCoEnv (gym.Env wrapper) reset + step (Track A v0 skeleton)
  T3: lerobot PI05Policy random-init forward (Track B inference plumbing)
  T4: env obs → batch → PI05 select_action → action → env.step (integrated)

T3/T4 use a *random-initialised* PI05Policy so no SFT checkpoint is required.
That checks the data-shape contract end to end. Replace with from_pretrained
once a converted lerobot checkpoint exists.

Colab cell sequence (recommended)::

    !pip install -q mujoco gymnasium torch transformers safetensors
    !pip install -q "git+https://github.com/RLinf/openpi"
    !pip install -q "lerobot==0.4.3"

    # transformers_replace patch (required by lerobot PI05Pytorch)
    !OPENPI_DIR=$(python3 -c "import openpi, os; print(os.path.dirname(openpi.__file__))") \\
       && TRANSFORMERS_DIR=$(python3 -c "import transformers, os; print(os.path.dirname(transformers.__file__))") \\
       && cp -r "${OPENPI_DIR}/models_pytorch/transformers_replace/"* "${TRANSFORMERS_DIR}/"

    !git clone --depth 1 https://github.com/intrinsic-dev/aic.git /content/aic
    !git clone --depth 1 https://github.com/RLinf/RLinf.git /content/RLinf

    !PYTHONPATH=/content/RLinf python3 /content/aic/aic_utils/aic_mujoco/scripts/colab_track_ab_smoke.py \\
        --mjcf /content/aic/aic_utils/aic_mujoco/mjcf/scene.xml
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path


def _section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def _ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def _fail(msg: str) -> None:
    print(f"  ❌ {msg}")


def t1_scene_load(mjcf_path: Path, bench_seconds: float) -> bool:
    _section("T1 — AIC MuJoCo scene loads + steps")
    try:
        import mujoco
    except ImportError:
        _fail("pip install mujoco")
        return False
    try:
        t0 = time.perf_counter()
        model = mujoco.MjModel.from_xml_path(str(mjcf_path))
        data = mujoco.MjData(model)
        load_s = time.perf_counter() - t0
        _ok(f"loaded in {load_s:.2f}s — nq={model.nq}, nbody={model.nbody}")

        # warm-up + benchmark
        for _ in range(50):
            mujoco.mj_step(model, data)
        n, t0 = 0, time.perf_counter()
        while time.perf_counter() - t0 < bench_seconds:
            mujoco.mj_step(model, data)
            n += 1
        wall = time.perf_counter() - t0
        rt = (n * model.opt.timestep) / wall
        _ok(f"step rate {n/wall:.1f} step/s ({rt:.2f}x realtime)")
        if rt < 1.0:
            _fail(f"sub-realtime — Track A on this CPU is borderline")
        return True
    except Exception:
        traceback.print_exc()
        return False


def t2_env_skeleton(mjcf_path: Path) -> bool:
    _section("T2 — AICMuJoCoEnv (gym.Env wrapper) reset + step")
    try:
        from rlinf.envs.aic_mujoco import AICMuJoCoEnv
    except ImportError:
        _fail("PYTHONPATH must include the RLinf repo root so rlinf.envs is importable")
        traceback.print_exc()
        return False
    try:
        env = AICMuJoCoEnv(mjcf_path=mjcf_path, seed=0)
        _ok(f"action_space={env.action_space}, observation_space={env.observation_space}")

        obs, info = env.reset(seed=0)
        _ok(f"reset → obs.state shape={obs['state'].shape}, dtype={obs['state'].dtype}")

        import numpy as np
        action = np.zeros(6, dtype=np.float32)
        for i in range(5):
            obs, reward, term, trunc, info = env.step(action)
        _ok(f"5 steps OK → reward={reward}, terminated={term}, truncated={trunc}")
        env.close()
        return True
    except Exception:
        traceback.print_exc()
        return False


def t3_pi05_forward() -> bool:
    _section("T3 — lerobot PI05Policy random-init forward")
    try:
        import torch
        from lerobot.policies.pi05.configuration_pi05 import PI05Config
        from lerobot.policies.pi05.modeling_pi05 import PI05Policy
    except ImportError:
        _fail("pip install lerobot==0.4.3 (and apply transformers_replace patch)")
        traceback.print_exc()
        return False
    try:
        cfg = PI05Config(
            paligemma_variant="gemma_2b",
            action_expert_variant="gemma_300m",
            dtype="bfloat16",
            chunk_size=10,
            n_action_steps=10,
            max_state_dim=32,
            max_action_dim=32,
            image_resolution=(224, 224),
            rtc_config=None,
        )
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _ok(f"device={device}")

        t0 = time.perf_counter()
        policy = PI05Policy(cfg).eval().to(device)
        _ok(f"random-init constructed in {time.perf_counter()-t0:.1f}s")

        batch = {
            "observation.images.cam_center": torch.rand(1, 3, 224, 224, device=device),
            "observation.images.cam_left": torch.rand(1, 3, 224, 224, device=device),
            "observation.images.cam_right": torch.rand(1, 3, 224, 224, device=device),
            "observation.state": torch.rand(1, 7, device=device),
            "task": ["Insert the sfp plug into port sfp_port_0 on nic_card_0."],
        }
        with torch.inference_mode():
            t0 = time.perf_counter()
            action = policy.select_action(batch)
            forward_s = time.perf_counter() - t0
        _ok(f"select_action → shape={tuple(action.shape)} in {forward_s*1000:.0f} ms")
        return True
    except Exception:
        traceback.print_exc()
        return False


def t4_integrated(mjcf_path: Path) -> bool:
    _section("T4 — env obs → PI05 select_action → env.step (integrated)")
    try:
        import numpy as np
        import torch
        from lerobot.policies.pi05.configuration_pi05 import PI05Config
        from lerobot.policies.pi05.modeling_pi05 import PI05Policy

        from rlinf.envs.aic_mujoco import AICMuJoCoEnv
    except ImportError:
        _fail("missing deps — see T2/T3 errors above")
        return False
    try:
        env = AICMuJoCoEnv(mjcf_path=mjcf_path, seed=0)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        cfg = PI05Config(
            paligemma_variant="gemma_2b",
            action_expert_variant="gemma_300m",
            dtype="bfloat16",
            chunk_size=10,
            n_action_steps=10,
            max_state_dim=32,
            max_action_dim=32,
            image_resolution=(224, 224),
            rtc_config=None,
        )
        policy = PI05Policy(cfg).eval().to(device)

        obs, _ = env.reset(seed=0)
        for tick in range(5):
            # MyPi05Policy-style batch assembly. v0 env has no images yet, so
            # we substitute random images — Track B's _ros_image_to_chw will
            # plug in the real adapter feed once integration is on Gazebo/eval.
            batch = {
                "observation.images.cam_center": torch.rand(1, 3, 224, 224, device=device),
                "observation.images.cam_left": torch.rand(1, 3, 224, 224, device=device),
                "observation.images.cam_right": torch.rand(1, 3, 224, 224, device=device),
                "observation.state": torch.from_numpy(obs["state"]).unsqueeze(0).to(device),
                "task": ["Insert the sfp plug into port sfp_port_0 on nic_card_0."],
            }
            with torch.inference_mode():
                action_t = policy.select_action(batch)
            # PI05 returns max_action_dim padded — take first 6 (B2/B3 decision).
            action = action_t[0, :6].float().cpu().numpy()
            obs, reward, term, trunc, info = env.step(action)
        _ok(f"5 integrated ticks OK — final state[0:3]={obs['state'][:3]}")
        env.close()
        return True
    except Exception:
        traceback.print_exc()
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--mjcf", type=Path, required=True, help="Path to AIC scene.xml"
    )
    ap.add_argument("--bench-seconds", type=float, default=3.0)
    ap.add_argument(
        "--skip-policy",
        action="store_true",
        help="Skip T3/T4 (no torch/lerobot install yet).",
    )
    args = ap.parse_args()

    if not args.mjcf.is_file():
        _fail(f"{args.mjcf} not found")
        return 2

    results = {
        "T1": t1_scene_load(args.mjcf, args.bench_seconds),
        "T2": t2_env_skeleton(args.mjcf),
    }
    if not args.skip_policy:
        results["T3"] = t3_pi05_forward()
        results["T4"] = t4_integrated(args.mjcf)

    _section("SUMMARY")
    for k, v in results.items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
