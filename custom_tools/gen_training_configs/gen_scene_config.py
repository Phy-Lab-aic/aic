#!/usr/bin/env python3
"""
gen_scene_config.py

AIC qualification-phase config YAML generator.

- train mode: 1 config = 1 trial. Separate sfp/, sc/ folders.
    configs/train/sfp/config_sfp_0000.yaml
    configs/train/sc/config_sc_0000.yaml

- test mode: 1 config = 3 trials (SFP x2 + SC x1). Evaluation flow.
    configs/test/config_test_0000.yaml

Usage:
    python3 gen_scene_config.py --mode train --n 100
    python3 gen_scene_config.py --mode test --n 20
    python3 gen_scene_config.py   # interactive
"""

from __future__ import annotations

import copy
import math
import os
import random
from pathlib import Path
from typing import Any

import customtkinter as ctk

import openpyxl
from openpyxl.styles import Font, PatternFill
import yaml


# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).parent.resolve()
DEFAULT_SAMPLE_PATH = (_SCRIPT_DIR / "../../aic_engine/config/sample_config.yaml").resolve()
DEFAULT_OUTPUT_BASE = (_SCRIPT_DIR / "configs").resolve()


# ---------------------------------------------------------------------------
# Nominal grasp values (qualification_phase.md + sample_config.yaml)
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

SAMPLE_MOUNT_RAILS = {
    "lc_mount_rail_0":  {"entity_present": True,  "entity_name": "lc_mount_0",  "entity_pose": {"translation": 0.02,  "roll": 0.0, "pitch": 0.0, "yaw": 0.0}},
    "sfp_mount_rail_0": {"entity_present": True,  "entity_name": "sfp_mount_0", "entity_pose": {"translation": 0.03,  "roll": 0.0, "pitch": 0.0, "yaw": 0.0}},
    "sc_mount_rail_0":  {"entity_present": True,  "entity_name": "sc_mount_0",  "entity_pose": {"translation": -0.02, "roll": 0.0, "pitch": 0.0, "yaw": 0.0}},
    "lc_mount_rail_1":  {"entity_present": True,  "entity_name": "lc_mount_1",  "entity_pose": {"translation": -0.01, "roll": 0.0, "pitch": 0.0, "yaw": 0.0}},
    "sfp_mount_rail_1": {"entity_present": False},
    "sc_mount_rail_1":  {"entity_present": False},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _noise(rng: random.Random, nominal: float, delta: float) -> float:
    return nominal + rng.uniform(-delta, delta)


def _assert_in_range(name: str, value: float, lo: float, hi: float) -> None:
    assert lo <= value <= hi, f"[ASSERT] {name}={value:.6f} outside [{lo}, {hi}]"


def load_base_config(sample_path: Path) -> dict[str, Any]:
    with open(sample_path, "r") as f:
        cfg = yaml.safe_load(f)
    return {
        "scoring": cfg["scoring"],
        "task_board_limits": cfg["task_board_limits"],
        "robot": cfg["robot"],
    }


def _get_dumper() -> type:
    dumper = yaml.Dumper
    dumper.add_representer(
        bool,
        lambda d, v: d.represent_scalar("tag:yaml.org,2002:bool", str(v)),
    )
    return dumper


# ---------------------------------------------------------------------------
# Gripper offset randomizers
# ---------------------------------------------------------------------------

def randomize_sfp_gripper_offset(rng: random.Random) -> dict[str, float]:
    n = SFP_NOMINAL_GRASP
    return {k: _noise(rng, n[k], GRASP_XYZ_NOISE if k in ("x", "y", "z") else GRASP_RPY_NOISE) for k in n}


def randomize_sc_gripper_offset(rng: random.Random) -> dict[str, float]:
    n = SC_NOMINAL_GRASP
    return {k: _noise(rng, n[k], GRASP_XYZ_NOISE if k in ("x", "y", "z") else GRASP_RPY_NOISE) for k in n}


# ---------------------------------------------------------------------------
# Scene builders
# ---------------------------------------------------------------------------

# All possible task targets for uniform distribution
# SFP: 5 rails x 2 ports = 10 combinations
SFP_TARGETS = [(rail, port)
               for rail in range(5)
               for port in ["sfp_port_0", "sfp_port_1"]]
# SC: 2 ports
SC_TARGETS = [0, 1]


def _randomize_nic_rails(
    rng: random.Random, limits: dict[str, Any], must_include: int,
) -> dict[str, Any]:
    """Generate random NIC card layout. must_include rail is always present."""
    nic_t_min = limits["nic_rail"]["min_translation"]
    nic_t_max = limits["nic_rail"]["max_translation"]
    nic_yaw_max = math.radians(10)

    n_nic = rng.randint(1, 5)
    nic_rails = set(rng.sample(range(5), n_nic))
    nic_rails.add(must_include)  # target rail must be present

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
    """Generate random SC port layout. must_include port is always present."""
    sc_t_min = limits["sc_rail"]["min_translation"]
    sc_t_max = limits["sc_rail"]["max_translation"]

    present = [bool(rng.getrandbits(1)), bool(rng.getrandbits(1))]
    present[must_include] = True  # target port must be present

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
    """Build SFP scene. NIC cards + SC ports both present."""
    if target_rail is None:
        target_rail = rng.randint(0, 4)
    if port_name is None:
        port_name = rng.choice(["sfp_port_0", "sfp_port_1"])

    task_board: dict[str, Any] = {"pose": dict(SFP_BOARD_POSE)}
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
    """Build SC scene. SC ports + NIC cards both present."""
    if target_idx is None:
        target_idx = rng.randint(0, 1)

    task_board: dict[str, Any] = {"pose": dict(SC_BOARD_POSE)}
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

def build_single_config(
    base: dict[str, Any], rng: random.Random, task_type: str,
    target_rail: int | None = None, port_name: str | None = None,
    target_idx: int | None = None,
) -> dict[str, Any]:
    """Build 1-trial config (train mode)."""
    limits = base["task_board_limits"]
    if task_type == "sfp":
        scene, task = build_sfp_scene(rng, limits, target_rail, port_name)
    else:
        scene, task = build_sc_scene(rng, limits, target_idx)
    return {
        "scoring": base["scoring"],
        "task_board_limits": base["task_board_limits"],
        "trials": {"trial_1": {"scene": scene, "tasks": {"task_1": task}}},
        "robot": base["robot"],
    }


def build_full_config(
    base: dict[str, Any], rng: random.Random,
    sfp_target_1: tuple[int, str] | None = None,
    sfp_target_2: tuple[int, str] | None = None,
    sc_target: int | None = None,
) -> dict[str, Any]:
    """Build 3-trial config (test mode): SFP + SFP + SC."""
    limits = base["task_board_limits"]
    r1, p1 = sfp_target_1 if sfp_target_1 else (None, None)
    r2, p2 = sfp_target_2 if sfp_target_2 else (None, None)
    scene1, task1 = build_sfp_scene(rng, limits, r1, p1)
    scene2, task2 = build_sfp_scene(rng, limits, r2, p2)
    scene3, task3 = build_sc_scene(rng, limits, sc_target)
    return {
        "scoring": base["scoring"],
        "task_board_limits": base["task_board_limits"],
        "trials": {
            "trial_1": {"scene": scene1, "tasks": {"task_1": task1}},
            "trial_2": {"scene": scene2, "tasks": {"task_1": task2}},
            "trial_3": {"scene": scene3, "tasks": {"task_1": task3}},
        },
        "robot": base["robot"],
    }


# ---------------------------------------------------------------------------
# Excel logging
# ---------------------------------------------------------------------------

_EXCEL_COLUMNS = [
    "file", "seed", "trial", "type",
    "n_nic", "nic_rails", "sc_rails",
    "target_rail", "port_name",
    "target_trans", "target_yaw",
    "gripper_x", "gripper_y", "gripper_z",
    "gripper_roll", "gripper_pitch", "gripper_yaw",
]

_HEADER_FILL = PatternFill("solid", fgColor="4F81BD")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_SFP_FILL = PatternFill("solid", fgColor="DCE6F1")
_SC_FILL = PatternFill("solid", fgColor="FDE9D9")
_ROW_FILL = {
    "trial_1": PatternFill("solid", fgColor="DCE6F1"),
    "trial_2": PatternFill("solid", fgColor="EBF1DE"),
    "trial_3": PatternFill("solid", fgColor="FDE9D9"),
}


def _sfp_row(filename: str, seed: int, cfg: dict, trial_key: str = "trial_1") -> dict[str, Any]:
    trial = cfg["trials"][trial_key]
    tb = trial["scene"]["task_board"]
    task = trial["tasks"]["task_1"]
    cable = trial["scene"]["cables"]["cable_0"]
    go = cable["pose"]["gripper_offset"]
    nic_rails = [i for i in range(5) if tb.get(f"nic_rail_{i}", {}).get("entity_present", False)]
    target_rail = int(task["target_module_name"].split("_")[-1])
    target_pose = tb[f"nic_rail_{target_rail}"]["entity_pose"]
    return {
        "file": filename, "seed": seed, "trial": trial_key, "type": "SFP",
        "n_nic": len(nic_rails),
        "nic_rails": ",".join(str(r) for r in sorted(nic_rails)),
        "sc_rails": None,
        "target_rail": target_rail, "port_name": task["port_name"],
        "target_trans": round(target_pose["translation"], 6),
        "target_yaw": round(target_pose["yaw"], 6),
        "gripper_x": go["x"], "gripper_y": go["y"], "gripper_z": go["z"],
        "gripper_roll": cable["pose"]["roll"],
        "gripper_pitch": cable["pose"]["pitch"],
        "gripper_yaw": cable["pose"]["yaw"],
    }


def _sc_row(filename: str, seed: int, cfg: dict, trial_key: str = "trial_1") -> dict[str, Any]:
    trial = cfg["trials"][trial_key]
    tb = trial["scene"]["task_board"]
    task = trial["tasks"]["task_1"]
    cable = trial["scene"]["cables"]["cable_1"]
    go = cable["pose"]["gripper_offset"]
    sc_rails = [i for i in range(2) if tb.get(f"sc_rail_{i}", {}).get("entity_present", False)]
    target_rail = int(task["target_module_name"].split("_")[-1])
    target_pose = tb[f"sc_rail_{target_rail}"]["entity_pose"]
    return {
        "file": filename, "seed": seed, "trial": trial_key, "type": "SC",
        "n_nic": None, "nic_rails": None,
        "sc_rails": ",".join(str(r) for r in sorted(sc_rails)),
        "target_rail": target_rail, "port_name": task["port_name"],
        "target_trans": round(target_pose["translation"], 6),
        "target_yaw": None,
        "gripper_x": go["x"], "gripper_y": go["y"], "gripper_z": go["z"],
        "gripper_roll": cable["pose"]["roll"],
        "gripper_pitch": cable["pose"]["pitch"],
        "gripper_yaw": cable["pose"]["yaw"],
    }


def append_to_excel(log_path: Path, rows: list[dict[str, Any]], use_trial_fill: bool = False) -> None:
    if log_path.exists():
        wb = openpyxl.load_workbook(log_path)
        ws = wb.active
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "trials"
        for col_idx, col_name in enumerate(_EXCEL_COLUMNS, start=1):
            cell = ws.cell(row=1, column=col_idx, value=col_name)
            cell.font = _HEADER_FONT
            cell.fill = _HEADER_FILL
        ws.freeze_panes = "A2"

    for row_data in rows:
        row_idx = ws.max_row + 1
        if use_trial_fill:
            row_fill = _ROW_FILL.get(row_data.get("trial", ""))
        else:
            row_fill = _SFP_FILL if row_data.get("type") == "SFP" else _SC_FILL
        for col_idx, col_name in enumerate(_EXCEL_COLUMNS, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=row_data.get(col_name))
            if row_fill:
                cell.fill = row_fill

    wb.save(log_path)


# ---------------------------------------------------------------------------
# Auto-detect next offset
# ---------------------------------------------------------------------------

def _next_offset(output_dir: Path, prefix: str) -> int:
    if not output_dir.exists():
        return 0
    indices = []
    for f in output_dir.glob(f"config_{prefix}_*.yaml"):
        try:
            indices.append(int(f.stem.split("_")[-1]))
        except ValueError:
            pass
    return max(indices) + 1 if indices else 0


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def print_single_stats(sfp_configs: list[dict], sc_configs: list[dict]) -> None:
    if sfp_configs:
        nic_counts = {i: 0 for i in range(5)}
        for cfg in sfp_configs:
            tb = cfg["trials"]["trial_1"]["scene"]["task_board"]
            for i in range(5):
                if tb.get(f"nic_rail_{i}", {}).get("entity_present", False):
                    nic_counts[i] += 1
        total = len(sfp_configs)
        print(f"\n--- NIC rail distribution (SFP, n={total}) ---")
        for i in range(5):
            print(f"  nic_rail_{i}: {nic_counts[i]:4d}/{total} ({100*nic_counts[i]/total:.1f}%)")

    if sc_configs:
        sc_counts = {0: 0, 1: 0}
        for cfg in sc_configs:
            tb = cfg["trials"]["trial_1"]["scene"]["task_board"]
            for i in range(2):
                if tb.get(f"sc_rail_{i}", {}).get("entity_present", False):
                    sc_counts[i] += 1
        total = len(sc_configs)
        print(f"\n--- SC rail distribution (SC, n={total}) ---")
        for i in range(2):
            print(f"  sc_rail_{i}: {sc_counts[i]:4d}/{total} ({100*sc_counts[i]/total:.1f}%)")


def print_full_stats(configs: list[dict]) -> None:
    nic_counts = {i: 0 for i in range(5)}
    sc_counts = {0: 0, 1: 0}
    for cfg in configs:
        for tk in ("trial_1", "trial_2"):
            tb = cfg["trials"][tk]["scene"]["task_board"]
            for i in range(5):
                if tb.get(f"nic_rail_{i}", {}).get("entity_present", False):
                    nic_counts[i] += 1
        tb3 = cfg["trials"]["trial_3"]["scene"]["task_board"]
        for i in range(2):
            if tb3.get(f"sc_rail_{i}", {}).get("entity_present", False):
                sc_counts[i] += 1

    total_sfp = len(configs) * 2
    total_sc = len(configs)
    print("\n--- NIC rail distribution ---")
    for i in range(5):
        print(f"  nic_rail_{i}: {nic_counts[i]:4d}/{total_sfp} ({100*nic_counts[i]/total_sfp:.1f}%)")
    print("--- SC rail distribution ---")
    for i in range(2):
        print(f"  sc_rail_{i}:  {sc_counts[i]:4d}/{total_sc}  ({100*sc_counts[i]/total_sc:.1f}%)")


# ---------------------------------------------------------------------------
# Generation logic (separated from UI)
# ---------------------------------------------------------------------------

def run_train_separate(n_sfp: int, n_sc: int, base: dict, rng: random.Random, seed: int) -> str:
    """Generate train configs with separate SFP/SC counts. Returns result summary."""
    base_dir = DEFAULT_OUTPUT_BASE / "train"
    sfp_dir = base_dir / "sfp"
    sc_dir = base_dir / "sc"

    lines = [f"seed={seed}"]
    sfp_configs, sc_configs = [], []

    if n_sfp > 0:
        sfp_dir.mkdir(parents=True, exist_ok=True)
        sfp_offset = _next_offset(sfp_dir, "sfp")
        sfp_rows = []
        # Uniform cycle: 5 rails x 2 ports = 10 combinations
        for i in range(n_sfp):
            target_rail, port_name = SFP_TARGETS[i % len(SFP_TARGETS)]
            idx = sfp_offset + i
            filename = f"config_sfp_{idx:04d}.yaml"
            cfg = build_single_config(base, rng, "sfp",
                                      target_rail=target_rail, port_name=port_name)
            sfp_rows.append(_sfp_row(filename, seed, cfg))
            sfp_configs.append(cfg)
            with open(sfp_dir / filename, "w") as f:
                yaml.dump(cfg, f, Dumper=_get_dumper(), default_flow_style=False, sort_keys=False)
        append_to_excel(sfp_dir / "configs_log.xlsx", sfp_rows)
        lines.append(f"SFP: {n_sfp} configs -> {sfp_dir}/  (index {sfp_offset}~{sfp_offset + n_sfp - 1})")

    if n_sc > 0:
        sc_dir.mkdir(parents=True, exist_ok=True)
        sc_offset = _next_offset(sc_dir, "sc")
        sc_rows = []
        # Uniform cycle: 2 ports
        for i in range(n_sc):
            target_idx = SC_TARGETS[i % len(SC_TARGETS)]
            idx = sc_offset + i
            filename = f"config_sc_{idx:04d}.yaml"
            cfg = build_single_config(base, rng, "sc", target_idx=target_idx)
            sc_rows.append(_sc_row(filename, seed, cfg))
            sc_configs.append(cfg)
            with open(sc_dir / filename, "w") as f:
                yaml.dump(cfg, f, Dumper=_get_dumper(), default_flow_style=False, sort_keys=False)
        append_to_excel(sc_dir / "configs_log.xlsx", sc_rows)
        lines.append(f"SC:  {n_sc} configs -> {sc_dir}/  (index {sc_offset}~{sc_offset + n_sc - 1})")

    print_single_stats(sfp_configs, sc_configs)
    return "\n".join(lines)


def run_test(n: int, base: dict, rng: random.Random, seed: int) -> str:
    """Generate test configs. Returns result summary string."""
    output_dir = DEFAULT_OUTPUT_BASE / "test"
    output_dir.mkdir(parents=True, exist_ok=True)

    offset = _next_offset(output_dir, "test")
    configs = []
    excel_rows = []

    # Uniform cycle: trial_1 and trial_2 cycle SFP_TARGETS independently,
    # trial_3 cycles SC_TARGETS
    for i in range(n):
        idx = offset + i
        filename = f"config_test_{idx:04d}.yaml"
        sfp_t1 = SFP_TARGETS[i % len(SFP_TARGETS)]
        sfp_t2 = SFP_TARGETS[(i + len(SFP_TARGETS) // 2) % len(SFP_TARGETS)]  # offset by half
        sc_t = SC_TARGETS[i % len(SC_TARGETS)]
        cfg = build_full_config(base, rng, sfp_target_1=sfp_t1, sfp_target_2=sfp_t2, sc_target=sc_t)
        configs.append(cfg)
        excel_rows.append(_sfp_row(filename, seed, cfg, "trial_1"))
        excel_rows.append(_sfp_row(filename, seed, cfg, "trial_2"))
        excel_rows.append(_sc_row(filename, seed, cfg, "trial_3"))
        with open(output_dir / filename, "w") as f:
            yaml.dump(cfg, f, Dumper=_get_dumper(), default_flow_style=False, sort_keys=False)

    append_to_excel(output_dir / "configs_log.xlsx", excel_rows, use_trial_fill=True)

    lines = [
        f"Generated {n} test configs (seed={seed})",
        f"  3 trials each (SFP×2 + SC×1)",
        f"  -> {output_dir}/",
        f"     (index {offset} ~ {offset + n - 1})",
    ]
    return "\n".join(lines)


def get_existing_counts() -> dict[str, int]:
    """Count existing configs in each folder."""
    counts = {}
    for mode in ["train", "test"]:
        mode_dir = DEFAULT_OUTPUT_BASE / mode
        if mode == "train":
            for t in ["sfp", "sc"]:
                d = mode_dir / t
                if d.exists():
                    counts[f"train/{t}"] = len(list(d.glob(f"config_{t}_*.yaml")))
                else:
                    counts[f"train/{t}"] = 0
        else:
            if mode_dir.exists():
                counts["test"] = len(list(mode_dir.glob("config_test_*.yaml")))
            else:
                counts["test"] = 0
    return counts


def _scan_distribution(yaml_files: list[Path]) -> dict:
    """Scan yaml files and return detailed distribution data."""
    sfp_targets: dict[str, int] = {}   # "mount_X/port_Y" -> count
    sc_targets: dict[str, int] = {}    # "sc_port_X" -> count
    nic_rails: dict[int, int] = {i: 0 for i in range(5)}   # rail presence count
    sc_rails: dict[int, int] = {i: 0 for i in range(2)}
    n_sfp = 0
    n_sc = 0
    n_total = 0

    for yf in yaml_files:
        with open(yf) as f:
            cfg = yaml.safe_load(f)
        if not cfg or "trials" not in cfg:
            continue
        for _, trial in cfg["trials"].items():
            n_total += 1
            task = trial.get("tasks", {}).get("task_1", {})
            tb = trial.get("scene", {}).get("task_board", {})
            plug_type = task.get("plug_type", "")
            target_module = task.get("target_module_name", "?")
            port_name = task.get("port_name", "?")

            # Count rail presence
            for i in range(5):
                if tb.get(f"nic_rail_{i}", {}).get("entity_present", False):
                    nic_rails[i] += 1
            for i in range(2):
                if tb.get(f"sc_rail_{i}", {}).get("entity_present", False):
                    sc_rails[i] += 1

            if plug_type == "sfp":
                key = f"{target_module}/{port_name}"
                sfp_targets[key] = sfp_targets.get(key, 0) + 1
                n_sfp += 1
            elif plug_type == "sc":
                sc_targets[target_module] = sc_targets.get(target_module, 0) + 1
                n_sc += 1

    return {
        "sfp_targets": sfp_targets, "sc_targets": sc_targets,
        "nic_rails": nic_rails, "sc_rails": sc_rails,
        "n_sfp": n_sfp, "n_sc": n_sc, "n_total": n_total,
    }


def compute_distributions() -> tuple[dict, dict]:
    """Compute distributions for train and test. Returns (train_data, test_data)."""
    train_files: list[Path] = []
    train_dir = DEFAULT_OUTPUT_BASE / "train"
    if train_dir.exists():
        for t in ["sfp", "sc"]:
            d = train_dir / t
            if d.exists():
                train_files.extend(d.glob(f"config_{t}_*.yaml"))

    test_files: list[Path] = []
    test_dir = DEFAULT_OUTPUT_BASE / "test"
    if test_dir.exists():
        test_files.extend(test_dir.glob("config_test_*.yaml"))

    return _scan_distribution(train_files), _scan_distribution(test_files)


# ---------------------------------------------------------------------------
# CustomTkinter GUI
# ---------------------------------------------------------------------------

_BG = "#111116"
_CARD = "#1c1c24"
_CARD_BORDER = "#2a2a35"




class ConfigGeneratorApp:
    def __init__(self):
        ctk.set_appearance_mode("dark")

        self.root = ctk.CTk()
        self.root.title("AIC Scene Config Generator")
        self.root.configure(fg_color=_BG)

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        scale = screen_h / 1080.0

        ctk.set_widget_scaling(1.0)
        ctk.set_window_scaling(1.0)

        # Window: 80% x 80%
        win_w = int(screen_w * 0.8)
        win_h = int(screen_h * 0.8)
        x = (screen_w - win_w) // 2
        y = max(0, (screen_h - win_h) // 2 - 20)
        self.root.geometry(f"{win_w}x{win_h}+{x}+{y}")
        self.root.minsize(800, 600)

        self._scale = scale
        self._sz = max(11, int(12 * scale))
        self._sz_lg = max(13, int(14 * scale))
        self._sz_sm = max(9, int(10 * scale))
        self._pad = max(10, int(12 * scale))
        self._entry_w = max(80, int(100 * scale))
        self._btn_h = max(30, int(34 * scale))

        self._build_ui()
        self.root.after(100, self._refresh_status)

    def _card(self, parent) -> ctk.CTkFrame:
        return ctk.CTkFrame(parent, fg_color=_CARD, corner_radius=12,
                            border_width=1, border_color=_CARD_BORDER)

    def _title(self, parent, text: str):
        ctk.CTkLabel(parent, text=text,
                     font=ctk.CTkFont(size=self._sz_sm, weight="bold"),
                     text_color="#8b8fa3", anchor="w").pack(
            fill="x", padx=self._pad // 2, pady=(self._pad // 2, 4))

    def _build_ui(self):
        pad = self._pad
        hp = pad // 2
        font = ctk.CTkFont(size=self._sz)
        font_bold = ctk.CTkFont(size=self._sz, weight="bold")
        font_lg = ctk.CTkFont(size=self._sz_lg, weight="bold")
        font_mono = ctk.CTkFont(family="monospace", size=self._sz_sm)
        font_log = ctk.CTkFont(family="monospace", size=max(9, int(self._sz * 0.6)))

        main = ctk.CTkScrollableFrame(self.root, fg_color="transparent")
        main.pack(fill="both", expand=True)

        # ============ Row 1: Controls (Mode + Count + Buttons) ============
        ctrl_row = ctk.CTkFrame(main, fg_color="transparent")
        ctrl_row.pack(fill="x", padx=pad, pady=(pad, hp))
        ctrl_row.columnconfigure(0, weight=1)
        ctrl_row.columnconfigure(1, weight=1)
        ctrl_row.columnconfigure(2, weight=0)

        # Mode
        card_m = self._card(ctrl_row)
        card_m.grid(row=0, column=0, sticky="nsew", padx=(0, hp))
        self._title(card_m, "MODE")
        self.mode_var = ctk.StringVar(value="train")
        ctk.CTkRadioButton(card_m, text="train — 1 trial/config (sfp/sc separate)",
                           variable=self.mode_var, value="train", font=font,
                           fg_color="#3b82f6", hover_color="#2563eb",
                           command=self._on_mode_change).pack(anchor="w", padx=hp, pady=2)
        ctk.CTkRadioButton(card_m, text="test  — 3 trials (SFPx2+SCx1)",
                           variable=self.mode_var, value="test", font=font,
                           fg_color="#3b82f6", hover_color="#2563eb",
                           command=self._on_mode_change).pack(anchor="w", padx=hp, pady=(2, hp))

        # Count
        card_c = self._card(ctrl_row)
        card_c.grid(row=0, column=1, sticky="nsew", padx=(0, hp))
        self._title(card_c, "NUMBER OF CONFIGS")

        self.train_frame = ctk.CTkFrame(card_c, fg_color="transparent")
        self.train_frame.pack(fill="x", padx=hp, pady=(0, 2))
        ctk.CTkLabel(self.train_frame, text="SFP", font=font_bold,
                     text_color="#60a5fa").pack(side="left")
        self.n_sfp_var = ctk.StringVar(value="50")
        ctk.CTkEntry(self.train_frame, textvariable=self.n_sfp_var,
                     width=self._entry_w, font=font, corner_radius=8,
                     border_color="#3b82f6", border_width=2).pack(side="left", padx=(4, pad))
        ctk.CTkLabel(self.train_frame, text="SC", font=font_bold,
                     text_color="#fb923c").pack(side="left")
        self.n_sc_var = ctk.StringVar(value="20")
        ctk.CTkEntry(self.train_frame, textvariable=self.n_sc_var,
                     width=self._entry_w, font=font, corner_radius=8,
                     border_color="#fb923c", border_width=2).pack(side="left", padx=(4, 0))

        ctk.CTkLabel(card_c, text="* Recommended SFP:SC = 5:2 (10 SFP targets, 2 SC targets)",
                     font=ctk.CTkFont(size=max(8, self._sz_sm - 2)),
                     text_color="#6b7280", anchor="w").pack(fill="x", padx=hp, pady=(0, hp))

        self.test_frame = ctk.CTkFrame(card_c, fg_color="transparent")
        ctk.CTkLabel(self.test_frame, text="Configs", font=font_bold,
                     text_color="#a78bfa").pack(side="left")
        self.n_test_var = ctk.StringVar(value="20")
        ctk.CTkEntry(self.test_frame, textvariable=self.n_test_var,
                     width=self._entry_w, font=font, corner_radius=8,
                     border_color="#a78bfa", border_width=2).pack(side="left", padx=(4, 0))

        self._count_card = card_c

        # Buttons
        btn_frame = ctk.CTkFrame(ctrl_row, fg_color="transparent")
        btn_frame.grid(row=0, column=2, sticky="ns", padx=(0, 0))
        ctk.CTkButton(btn_frame, text="Generate", font=font_lg,
                      width=int(160 * self._scale), height=self._btn_h,
                      fg_color="#22c55e", hover_color="#16a34a",
                      corner_radius=10, command=self._generate).pack(pady=(hp, hp))
        ctk.CTkButton(btn_frame, text="Refresh", font=font,
                      width=int(120 * self._scale), height=self._btn_h,
                      fg_color="#374151", hover_color="#4b5563",
                      corner_radius=10, command=self._refresh_status).pack()

        # ============ Row 2: Status + Charts (Train | Test columns) ============
        dist_row = ctk.CTkFrame(main, fg_color="transparent")
        dist_row.pack(fill="both", expand=True, padx=pad, pady=(0, hp))
        dist_row.columnconfigure(0, weight=1)
        dist_row.columnconfigure(1, weight=1)

        # --- TRAIN column ---
        train_col = self._card(dist_row)
        train_col.grid(row=0, column=0, sticky="nsew", padx=(0, hp))
        self._title(train_col, "TRAIN")

        self.train_status = ctk.CTkLabel(train_col, text="", font=font_mono,
                                         anchor="w", justify="left", text_color="#86efac")
        self.train_status.pack(fill="x", padx=hp, pady=(0, 4))

        self.train_dist_label = ctk.CTkLabel(train_col, text="", font=font_mono,
                                              anchor="w", justify="left", text_color="#d1d5db")
        self.train_dist_label.pack(fill="both", expand=True, padx=hp, pady=(0, hp))

        # --- TEST column ---
        test_col = self._card(dist_row)
        test_col.grid(row=0, column=1, sticky="nsew", padx=(hp, 0))
        self._title(test_col, "TEST")

        self.test_status = ctk.CTkLabel(test_col, text="", font=font_mono,
                                        anchor="w", justify="left", text_color="#93c5fd")
        self.test_status.pack(fill="x", padx=hp, pady=(0, 4))

        self.test_dist_label = ctk.CTkLabel(test_col, text="", font=font_mono,
                                             anchor="w", justify="left", text_color="#d1d5db")
        self.test_dist_label.pack(fill="both", expand=True, padx=hp, pady=(0, hp))

        # ============ Row 3: Log ============
        log_card = self._card(main)
        log_card.pack(fill="x", padx=pad, pady=(0, hp))
        self._title(log_card, "OUTPUT LOG")
        self.log_text = ctk.CTkTextbox(log_card, font=font_log, state="disabled",
                                       wrap="word", corner_radius=6,
                                       fg_color="#0d0d10", text_color="#9ca3af",
                                       height=max(80, int(90 * self._scale)))
        self.log_text.pack(fill="both", expand=True, padx=hp, pady=(0, hp))

    def _on_mode_change(self):
        hp = self._pad // 2
        if self.mode_var.get() == "train":
            self.test_frame.pack_forget()
            self.train_frame.pack(fill="x", padx=hp, pady=(0, hp), in_=self._count_card)
        else:
            self.train_frame.pack_forget()
            self.test_frame.pack(fill="x", padx=hp, pady=(0, hp), in_=self._count_card)

    def _format_dist(self, data: dict) -> str:
        lines = []
        n_total = data["n_total"]
        if n_total == 0:
            return "No data"

        # Task Targets — percentage based on total tasks
        if data["sfp_targets"]:
            lines.append("Task Targets (SFP):")
            for k in sorted(data["sfp_targets"]):
                c = data["sfp_targets"][k]
                lines.append(f"  {k}: {c} ({100*c/n_total:.1f}%)")
        if data["sc_targets"]:
            lines.append("Task Targets (SC):")
            for k in sorted(data["sc_targets"]):
                c = data["sc_targets"][k]
                lines.append(f"  {k}: {c} ({100*c/n_total:.1f}%)")

        # Rail Presence
        lines.append("Rail Presence:")
        for i in range(5):
            c = data["nic_rails"][i]
            lines.append(f"  nic_rail_{i}: {c} ({100*c/n_total:.0f}%)")
        for i in range(2):
            c = data["sc_rails"][i]
            lines.append(f"  sc_rail_{i}:  {c} ({100*c/n_total:.0f}%)")

        return "\n".join(lines)

    def _refresh_status(self):
        train_data, test_data = compute_distributions()

        self.train_status.configure(
            text=f"SFP: {train_data['n_sfp']}  |  SC: {train_data['n_sc']}  |  Total: {train_data['n_total']}")
        self.train_dist_label.configure(text=self._format_dist(train_data))

        self.test_status.configure(
            text=f"SFP: {test_data['n_sfp']}  |  SC: {test_data['n_sc']}  |  Total: {test_data['n_total']}")
        self.test_dist_label.configure(text=self._format_dist(test_data))

    def _log(self, text: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _show_error(self, msg: str):
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Error")
        dialog.geometry("500x200")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(fg_color=_CARD)
        ctk.CTkLabel(dialog, text=msg, font=ctk.CTkFont(size=self._sz),
                     wraplength=440, text_color="#fca5a5").pack(expand=True, padx=20, pady=20)
        ctk.CTkButton(dialog, text="OK", command=dialog.destroy,
                      width=120, fg_color="#ef4444", hover_color="#dc2626").pack(pady=(0, 20))

    def _generate(self):
        mode = self.mode_var.get()
        try:
            base = load_base_config(DEFAULT_SAMPLE_PATH)
        except FileNotFoundError:
            self._show_error(f"sample_config.yaml not found:\n{DEFAULT_SAMPLE_PATH}")
            return

        seed = int.from_bytes(os.urandom(4), "big")
        rng = random.Random(seed)

        try:
            if mode == "train":
                n_sfp = int(self.n_sfp_var.get() or 0)
                n_sc = int(self.n_sc_var.get() or 0)
                if n_sfp + n_sc < 1:
                    self._show_error("Enter at least 1 for SFP or SC.")
                    return
                self._log(f"--- train (SFP={n_sfp}, SC={n_sc}) ---")
                result = run_train_separate(n_sfp, n_sc, base, rng, seed)
            else:
                n = int(self.n_test_var.get() or 0)
                if n < 1:
                    self._show_error("Enter at least 1.")
                    return
                self._log(f"--- test (n={n}) ---")
                result = run_test(n, base, rng, seed)

            self._log(result)
            self._log("")
            self._refresh_status()
        except Exception as e:
            self._log(f"ERROR: {e}")
            self._show_error(str(e))

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = ConfigGeneratorApp()
    app.run()
