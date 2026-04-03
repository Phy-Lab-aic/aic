#!/usr/bin/env python3
"""Tests for collect_scores.py"""
import os
import tempfile
import yaml
import pytest
from pathlib import Path

import sys
sys.path.insert(0, os.path.dirname(__file__))
from collect_scores import (
    parse_scoring_yaml,
    compute_averages,
    update_leaderboard,
    generate_markdown,
    extract_class_name,
)


def test_extract_class_name():
    assert extract_class_name("aic_example_policies.ros.CheatCode") == "CheatCode"
    assert extract_class_name("my_pkg.ros.MyPolicy") == "MyPolicy"
    assert extract_class_name("SimplePolicy") == "SimplePolicy"


def test_parse_scoring_yaml_valid():
    data = {
        "total": 85.5,
        "trial_1": {
            "tier_1": {"score": 1.0, "message": "ok"},
            "tier_2": {"score": 20.0, "message": "ok"},
            "tier_3": {"score": 30.0, "message": "ok"},
        },
        "trial_2": {
            "tier_1": {"score": 1.0, "message": "ok"},
            "tier_2": {"score": 15.0, "message": "ok"},
            "tier_3": {"score": 18.5, "message": "ok"},
        },
        "trial_3": {
            "tier_1": {"score": 1.0, "message": "ok"},
            "tier_2": {"score": 18.0, "message": "ok"},
            "tier_3": {"score": 50.0, "message": "ok"},
        },
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        path = f.name
    try:
        trials = parse_scoring_yaml(path)
        assert len(trials) == 3
        assert trials[0]["tier1"] == 1.0
        assert trials[0]["tier2"] == 20.0
        assert trials[0]["tier3"] == 30.0
        assert trials[0]["total"] == 51.0
    finally:
        os.unlink(path)


def test_parse_scoring_yaml_missing_file():
    trials = parse_scoring_yaml("/nonexistent/path.yaml")
    assert trials == []


def test_compute_averages():
    trials = [
        {"tier1": 1.0, "tier2": 20.0, "tier3": 60.0, "total": 81.0},
        {"tier1": 1.0, "tier2": 15.0, "tier3": 50.0, "total": 66.0},
        {"tier1": 0.0, "tier2": 10.0, "tier3": 70.0, "total": 80.0},
    ]
    avg = compute_averages(trials)
    assert avg["trials_completed"] == 3
    assert abs(avg["avg_score"] - 75.67) < 0.01
    assert abs(avg["tier1_avg"] - 0.67) < 0.01
    assert abs(avg["tier2_avg"] - 15.0) < 0.01
    assert abs(avg["tier3_avg"] - 60.0) < 0.01
    assert avg["min_score"] == 66.0
    assert avg["max_score"] == 81.0


def test_compute_averages_empty():
    avg = compute_averages([])
    assert avg["avg_score"] == 0.0
    assert avg["trials_completed"] == 0


def test_update_leaderboard_new_entry():
    with tempfile.TemporaryDirectory() as tmpdir:
        lb_path = os.path.join(tmpdir, "leaderboard.yaml")
        entry = {
            "policy": "pkg.ros.TestPolicy",
            "avg_score": 80.0,
            "tier1_avg": 1.0,
            "tier2_avg": 19.0,
            "tier3_avg": 60.0,
            "min_score": 70.0,
            "max_score": 90.0,
            "date": "2026-04-04",
            "branch": "test-branch",
            "trials_completed": 15,
            "trials_total": 15,
        }
        update_leaderboard(lb_path, entry)
        with open(lb_path) as f:
            lb = yaml.safe_load(f)
        assert len(lb["entries"]) == 1
        assert lb["entries"][0]["policy"] == "pkg.ros.TestPolicy"


def test_update_leaderboard_replaces_existing():
    with tempfile.TemporaryDirectory() as tmpdir:
        lb_path = os.path.join(tmpdir, "leaderboard.yaml")
        entry1 = {
            "policy": "pkg.ros.TestPolicy",
            "avg_score": 80.0,
            "tier1_avg": 1.0,
            "tier2_avg": 19.0,
            "tier3_avg": 60.0,
            "min_score": 70.0,
            "max_score": 90.0,
            "date": "2026-04-04",
            "branch": "branch-1",
            "trials_completed": 15,
            "trials_total": 15,
        }
        entry2 = {**entry1, "avg_score": 90.0, "branch": "branch-2"}
        update_leaderboard(lb_path, entry1)
        update_leaderboard(lb_path, entry2)
        with open(lb_path) as f:
            lb = yaml.safe_load(f)
        assert len(lb["entries"]) == 1
        assert lb["entries"][0]["avg_score"] == 90.0
        assert lb["entries"][0]["branch"] == "branch-2"


def test_generate_markdown():
    lb = {
        "baseline_score": 85.0,
        "entries": [
            {
                "policy": "pkg.ros.CheatCode",
                "avg_score": 85.0,
                "tier1_avg": 1.0,
                "tier2_avg": 19.0,
                "tier3_avg": 65.0,
                "min_score": 70.0,
                "max_score": 95.0,
                "date": "2026-04-04",
                "branch": "main",
                "trials_completed": 15,
                "trials_total": 15,
            }
        ],
    }
    md = generate_markdown(lb)
    assert "# Cheatcode Benchmark Leaderboard" in md
    assert "| 1 |" in md
    assert "CheatCode" in md
    assert "85.0" in md
