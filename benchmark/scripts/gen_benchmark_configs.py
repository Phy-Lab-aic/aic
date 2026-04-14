#!/usr/bin/env python3
"""
gen_benchmark_configs.py

Benchmark config YAML generator.
Scene builder logic ported from gen_scene_config.py — no GUI, no openpyxl.

Output structure:
    benchmark/configs/sfp/benchmark_XXXX_<name>.yaml     (1 trial, SFP only)
    benchmark/configs/sc/benchmark_XXXX_<name>.yaml      (1 trial, SC only)
    benchmark/configs/mixed/benchmark_XXXX_<name>.yaml   (3 trials, SFP×2 + SC×1)

Usage:
    python3 gen_benchmark_configs.py --type sfp   --n 10
    python3 gen_benchmark_configs.py --type sc    --n 10
    python3 gen_benchmark_configs.py --type mixed --n 5
    python3 gen_benchmark_configs.py --type sfp   --n 10 --seed 42 --name custom
"""

from __future__ import annotations

import argparse
import copy
import math
import os
import random
import re
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).parent.resolve()
BENCHMARK_DIR = (_SCRIPT_DIR / "..").resolve()
CONFIGS_DIR = BENCHMARK_DIR / "configs"
DEFAULT_SAMPLE_PATH = (BENCHMARK_DIR / "../aic_engine/config/sample_config.yaml").resolve()

# ---------------------------------------------------------------------------
# Nominal values (from gen_scene_config.py)
# ---------------------------------------------------------------------------
SFP_NOMINAL_GRASP = {
    "x": 0.0, "y": 0.015385, "z": 0.04245,
    "roll": 0.4432, "pitch": -0.4838, "yaw": 1.3303,
}
SC_NOMINAL_GRASP = {
    "x": 0.0, "y": 0.015385, "z": 0.04045,
    "roll": 0.4432, "pitch": -0.4838, "yaw": 1.3303,
}

GRASP_XYZ_NOISE = 0.002
GRASP_RPY_NOISE = 0.04

SFP_BOARD_POSE = {"x": 0.15, "y": -0.2, "z": 1.14, "roll": 0.0, "pitch": 0.0, "yaw": math.pi}
SC_BOARD_POSE  = {"x": 0.17, "y": 0.0,  "z": 1.14, "roll": 0.0, "pitch": 0.0, "yaw": 3.0}

BOARD_XY_NOISE = 0.05          # ±5cm
BOARD_YAW_NOISE = math.radians(5)  # ±5°

SAMPLE_MOUNT_RAILS = {
    "lc_mount_rail_0":  {"entity_present": True,  "entity_name": "lc_mount_0",  "entity_pose": {"translation": 0.02,  "roll": 0.0, "pitch": 0.0, "yaw": 0.0}},
    "sfp_mount_rail_0": {"entity_present": True,  "entity_name": "sfp_mount_0", "entity_pose": {"translation": 0.03,  "roll": 0.0, "pitch": 0.0, "yaw": 0.0}},
    "sc_mount_rail_0":  {"entity_present": True,  "entity_name": "sc_mount_0",  "entity_pose": {"translation": -0.02, "roll": 0.0, "pitch": 0.0, "yaw": 0.0}},
    "lc_mount_rail_1":  {"entity_present": True,  "entity_name": "lc_mount_1",  "entity_pose": {"translation": -0.01, "roll": 0.0, "pitch": 0.0, "yaw": 0.0}},
    "sfp_mount_rail_1": {"entity_present": False},
    "sc_mount_rail_1":  {"entity_present": False},
}

# Uniform-distribution targets
SFP_TARGETS = [(rail, port) for rail in range(5) for port in ["sfp_port_0", "sfp_port_1"]]
SC_TARGETS = [0, 1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _noise(rng: random.Random, nominal: float, delta: float) -> float:
    return nominal + rng.uniform(-delta, delta)


def _assert_in_range(name: str, value: float, lo: float, hi: float) -> None:
    assert lo <= value <= hi, f"[ASSERT] {name}={value:.6f} outside [{lo}, {hi}]"


def _get_dumper() -> type:
    dumper = yaml.Dumper
    dumper.add_representer(
        bool,
        lambda d, v: d.represent_scalar("tag:yaml.org,2002:bool", str(v)),
    )
    return dumper


def load_base_config(sample_path: Path) -> dict[str, Any]:
    with open(sample_path, "r") as f:
        cfg = yaml.safe_load(f)
    return {
        "scoring": cfg["scoring"],
        "task_board_limits": cfg["task_board_limits"],
        "robot": cfg["robot"],
    }


# ---------------------------------------------------------------------------
# Gripper offset randomizers
# ---------------------------------------------------------------------------

def _randomize_board_pose(rng: random.Random, nominal: dict[str, float]) -> dict[str, float]:
    """Randomize task board xy position (±5cm) and yaw (±10°)."""
    return {
        "x": round(_noise(rng, nominal["x"], BOARD_XY_NOISE), 6),
        "y": round(_noise(rng, nominal["y"], BOARD_XY_NOISE), 6),
        "z": nominal["z"],
        "roll": nominal["roll"],
        "pitch": nominal["pitch"],
        "yaw": round(_noise(rng, nominal["yaw"], BOARD_YAW_NOISE), 6),
    }


def randomize_sfp_gripper_offset(rng: random.Random) -> dict[str, float]:
    n = SFP_NOMINAL_GRASP
    return {k: _noise(rng, n[k], GRASP_XYZ_NOISE if k in ("x", "y", "z") else GRASP_RPY_NOISE) for k in n}


def randomize_sc_gripper_offset(rng: random.Random) -> dict[str, float]:
    n = SC_NOMINAL_GRASP
    return {k: _noise(rng, n[k], GRASP_XYZ_NOISE if k in ("x", "y", "z") else GRASP_RPY_NOISE) for k in n}


# ---------------------------------------------------------------------------
# Scene builders
# ---------------------------------------------------------------------------

def _randomize_nic_rails(
    rng: random.Random, limits: dict[str, Any], must_include: int,
) -> dict[str, Any]:
    nic_t_min = limits["nic_rail"]["min_translation"]
    nic_t_max = limits["nic_rail"]["max_translation"]
    nic_yaw_max = math.radians(10)

    n_nic = rng.randint(1, 5)
    nic_rails = set(rng.sample(range(5), n_nic))
    nic_rails.add(must_include)

    result: dict[str, Any] = {}
    for i in range(5):
        if i in nic_rails:
            t = rng.uniform(nic_t_min, nic_t_max)
            y = rng.uniform(-nic_yaw_max, nic_yaw_max)
            _assert_in_range(f"nic_rail_{i}.translation", t, nic_t_min, nic_t_max)
            result[f"nic_rail_{i}"] = {
                "entity_present": True,
                "entity_name": f"nic_card_{i}",
                "entity_pose": {"translation": round(t, 6), "roll": 0.0, "pitch": 0.0, "yaw": round(y, 6)},
            }
        else:
            result[f"nic_rail_{i}"] = {"entity_present": False}
    return result


def _randomize_sc_rails(
    rng: random.Random, limits: dict[str, Any], must_include: int,
) -> dict[str, Any]:
    sc_t_min = limits["sc_rail"]["min_translation"]
    sc_t_max = limits["sc_rail"]["max_translation"]

    present = [bool(rng.getrandbits(1)), bool(rng.getrandbits(1))]
    present[must_include] = True

    result: dict[str, Any] = {}
    for i in range(2):
        if present[i]:
            t = rng.uniform(sc_t_min, sc_t_max)
            _assert_in_range(f"sc_rail_{i}.translation", t, sc_t_min, sc_t_max)
            result[f"sc_rail_{i}"] = {
                "entity_present": True,
                "entity_name": f"sc_mount_{i}",
                "entity_pose": {"translation": round(t, 6), "roll": 0.0, "pitch": 0.0, "yaw": 0.0},
            }
        else:
            result[f"sc_rail_{i}"] = {"entity_present": False}
    return result


def build_sfp_scene(
    rng: random.Random, limits: dict[str, Any],
    target_rail: int | None = None, port_name: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if target_rail is None:
        target_rail = rng.randint(0, 4)
    if port_name is None:
        port_name = rng.choice(["sfp_port_0", "sfp_port_1"])

    task_board: dict[str, Any] = {"pose": _randomize_board_pose(rng, SFP_BOARD_POSE)}
    task_board.update(_randomize_nic_rails(rng, limits, target_rail))
    task_board.update(_randomize_sc_rails(rng, limits, must_include=rng.randint(0, 1)))
    task_board.update(copy.deepcopy(SAMPLE_MOUNT_RAILS))

    g = randomize_sfp_gripper_offset(rng)
    cables = {"cable_0": {
        "pose": {
            "gripper_offset": {"x": round(g["x"], 6), "y": round(g["y"], 6), "z": round(g["z"], 6)},
            "roll": round(g["roll"], 6), "pitch": round(g["pitch"], 6), "yaw": round(g["yaw"], 6),
        },
        "attach_cable_to_gripper": True,
        "cable_type": "sfp_sc_cable",
    }}

    task = {
        "cable_type": "sfp_sc", "cable_name": "cable_0",
        "plug_type": "sfp", "plug_name": "sfp_tip",
        "port_type": "sfp", "port_name": port_name,
        "target_module_name": f"nic_card_mount_{target_rail}",
        "time_limit": 180,
    }
    return {"task_board": task_board, "cables": cables}, task


def build_sc_scene(
    rng: random.Random, limits: dict[str, Any],
    target_idx: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if target_idx is None:
        target_idx = rng.randint(0, 1)

    task_board: dict[str, Any] = {"pose": _randomize_board_pose(rng, SC_BOARD_POSE)}
    task_board.update(_randomize_nic_rails(rng, limits, must_include=rng.randint(0, 4)))
    task_board.update(_randomize_sc_rails(rng, limits, target_idx))
    task_board.update(copy.deepcopy(SAMPLE_MOUNT_RAILS))

    g = randomize_sc_gripper_offset(rng)
    cables = {"cable_1": {
        "pose": {
            "gripper_offset": {"x": round(g["x"], 6), "y": round(g["y"], 6), "z": round(g["z"], 6)},
            "roll": round(g["roll"], 6), "pitch": round(g["pitch"], 6), "yaw": round(g["yaw"], 6),
        },
        "attach_cable_to_gripper": True,
        "cable_type": "sfp_sc_cable_reversed",
    }}

    task = {
        "cable_type": "sfp_sc", "cable_name": "cable_1",
        "plug_type": "sc", "plug_name": "sc_tip",
        "port_type": "sc", "port_name": "sc_port_base",
        "target_module_name": f"sc_port_{target_idx}",
        "time_limit": 180,
    }
    return {"task_board": task_board, "cables": cables}, task


# ---------------------------------------------------------------------------
# Config builders
# ---------------------------------------------------------------------------

def _wrap_config(base: dict[str, Any], trials: dict[str, Any]) -> dict[str, Any]:
    return {
        "scoring": base["scoring"],
        "task_board_limits": base["task_board_limits"],
        "trials": trials,
        "robot": base["robot"],
    }


def build_single_sfp(base: dict[str, Any], rng: random.Random,
                     target_rail: int | None = None,
                     port_name: str | None = None) -> dict[str, Any]:
    """1 trial — SFP only."""
    scene, task = build_sfp_scene(rng, base["task_board_limits"], target_rail, port_name)
    return _wrap_config(base, {"trial_1": {"scene": scene, "tasks": {"task_1": task}}})


def build_single_sc(base: dict[str, Any], rng: random.Random,
                    target_idx: int | None = None) -> dict[str, Any]:
    """1 trial — SC only."""
    scene, task = build_sc_scene(rng, base["task_board_limits"], target_idx)
    return _wrap_config(base, {"trial_1": {"scene": scene, "tasks": {"task_1": task}}})


def build_mixed(base: dict[str, Any], rng: random.Random,
                sfp_target_1: tuple[int, str] | None = None,
                sfp_target_2: tuple[int, str] | None = None,
                sc_target: int | None = None) -> dict[str, Any]:
    """3 trials — SFP + SFP + SC (standard evaluation flow)."""
    limits = base["task_board_limits"]
    r1, p1 = sfp_target_1 if sfp_target_1 else (None, None)
    r2, p2 = sfp_target_2 if sfp_target_2 else (None, None)
    s1, t1 = build_sfp_scene(rng, limits, r1, p1)
    s2, t2 = build_sfp_scene(rng, limits, r2, p2)
    s3, t3 = build_sc_scene(rng, limits, sc_target)
    return _wrap_config(base, {
        "trial_1": {"scene": s1, "tasks": {"task_1": t1}},
        "trial_2": {"scene": s2, "tasks": {"task_1": t2}},
        "trial_3": {"scene": s3, "tasks": {"task_1": t3}},
    })


# ---------------------------------------------------------------------------
# Index detection (per subdirectory)
# ---------------------------------------------------------------------------

def _next_idx(output_dir: Path) -> int:
    indices: list[int] = []
    for f in output_dir.glob("benchmark_*.yaml"):
        m = re.match(r"benchmark_(\d+)", f.stem)
        if m:
            indices.append(int(m.group(1)))
    return max(indices) + 1 if indices else 0


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def generate(config_type: str, n: int, name: str | None, seed: int) -> list[Path]:
    base = load_base_config(DEFAULT_SAMPLE_PATH)
    rng = random.Random(seed)

    output_dir = CONFIGS_DIR / config_type
    output_dir.mkdir(parents=True, exist_ok=True)

    start_idx = _next_idx(output_dir)
    if not name:
        name = config_type

    created: list[Path] = []
    for i in range(n):
        idx = start_idx + i

        if config_type == "sfp":
            target_rail, port_name = SFP_TARGETS[i % len(SFP_TARGETS)]
            cfg = build_single_sfp(base, rng, target_rail, port_name)
        elif config_type == "sc":
            target_idx = SC_TARGETS[i % len(SC_TARGETS)]
            cfg = build_single_sc(base, rng, target_idx)
        else:  # mixed
            sfp_t1 = SFP_TARGETS[i % len(SFP_TARGETS)]
            sfp_t2 = SFP_TARGETS[(i + len(SFP_TARGETS) // 2) % len(SFP_TARGETS)]
            sc_t = SC_TARGETS[i % len(SC_TARGETS)]
            cfg = build_mixed(base, rng, sfp_t1, sfp_t2, sc_t)

        filename = f"benchmark_{idx:04d}_{name}.yaml"
        filepath = output_dir / filename

        with open(filepath, "w") as f:
            yaml.dump(cfg, f, Dumper=_get_dumper(), default_flow_style=False, sort_keys=False)

        created.append(filepath)

    return created


def main():
    parser = argparse.ArgumentParser(description="Generate benchmark configs")
    parser.add_argument("--type", choices=["sfp", "sc", "mixed"], required=True,
                        help="sfp: 1 trial SFP, sc: 1 trial SC, mixed: 3 trials (SFP×2+SC×1)")
    parser.add_argument("--n", type=int, default=1,
                        help="Number of configs to generate (default: 1)")
    parser.add_argument("--name", type=str, default=None,
                        help="Name suffix (default: type name)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed (default: random)")
    args = parser.parse_args()

    seed = args.seed if args.seed is not None else int.from_bytes(os.urandom(4), "big")
    created = generate(args.type, args.n, args.name, seed)

    print(f"Seed: {seed}")
    print(f"Generated {len(created)} config(s) -> {created[0].parent}/")
    for p in created:
        print(f"  {p.name}")


if __name__ == "__main__":
    main()
