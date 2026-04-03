#!/usr/bin/env bash
# Benchmark runner: executes all 5 configs against a given policy
# Usage: ./benchmark/scripts/run_benchmark.sh <policy_module> [--ground-truth]
#
# Prerequisites:
#   - aic_eval docker container running in tmux session autocode:sim
#   - Gazebo fully loaded
#   - pixi environment set up

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCHMARK_DIR="$(dirname "$SCRIPT_DIR")"
SRC_DIR="$(dirname "$BENCHMARK_DIR")"
WS_DIR="$(dirname "$SRC_DIR")"
CONFIGS_DIR="${BENCHMARK_DIR}/configs"
RESULTS_DIR="${BENCHMARK_DIR}/results"
LOG_DIR="${BENCHMARK_DIR}/logs"
SCORING_FILE="${HOME}/aic_results/scoring.yaml"
CONTAINER_NAME="aic_eval"
TIMEOUT_PER_CONFIG=300

# Parse arguments
POLICY_MODULE=""
GROUND_TRUTH="false"

for arg in "$@"; do
    case "$arg" in
        --ground-truth)
            GROUND_TRUTH="true"
            ;;
        *)
            if [ -z "$POLICY_MODULE" ]; then
                POLICY_MODULE="$arg"
            fi
            ;;
    esac
done

if [ -z "$POLICY_MODULE" ]; then
    echo "Usage: $0 <policy_module> [--ground-truth]" >&2
    echo "  e.g.: $0 aic_example_policies.ros.CheatCode --ground-truth" >&2
    echo "  e.g.: $0 aic_example_policies.ros.MyPolicy" >&2
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

# Step 1: Build policy package
echo "Building policy package..." >&2
cd "$SRC_DIR"
pixi run colcon build --packages-select aic_example_policies 2>&1 | tail -5 >&2

# Step 2: Sync to pixi env cache
COLCON_POLICY_DIR="${WS_DIR}/install/lib/python3.12/site-packages/aic_example_policies"
PIXI_POLICY_DIR="${SRC_DIR}/.pixi/envs/default/lib/python3.12/site-packages/aic_example_policies"
if [ -d "$COLCON_POLICY_DIR" ] && [ -d "$PIXI_POLICY_DIR" ]; then
    cp -r "${COLCON_POLICY_DIR}/ros/" "${PIXI_POLICY_DIR}/ros/" 2>/dev/null || true
    echo "Synced policy to pixi env" >&2
fi

# Step 3: Run each config
config_idx=0
for config_file in "${CONFIGS_DIR}"/benchmark_*.yaml; do
    config_idx=$((config_idx + 1))
    config_name="$(basename "$config_file" .yaml)"
    echo "" >&2
    echo "=== Config ${config_idx}/5: ${config_name} ===" >&2

    # Kill leftover processes
    pkill -f "aic_model aic_model" 2>/dev/null || true
    pkill -f "ros2 run aic_engine" 2>/dev/null || true
    sleep 15

    # Restart simulation
    echo "  Restarting simulation (ground_truth=${GROUND_TRUTH})..." >&2
    tmux send-keys -t autocode:sim C-c 2>/dev/null || true
    sleep 5
    tmux send-keys -t autocode:sim "/entrypoint.sh ground_truth:=${GROUND_TRUTH} start_aic_engine:=false" Enter 2>/dev/null || true
    sleep 50
    echo "  Simulation ready." >&2

    # Clear previous scoring result
    rm -f "$SCORING_FILE"
    docker exec "$CONTAINER_NAME" bash -c "rm -rf ${HOME}/aic_results/bag_*" 2>/dev/null || true

    # Start policy on host
    bash -c "
        cd ${SRC_DIR}
        source ${WS_DIR}/install/setup.bash
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
        export ROS_DOMAIN_ID=30
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
    wait "$POLICY_PID" 2>/dev/null || true
    wait "$ENGINE_PID" 2>/dev/null || true

    # Copy results
    if [ -f "$SCORING_FILE" ]; then
        cp "$SCORING_FILE" "${POLICY_RESULTS_DIR}/${config_name}_scoring.yaml"
        score=$(python3 -c "
import yaml
with open('${SCORING_FILE}') as f:
    data = yaml.safe_load(f)
print(float(data.get('total', 0)) if data else 0)
")
        echo "  Config score: ${score}" >&2
    else
        echo "  TIMEOUT - no scoring.yaml after ${TIMEOUT_PER_CONFIG}s" >&2
        echo "total: 0" > "${POLICY_RESULTS_DIR}/${config_name}_scoring.yaml"
    fi
done

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
