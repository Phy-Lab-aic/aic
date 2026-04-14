#!/usr/bin/env bash
# Tuning runner: 4개 config 순차 실행 + scoring 파싱
# Usage: ./research/scripts/run_tune.sh <experiment_name>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESEARCH_DIR="$(dirname "$SCRIPT_DIR")"
SRC_DIR="$(dirname "$RESEARCH_DIR")"
WS_DIR="$(dirname "$(dirname "$SRC_DIR")")"
CONFIGS_DIR="${RESEARCH_DIR}/configs"
SCORING_FILE="${HOME}/aic_results/scoring.yaml"
CONTAINER_NAME="aic_eval"
TIMEOUT_PER_CONFIG=120
POLICY_MODULE="aic_example_policies.ros.OptimalPolicy"

EXPERIMENT_NAME="${1:-exp}"
RESULTS_DIR="${RESEARCH_DIR}/results/${EXPERIMENT_NAME}"
LOG_DIR="${RESEARCH_DIR}/logs/${EXPERIMENT_NAME}"

SIM_PID=""
POLICY_PID=""
ENGINE_PID=""

cleanup_procs() {
    [ -n "$POLICY_PID" ] && kill "$POLICY_PID" 2>/dev/null || true
    [ -n "$ENGINE_PID" ] && kill "$ENGINE_PID" 2>/dev/null || true
    [ -n "$SIM_PID" ] && kill "$SIM_PID" 2>/dev/null || true
    wait "$POLICY_PID" 2>/dev/null || true
    wait "$ENGINE_PID" 2>/dev/null || true
    wait "$SIM_PID" 2>/dev/null || true
    pkill -f "ros2 run aic_model" 2>/dev/null || true
    pkill -f "ros2 run aic_engine" 2>/dev/null || true
    POLICY_PID=""
    ENGINE_PID=""
    SIM_PID=""
}

cleanup() {
    cleanup_procs
    docker restart "$CONTAINER_NAME" &>/dev/null || true
    echo "Cleanup done." >&2
}
trap cleanup EXIT INT TERM

mkdir -p "$RESULTS_DIR" "$LOG_DIR"

# NOTE: Run 'pixi reinstall' BEFORE this script
echo "Using pre-installed policy" >&2

echo "=== Tune: ${EXPERIMENT_NAME} ===" >&2

# Collect configs
CONFIG_FILES=()
for f in "${CONFIGS_DIR}"/sfp_tune_*.yaml; do
    [ -f "$f" ] && CONFIG_FILES+=("$f")
done
TOTAL=${#CONFIG_FILES[@]}
echo "Configs: ${TOTAL}" >&2

ALL_RESULTS="[]"
config_idx=0

for config_file in "${CONFIG_FILES[@]}"; do
    config_idx=$((config_idx + 1))
    config_name="$(basename "$config_file" .yaml)"
    echo "" >&2
    echo "--- Config ${config_idx}/${TOTAL}: ${config_name} ---" >&2

    # Kill leftover + restart container
    cleanup_procs
    pkill -9 -f "aic_model" 2>/dev/null || true
    pkill -f "rmw_zenohd" 2>/dev/null || true
    pkill -f "entrypoint.sh" 2>/dev/null || true
    sudo pkill -f "rmw_zenohd" 2>/dev/null || true
    docker restart "$CONTAINER_NAME" &>/dev/null || true
    sleep 5

    # Start simulation
    docker exec "$CONTAINER_NAME" /entrypoint.sh \
        ground_truth:=true start_aic_engine:=false \
        gazebo_gui:=false launch_rviz:=false \
        &>"${LOG_DIR}/${config_name}_sim.log" &
    SIM_PID=$!

    # Wait for clock
    sim_wait=0
    sim_ready="false"
    while [ "$sim_ready" = "false" ] && [ "$sim_wait" -lt 120 ]; do
        sleep 5
        sim_wait=$((sim_wait + 5))
        if docker exec "$CONTAINER_NAME" bash -c \
            "source /ws_aic/install/setup.bash 2>/dev/null && export RMW_IMPLEMENTATION=rmw_zenoh_cpp && export ZENOH_CONFIG_OVERRIDE=';transport/shared_memory/enabled=false' && export ZENOH_ROUTER_CONFIG_URI=/aic_zenoh_config.json5 && ros2 daemon stop 2>/dev/null; ros2 topic echo /clock --once --spin-time 3" &>/dev/null; then
            sim_ready="true"
        fi
    done
    if [ "$sim_ready" = "false" ]; then
        echo "  Sim not ready, skip" >&2
        continue
    fi
    echo "  Sim ready (${sim_wait}s)" >&2

    rm -f "$SCORING_FILE"

    # Start policy
    RMW_IMPLEMENTATION=rmw_zenoh_cpp pixi run ros2 daemon stop &>/dev/null || true
    bash -c "
        cd ${SRC_DIR}
        source ${WS_DIR}/install/setup.bash 2>/dev/null || true
        export RMW_IMPLEMENTATION=rmw_zenoh_cpp
        export ZENOH_SESSION_CONFIG_URI=${SRC_DIR}/benchmark/configs/zenoh_session_config.json5
        export ROS_DOMAIN_ID=0
        pixi run ros2 run aic_model aic_model --ros-args \
            -p use_sim_time:=true \
            -p policy:=${POLICY_MODULE}
    " &>"${LOG_DIR}/${config_name}_policy.log" &
    POLICY_PID=$!

    sleep 10

    # Start engine
    docker exec "$CONTAINER_NAME" bash -c "
        source /ws_aic/install/setup.bash
        export RMW_IMPLEMENTATION=rmw_zenoh_cpp
        export ZENOH_CONFIG_OVERRIDE=';transport/shared_memory/enabled=false'
        export ZENOH_ROUTER_CONFIG_URI=/aic_zenoh_config.json5
        ros2 run aic_engine aic_engine --ros-args \
            -p config_file_path:=${config_file} \
            -p ground_truth:=true \
            -p use_sim_time:=true
    " &>"${LOG_DIR}/${config_name}_engine.log" &
    ENGINE_PID=$!

    # Wait for scoring
    elapsed=0
    while [ ! -f "$SCORING_FILE" ] && [ "$elapsed" -lt "$TIMEOUT_PER_CONFIG" ]; do
        sleep 3
        elapsed=$((elapsed + 3))
    done
    sleep 2

    # Parse result
    if [ -f "$SCORING_FILE" ]; then
        cp "$SCORING_FILE" "${RESULTS_DIR}/${config_name}_scoring.yaml"
        RESULT=$(python3 -c "
import yaml, json
with open('${SCORING_FILE}') as f:
    data = yaml.safe_load(f)
td = data.get('trial_1', {})
t1 = float(td.get('tier_1', {}).get('score', 0))
t2 = float(td.get('tier_2', {}).get('score', 0))
t3 = float(td.get('tier_3', {}).get('score', 0))
cats = td.get('tier_2', {}).get('categories', {})
print(json.dumps({
    'config': '${config_name}',
    'total': t1+t2+t3, 'tier1': t1, 'tier2': t2, 'tier3': t3,
    'duration': float(cats.get('duration', {}).get('score', 0)),
    'smoothness': float(cats.get('trajectory smoothness', {}).get('score', 0)),
    'efficiency': float(cats.get('trajectory efficiency', {}).get('score', 0)),
    'force': float(cats.get('insertion force', {}).get('score', 0)),
    'dur_msg': cats.get('duration', {}).get('message', ''),
    'smooth_msg': cats.get('trajectory smoothness', {}).get('message', ''),
}))
")
        echo "$RESULT"
        echo "  $(echo "$RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Total={d[\"total\"]:.1f} Dur={d[\"duration\"]:.2f} Smooth={d[\"smoothness\"]:.2f} Tier3={d[\"tier3\"]:.1f}')")" >&2
    else
        echo "{\"config\": \"${config_name}\", \"total\": 0, \"error\": \"timeout\"}"
        echo "  TIMEOUT" >&2
    fi
done

echo "" >&2
echo "=== ${EXPERIMENT_NAME} complete ===" >&2
