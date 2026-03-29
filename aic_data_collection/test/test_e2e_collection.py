#!/usr/bin/env python3
"""End-to-end data collection test against live Gazebo simulation.

Requires: Gazebo simulation running (launched automatically via launch file).
Run with: pixi run bash -c "source install/setup.bash && python aic_data_collection/test/test_e2e_collection.py"
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time


def wait_for_process(proc, timeout_sec):
    """Wait for process to complete, return (stdout, stderr, returncode)."""
    try:
        stdout, stderr = proc.communicate(timeout=timeout_sec)
        return stdout, stderr, proc.returncode
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        return b"", b"TIMEOUT", -1


def run_collection(bag_dir, target_episodes, trial_mode="static", trials=None, timeout_sec=600):
    """Run the auto_data_collector node directly (sim must be running).

    Uses ros2 run if available, falls back to direct script execution.
    """
    config_file = os.environ.get("AIC_CONFIG", "")
    ros_args = [
        "--ros-args",
        "-p", f"config_file:={config_file}",
        "-p", f"target_episodes:={target_episodes}",
        "-p", f"max_attempts:={target_episodes * 3}",
        "-p", f"task_timeout_sec:=120.0",
        "-p", f"bag_output_dir:={bag_dir}",
        "-p", f"trial_mode:={trial_mode}",
        "-p", "use_sim_time:=true",
    ]
    if trials:
        trials_str = str(trials)
        ros_args.extend(["-p", f"trials:={trials_str}"])

    # Find executable: check isolated install bin/, then ros2 run fallback
    cmd = ["ros2", "run", "aic_data_collection", "auto_data_collector"] + ros_args
    for prefix in os.environ.get("AMENT_PREFIX_PATH", "").split(":"):
        candidate = os.path.join(prefix, "bin", "auto_data_collector")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            cmd = [candidate] + ros_args
            break

    print(f"\n{'='*60}")
    print(f"Running: {' '.join(cmd)}")
    print(f"{'='*60}\n")

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env={**os.environ}
    )
    stdout, stderr, rc = wait_for_process(proc, timeout_sec)
    output = stdout.decode("utf-8", errors="replace") if stdout else ""
    return output, rc


def count_bags(bag_dir, subdir=""):
    """Count bag directories (each episode creates one)."""
    path = os.path.join(bag_dir, subdir) if subdir else bag_dir
    if not os.path.exists(path):
        return 0
    return len([d for d in os.listdir(path)
                if os.path.isdir(os.path.join(path, d)) and d != "failed"])


def count_failed_bags(bag_dir):
    """Count failed bag directories."""
    failed_dir = os.path.join(bag_dir, "failed")
    if not os.path.exists(failed_dir):
        return 0
    return len([d for d in os.listdir(failed_dir)
                if os.path.isdir(os.path.join(failed_dir, d))])


def find_config():
    """Find sample_config.yaml from aic_engine package."""
    try:
        result = subprocess.run(
            ["ros2", "pkg", "prefix", "aic_engine"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            prefix = result.stdout.strip()
            config = os.path.join(prefix, "share", "aic_engine", "config", "sample_config.yaml")
            if os.path.exists(config):
                return config
    except Exception:
        pass
    return None


class E2EResult:
    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.failures = []

    def assert_true(self, condition, msg):
        self.tests_run += 1
        if condition:
            self.tests_passed += 1
            print(f"  PASS: {msg}")
        else:
            self.failures.append(msg)
            print(f"  FAIL: {msg}")

    def summary(self):
        print(f"\n{'='*60}")
        print(f"E2E Results: {self.tests_passed}/{self.tests_run} passed")
        if self.failures:
            print("Failures:")
            for f in self.failures:
                print(f"  - {f}")
        print(f"{'='*60}")
        return len(self.failures) == 0


def test_phase1_static_collection(config_path):
    """Phase 1: Static mode - collect 3 episodes, verify bags and trial transitions."""
    print("\n" + "="*60)
    print("TEST: Phase 1 - Static mode, 3 episodes")
    print("="*60)

    result = E2EResult()
    bag_dir = tempfile.mkdtemp(prefix="e2e_phase1_")

    try:
        os.environ["AIC_CONFIG"] = config_path
        output, rc = run_collection(
            bag_dir=bag_dir,
            target_episodes=3,
            trial_mode="static",
            timeout_sec=600,
        )

        print("\n--- Collector output (last 30 lines) ---")
        lines = output.strip().split("\n")
        for line in lines[-30:]:
            print(f"  {line}")

        # 1. Process completed
        result.assert_true(rc == 0, f"Collector exited cleanly (rc={rc})")

        # 2. Summary printed
        result.assert_true("Data Collection Summary" in output, "Summary printed at exit")

        # 3. Target reached
        result.assert_true("target reached" in output, "Target episodes reached")

        # 4. At least 3 successful bags
        success_count = count_bags(bag_dir)
        result.assert_true(success_count >= 3, f"3+ successful bags created (got {success_count})")

        # 5. Check trial transition in output (trial_1 and trial_2 should appear)
        result.assert_true("trial_1" in output, "trial_1 appeared in output")
        result.assert_true("trial_2" in output, "trial_2 appeared in output (round-robin)")

        # 6. Homing occurred (check for homing log messages)
        home_count = output.count("homed successfully") + output.count("Homing")
        result.assert_true(home_count >= 2, f"Robot homing occurred between episodes (mentions={home_count})")

        # 7. Rosbag files exist and are non-empty
        if success_count > 0:
            first_bag = None
            for d in sorted(os.listdir(bag_dir)):
                bag_path = os.path.join(bag_dir, d)
                if os.path.isdir(bag_path) and d != "failed":
                    first_bag = bag_path
                    break
            if first_bag:
                bag_files = os.listdir(first_bag)
                result.assert_true(len(bag_files) > 0, f"Bag directory non-empty: {bag_files[:3]}")
            else:
                result.assert_true(False, "No bag directory found")
        else:
            result.assert_true(False, "No bags to verify")

    finally:
        shutil.rmtree(bag_dir, ignore_errors=True)

    return result


def test_phase2_dynamic_collection(config_path):
    """Phase 2: Dynamic mode - collect 3 episodes with randomized trials."""
    print("\n" + "="*60)
    print("TEST: Phase 2 - Dynamic mode, 3 episodes")
    print("="*60)

    result = E2EResult()
    bag_dir = tempfile.mkdtemp(prefix="e2e_phase2_")

    try:
        os.environ["AIC_CONFIG"] = config_path
        output, rc = run_collection(
            bag_dir=bag_dir,
            target_episodes=3,
            trial_mode="dynamic",
            trials=["trial_1"],
            timeout_sec=600,
        )

        print("\n--- Collector output (last 30 lines) ---")
        lines = output.strip().split("\n")
        for line in lines[-30:]:
            print(f"  {line}")

        # 1. Process completed
        result.assert_true(rc == 0, f"Collector exited cleanly (rc={rc})")

        # 2. Summary printed
        result.assert_true("Data Collection Summary" in output, "Summary printed at exit")

        # 3. Target reached
        result.assert_true("target reached" in output, "Target episodes reached")

        # 4. At least 3 successful bags
        success_count = count_bags(bag_dir)
        result.assert_true(success_count >= 3, f"3+ successful bags created (got {success_count})")

        # 5. Dynamic trial IDs used
        result.assert_true("dynamic_" in output, "Dynamic trial IDs appear in output")

        # 6. Homing occurred
        home_count = output.count("homed successfully") + output.count("Homing")
        result.assert_true(home_count >= 2, f"Robot homing occurred between episodes (mentions={home_count})")

        # 7. Bags non-empty
        if success_count > 0:
            first_bag = None
            for d in sorted(os.listdir(bag_dir)):
                bag_path = os.path.join(bag_dir, d)
                if os.path.isdir(bag_path) and d != "failed":
                    first_bag = bag_path
                    break
            if first_bag:
                bag_files = os.listdir(first_bag)
                result.assert_true(len(bag_files) > 0, f"Bag directory non-empty: {bag_files[:3]}")
            else:
                result.assert_true(False, "No bag directory found")
        else:
            result.assert_true(False, "No bags to verify")

    finally:
        shutil.rmtree(bag_dir, ignore_errors=True)

    return result


def main():
    print("="*60)
    print("Auto Data Collection - End-to-End Verification")
    print("="*60)

    # Find config
    config_path = find_config()
    if not config_path:
        print("ERROR: Cannot find sample_config.yaml. Is aic_engine built?")
        sys.exit(1)
    print(f"Config: {config_path}")

    # Run tests
    results = []
    results.append(("Phase 1 (Static)", test_phase1_static_collection(config_path)))
    results.append(("Phase 2 (Dynamic)", test_phase2_dynamic_collection(config_path)))

    # Final summary
    print("\n" + "="*60)
    print("FINAL SUMMARY")
    print("="*60)
    all_pass = True
    for name, r in results:
        status = "PASS" if r.summary() else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"  {name}: {r.tests_passed}/{r.tests_run} {status}")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
