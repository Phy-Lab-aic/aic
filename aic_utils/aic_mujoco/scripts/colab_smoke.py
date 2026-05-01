#!/usr/bin/env python3
"""Colab smoke test — does AIC MuJoCo scene load + step on a Colab CPU?

Single-purpose: answer the only question that matters before committing to
Track A (RLinf in-process MuJoCo env) on Colab — is the cable composite
+ elasticity plugin physics fast enough on Colab's 2-4 vCPU?

Usage in a Colab cell::

    # 1) Install
    !pip install -q mujoco

    # 2) Clone AIC (only needs the mjcf/ subtree)
    !git clone --depth 1 https://github.com/intrinsic-dev/aic.git /content/aic

    # 3) Run the smoke
    !python /content/aic/aic_utils/aic_mujoco/scripts/colab_smoke.py \\
        --mjcf /content/aic/aic_utils/aic_mujoco/mjcf/scene.xml

The script prints (a) load time, (b) step rate over 5 s, (c) realtime factor
vs the 500 Hz physics, (d) a GO/NOGO verdict for Track A.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--mjcf",
        type=Path,
        required=True,
        help="Path to AIC scene.xml (includes aic_robot.xml + aic_world.xml)",
    )
    ap.add_argument(
        "--bench-seconds",
        type=float,
        default=5.0,
        help="Wall-clock seconds to benchmark step rate (default: 5.0)",
    )
    args = ap.parse_args()

    if not args.mjcf.is_file():
        print(f"ERROR: {args.mjcf} not found", file=sys.stderr)
        return 2

    try:
        import mujoco
    except ImportError:
        print("ERROR: pip install mujoco first", file=sys.stderr)
        return 2

    print(f"MuJoCo version: {mujoco.__version__}")
    print(f"Scene: {args.mjcf}")

    # --- Load ---------------------------------------------------------------
    t0 = time.perf_counter()
    model = mujoco.MjModel.from_xml_path(str(args.mjcf))
    data = mujoco.MjData(model)
    load_s = time.perf_counter() - t0
    print(f"\nLoad: {load_s:.2f}s")
    print(f"  nq={model.nq}, nv={model.nv}, nbody={model.nbody}")
    print(f"  timestep={model.opt.timestep}s ({1/model.opt.timestep:.0f} Hz physics)")
    print(f"  ngeom={model.ngeom}, ntendon={model.ntendon}, nplugin={model.nplugin}")

    # --- Warm-up (first few steps may JIT plugins) --------------------------
    for _ in range(50):
        mujoco.mj_step(model, data)

    # --- Benchmark ----------------------------------------------------------
    sim_time_at_start = data.time
    n_steps = 0
    wall_start = time.perf_counter()
    while time.perf_counter() - wall_start < args.bench_seconds:
        mujoco.mj_step(model, data)
        n_steps += 1
    wall_elapsed = time.perf_counter() - wall_start
    sim_elapsed = data.time - sim_time_at_start

    step_rate = n_steps / wall_elapsed
    realtime_factor = sim_elapsed / wall_elapsed
    physics_hz = 1.0 / model.opt.timestep

    print(f"\nBenchmark over {wall_elapsed:.2f}s:")
    print(f"  Steps:           {n_steps}")
    print(f"  Step rate:       {step_rate:.1f} step/s")
    print(f"  Sim time:        {sim_elapsed:.3f}s")
    print(f"  Realtime factor: {realtime_factor:.2f}x  (1.0x = real-time at {physics_hz:.0f} Hz)")

    # --- Verdict ------------------------------------------------------------
    print("\n" + "=" * 60)
    if realtime_factor >= 5.0:
        print(f"✅ GO — {realtime_factor:.1f}x realtime. Cable physics fast enough on this CPU.")
        print("   Track A (RLinf in-process MuJoCo env) is viable on Colab.")
        verdict = 0
    elif realtime_factor >= 2.0:
        print(f"⚠️  MARGINAL — {realtime_factor:.1f}x realtime.")
        print("   Track A possible but PPO wall-clock will be slow. Consider:")
        print("   - num_envs=4 max, accept multi-day training")
        print("   - simplify cable (rigid links instead of elasticity plugin)")
        print("   - Colab Pro+ for L4 + 24h sessions")
        verdict = 0
    elif realtime_factor >= 1.0:
        print(f"⚠️  SLOW — {realtime_factor:.1f}x realtime. Borderline.")
        print("   PPO would take many days. Strongly consider:")
        print("   - MuJoCo MJX (JAX/GPU port) — needs cable plugin port check")
        print("   - dedicated machine instead of Colab")
        verdict = 0
    else:
        print(f"❌ NOGO — {realtime_factor:.1f}x realtime (sub-realtime!).")
        print("   PPO is not feasible. Plan must change:")
        print("   - rewrite cable as rigid linkage")
        print("   - or pivot off Colab to a many-core / GPU-physics setup")
        verdict = 1
    print("=" * 60)
    return verdict


if __name__ == "__main__":
    raise SystemExit(main())
