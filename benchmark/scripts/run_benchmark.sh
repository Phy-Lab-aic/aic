#!/usr/bin/env bash
# Benchmark runner: executes all 5 configs against a given policy
# Usage: ./benchmark/scripts/run_benchmark.sh <policy_module> [--ground-truth] [--skip-build]
#
# Runs from HOST. Uses distrobox for simulation/engine, pixi for policy.
# Prerequisites:
#   - aic_eval distrobox container available
#   - pixi environment set up

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCHMARK_DIR="$(dirname "$SCRIPT_DIR")"
SRC_DIR="$(dirname "$BENCHMARK_DIR")"
WS_DIR="$(dirname "$(dirname "$SRC_DIR")")"
CONFIGS_DIR="${BENCHMARK_DIR}/configs"
RESULTS_DIR="${BENCHMARK_DIR}/results"
LOG_DIR="${BENCHMARK_DIR}/logs"
SCORING_FILE="${HOME}/aic_results/scoring.yaml"
CONTAINER_NAME="aic_eval"
TIMEOUT_PER_CONFIG=300
MAX_RETRIES=5

# Parse arguments
POLICY_MODULE=""
GROUND_TRUTH="false"
SKIP_BUILD="false"

for arg in "$@"; do
    case "$arg" in
        --ground-truth)
            GROUND_TRUTH="true"
            ;;
        --skip-build)
            SKIP_BUILD="true"
            ;;
        *)
            if [ -z "$POLICY_MODULE" ]; then
                POLICY_MODULE="$arg"
            fi
            ;;
    esac
done

if [ -z "$POLICY_MODULE" ]; then
    echo "Usage: $0 <policy_module> [--ground-truth] [--skip-build]" >&2
    echo "  e.g.: $0 aic_example_policies.ros.CheatCode --ground-truth" >&2
    echo "  e.g.: $0 aic_example_policies.ros.MyPolicy --skip-build" >&2
    exit 1
fi

# Extract class name for results directory
CLASS_NAME="${POLICY_MODULE##*.}"
POLICY_RESULTS_DIR="${RESULTS_DIR}/${CLASS_NAME}"

mkdir -p "$POLICY_RESULTS_DIR" "$LOG_DIR"

echo "=== Benchmark Runner ===" >&2
echo "Policy: ${POLICY_MODULE} (${CLASS_NAME})" >&2
echo "Ground truth: ${GROUND_TRUTH}" >&2
echo "Configs dir: ${CONFIGS_DIR}" >&2
echo "Results dir: ${POLICY_RESULTS_DIR}" >&2
echo "" >&2

# Helper: run command inside container
run_in_container() {
    docker exec "$CONTAINER_NAME" bash -c "$1"
}

# Step 1: Build policy package
if [ "$SKIP_BUILD" = "true" ]; then
    echo "Skipping build (--skip-build)" >&2
else
    echo "Building policy package..." >&2
    cd "$SRC_DIR"
    pixi run colcon build --packages-select aic_example_policies 2>&1 | tail -5 >&2
    # Sync to pixi env cache
    COLCON_POLICY_DIR="${WS_DIR}/install/lib/python3.12/site-packages/aic_example_policies"
    PIXI_POLICY_DIR="${SRC_DIR}/.pixi/envs/default/lib/python3.12/site-packages/aic_example_policies"
    if [ -d "$COLCON_POLICY_DIR" ] && [ -d "$PIXI_POLICY_DIR" ]; then
        cp -r "${COLCON_POLICY_DIR}/ros/" "${PIXI_POLICY_DIR}/ros/" 2>/dev/null || true
        echo "Synced policy to pixi env" >&2
    fi
fi

# Step 2: Run each config
config_idx=0
for config_file in "${CONFIGS_DIR}"/benchmark_*.yaml; do
    config_idx=$((config_idx + 1))
    config_name="$(basename "$config_file" .yaml)"
    echo "" >&2
    echo "=== Config ${config_idx}/5: ${config_name} ===" >&2

    attempt=0
    config_success="false"
    while [ "$config_success" = "false" ] && [ "$attempt" -lt "$MAX_RETRIES" ]; do
    attempt=$((attempt + 1))
    if [ "$attempt" -gt 1 ]; then
        echo "  Retry ${attempt}/${MAX_RETRIES}..." >&2
    fi

    # Kill leftover processes (host + container) for clean state
    pkill -f "aic_model aic_model" 2>/dev/null || true
    pkill -f "ros2 run aic_engine" 2>/dev/null || true
    pkill -f "rmw_zenohd" 2>/dev/null || true
    pkill -f "entrypoint.sh" 2>/dev/null || true
    sudo pkill -f "rmw_zenohd" 2>/dev/null || true
    docker restart "$CONTAINER_NAME" &>/dev/null || true
    sleep 5

    # Start simulation (headless, background)
    echo "  Starting simulation (ground_truth=${GROUND_TRUTH})..." >&2
    docker exec "$CONTAINER_NAME" /entrypoint.sh \
        ground_truth:="${GROUND_TRUTH}" \
        start_aic_engine:=false \
        &>"${LOG_DIR}/${config_name}_sim.log" &
    SIM_PID=$!

    # Wait for clock topic
    echo "  Waiting for simulation (clock topic)..." >&2
    sim_wait=0
    sim_ready="false"
    while [ "$sim_ready" = "false" ] && [ "$sim_wait" -lt 120 ]; do
        sleep 5
        sim_wait=$((sim_wait + 5))
        if run_in_container "source /ws_aic/install/setup.bash 2>/dev/null && export RMW_IMPLEMENTATION=rmw_zenoh_cpp && export ZENOH_CONFIG_OVERRIDE=';transport/shared_memory/enabled=false' && export ZENOH_ROUTER_CONFIG_URI=/aic_zenoh_config.json5 && ros2 daemon stop 2>/dev/null; ros2 topic echo /clock --once --spin-time 3" &>/dev/null; then
            sim_ready="true"
        fi
        if (( sim_wait % 30 == 0 )) && [ "$sim_ready" = "false" ]; then
            echo "  Still waiting for clock... ${sim_wait}s" >&2
        fi
    done

    if [ "$sim_ready" = "false" ]; then
        echo "  Simulation not ready after 120s, retrying..." >&2
        kill "$SIM_PID" 2>/dev/null || true
        wait "$SIM_PID" 2>/dev/null || true
        continue
    fi
    echo "  Simulation ready (clock detected after ${sim_wait}s)." >&2

    # Clear previous scoring result
    rm -f "$SCORING_FILE"
    rm -rf "${HOME}/aic_results/bag_"* 2>/dev/null || true

    # Start policy on host via pixi (has compatible Python dependencies)
    # Must connect to the container's Zenoh router with matching ROS_DOMAIN_ID
    RMW_IMPLEMENTATION=rmw_zenoh_cpp pixi run ros2 daemon stop &>/dev/null || true
    bash -c "
        cd ${SRC_DIR}
        source ${WS_DIR}/install/setup.bash
        export RMW_IMPLEMENTATION=rmw_zenoh_cpp
        export ZENOH_SESSION_CONFIG_URI=${BENCHMARK_DIR}/configs/zenoh_session_config.json5
        export ROS_DOMAIN_ID=0
        pixi run ros2 run aic_model aic_model --ros-args \
            -p use_sim_time:=true \
            -p policy:=${POLICY_MODULE}
    " &>"${LOG_DIR}/${config_name}_policy.log" &
    POLICY_PID=$!

    sleep 10

    # Start aic_engine inside container
    docker exec "$CONTAINER_NAME" bash -c "
        source /ws_aic/install/setup.bash
        export RMW_IMPLEMENTATION=rmw_zenoh_cpp
        export ZENOH_CONFIG_OVERRIDE=';transport/shared_memory/enabled=false'
        export ZENOH_ROUTER_CONFIG_URI=/aic_zenoh_config.json5
        ros2 run aic_engine aic_engine --ros-args \
            -p config_file_path:=${config_file} \
            -p ground_truth:=${GROUND_TRUTH} \
            -p use_sim_time:=true
    " &>"${LOG_DIR}/${config_name}_engine.log" &
    ENGINE_PID=$!

    # Wait for scoring.yaml
    elapsed=0
    while [ ! -f "$SCORING_FILE" ] && [ "$elapsed" -lt "$TIMEOUT_PER_CONFIG" ]; do
        sleep 5
        elapsed=$((elapsed + 5))
        if (( elapsed % 60 == 0 )); then
            echo "  Waiting... ${elapsed}s elapsed" >&2
        fi
    done
    sleep 2

    # Cleanup processes
    kill "$POLICY_PID" 2>/dev/null || true
    kill "$ENGINE_PID" 2>/dev/null || true
    kill "$SIM_PID" 2>/dev/null || true
    wait "$POLICY_PID" 2>/dev/null || true
    wait "$ENGINE_PID" 2>/dev/null || true
    wait "$SIM_PID" 2>/dev/null || true

    # Copy results and display score table
    if [ -f "$SCORING_FILE" ]; then
        config_success="true"
        cp "$SCORING_FILE" "${POLICY_RESULTS_DIR}/${config_name}_scoring.yaml"
        python3 -c "
import yaml, sys
with open('${SCORING_FILE}') as f:
    data = yaml.safe_load(f)
if not data:
    print('  No scoring data', file=sys.stderr)
    sys.exit(0)
trials = sorted([k for k in data if k.startswith('trial_')])
print('', file=sys.stderr)
print('  ┌─────────┬────────┬────────┬────────┬────────┐', file=sys.stderr)
print('  │  Trial  │ Tier 1 │ Tier 2 │ Tier 3 │ Total  │', file=sys.stderr)
print('  ├─────────┼────────┼────────┼────────┼────────┤', file=sys.stderr)
grand_total = 0
for t in trials:
    td = data[t]
    t1 = float(td.get('tier_1', {}).get('score', 0))
    t2 = float(td.get('tier_2', {}).get('score', 0))
    t3 = float(td.get('tier_3', {}).get('score', 0))
    total = t1 + t2 + t3
    grand_total += total
    name = t.replace('_', ' ').title()
    print(f'  │ {name:>7} │ {t1:6.2f} │ {t2:6.2f} │ {t3:6.2f} │ {total:6.2f} │', file=sys.stderr)
print('  ├─────────┼────────┼────────┼────────┼────────┤', file=sys.stderr)
avg = grand_total / len(trials) if trials else 0
print(f'  │ Average │        │        │        │ {avg:6.2f} │', file=sys.stderr)
print('  └─────────┴────────┴────────┴────────┴────────┘', file=sys.stderr)
" 2>&2
    else
        echo "  TIMEOUT (attempt ${attempt}/${MAX_RETRIES}) - no scoring.yaml after ${TIMEOUT_PER_CONFIG}s" >&2
    fi

    done  # end retry loop

    if [ "$config_success" = "false" ]; then
        echo "  FAILED after ${MAX_RETRIES} attempts" >&2
        echo "total: 0" > "${POLICY_RESULTS_DIR}/${config_name}_scoring.yaml"
    fi
done

# Step 3: Final summary table
echo "" >&2
echo "=== Final Summary ===" >&2
python3 -c "
import yaml, sys, os
results_dir = '${POLICY_RESULTS_DIR}'
configs = sorted([f for f in os.listdir(results_dir) if f.endswith('_scoring.yaml')])
print('', file=sys.stderr)
print('  ┌──────────────────────────────────┬────────┐', file=sys.stderr)
print('  │ Config                           │  Score │', file=sys.stderr)
print('  ├──────────────────────────────────┼────────┤', file=sys.stderr)
total = 0
count = 0
for cfg in configs:
    path = os.path.join(results_dir, cfg)
    with open(path) as f:
        data = yaml.safe_load(f)
    if not data:
        score = 0.0
    else:
        trials = [k for k in data if k.startswith('trial_')]
        score = 0.0
        for t in trials:
            td = data[t]
            score += float(td.get('tier_1', {}).get('score', 0))
            score += float(td.get('tier_2', {}).get('score', 0))
            score += float(td.get('tier_3', {}).get('score', 0))
        score = score / len(trials) if trials else float(data.get('total', 0))
    name = cfg.replace('_scoring.yaml', '').replace('benchmark_', '')
    print(f'  │ {name:<32} │ {score:6.2f} │', file=sys.stderr)
    total += score
    count += 1
print('  ├──────────────────────────────────┼────────┤', file=sys.stderr)
avg = total / count if count else 0
print(f'  │ {\"OVERALL AVERAGE\":>32} │ {avg:6.2f} │', file=sys.stderr)
print('  └──────────────────────────────────┴────────┘', file=sys.stderr)
" 2>&2

# Step 4: Collect scores and update leaderboard
echo "" >&2
echo "=== Collecting scores ===" >&2
BRANCH="$(git -C "$SRC_DIR" branch --show-current 2>/dev/null || echo 'unknown')"
python3 "${SCRIPT_DIR}/collect_scores.py" "$POLICY_MODULE" --branch "$BRANCH"

echo "" >&2
echo "=== Benchmark complete ===" >&2
echo "Results: ${POLICY_RESULTS_DIR}/" >&2
echo "Leaderboard: ${BENCHMARK_DIR}/leaderboard.yaml" >&2
echo "Markdown: ${BENCHMARK_DIR}/LEADERBOARD.md" >&2
