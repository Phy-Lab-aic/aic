#!/usr/bin/env bash
# Benchmark runner: executes configs against a given policy
# Usage: ./benchmark/scripts/run_benchmark.sh <policy_module> [--type sfp|sc|mixed] [--ground-truth] [--skip-build]
#
# Config directory structure:
#   benchmark/configs/sfp/     (1-trial SFP configs)
#   benchmark/configs/sc/      (1-trial SC configs)
#   benchmark/configs/mixed/   (3-trial mixed configs)
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
SCORING_FILE="${HOME}/aic_results/scoring.yaml"
CONTAINER_NAME="aic_eval"
TIMEOUT_PER_CONFIG=300
MAX_RETRIES=5

# Parse arguments
POLICY_MODULE=""
GROUND_TRUTH="false"
SKIP_BUILD="false"
CONFIG_TYPE=""
HEADLESS="true"

_prev=""
for arg in "$@"; do
    if [ "$_prev" = "--type" ]; then
        CONFIG_TYPE="$arg"
        _prev="$arg"
        continue
    fi
    case "$arg" in
        --ground-truth)  GROUND_TRUTH="true" ;;
        --skip-build)    SKIP_BUILD="true" ;;
        --gui)           HEADLESS="false" ;;
        --type=*)        CONFIG_TYPE="${arg#--type=}" ;;
        --type)          ;; # value handled by _prev
        *)
            if [ -z "$POLICY_MODULE" ]; then
                POLICY_MODULE="$arg"
            fi
            ;;
    esac
    _prev="$arg"
done

if [ -z "$POLICY_MODULE" ]; then
    echo "Usage: $0 <policy_module> [--type sfp|sc|mixed] [--ground-truth] [--skip-build] [--gui]" >&2
    echo "" >&2
    echo "  --type sfp|sc|mixed   Run configs from specific subfolder (default: all)" >&2
    echo "  --ground-truth        Use ground truth mode" >&2
    echo "  --skip-build          Skip colcon build step" >&2
    echo "  --gui                 Run with Gazebo GUI (default: headless)" >&2
    echo "" >&2
    echo "Examples:" >&2
    echo "  # PilzPolicy — SFP configs only" >&2
    echo "  $0 my_policy.PilzPolicy --type sfp --skip-build" >&2
    echo "" >&2
    echo "  # PilzPolicy — SC configs only" >&2
    echo "  $0 my_policy.PilzPolicy --type sc --skip-build" >&2
    echo "" >&2
    echo "  # PilzPolicy — mixed (3-trial) configs" >&2
    echo "  $0 my_policy.PilzPolicy --type mixed" >&2
    echo "" >&2
    echo "  # PilzPolicy — all configs" >&2
    echo "  $0 my_policy.PilzPolicy" >&2
    echo "" >&2
    echo "  # CheatCode baseline (needs --ground-truth)" >&2
    echo "  $0 aic_example_policies.ros.CheatCode --type mixed --ground-truth" >&2
    exit 1
fi

# Validate config type
if [ -n "$CONFIG_TYPE" ] && [[ ! "$CONFIG_TYPE" =~ ^(sfp|sc|mixed)$ ]]; then
    echo "Error: --type must be one of: sfp, sc, mixed" >&2
    exit 1
fi

# Collect config files
CONFIG_FILES=()
if [ -n "$CONFIG_TYPE" ]; then
    # Single type
    TYPE_DIR="${CONFIGS_DIR}/${CONFIG_TYPE}"
    if [ ! -d "$TYPE_DIR" ]; then
        echo "Error: Config directory not found: ${TYPE_DIR}" >&2
        exit 1
    fi
    for f in "${TYPE_DIR}"/benchmark_*.yaml; do
        [ -f "$f" ] && CONFIG_FILES+=("$f")
    done
else
    # All types: sfp, sc, mixed (also root for legacy configs)
    for subdir in sfp sc mixed; do
        if [ -d "${CONFIGS_DIR}/${subdir}" ]; then
            for f in "${CONFIGS_DIR}/${subdir}"/benchmark_*.yaml; do
                [ -f "$f" ] && CONFIG_FILES+=("$f")
            done
        fi
    done
    # Legacy: root-level configs
    for f in "${CONFIGS_DIR}"/benchmark_*.yaml; do
        [ -f "$f" ] && CONFIG_FILES+=("$f")
    done
fi

TOTAL_CONFIGS=${#CONFIG_FILES[@]}
if [ "$TOTAL_CONFIGS" -eq 0 ]; then
    echo "Error: No benchmark configs found" >&2
    exit 1
fi

# Timestamped run ID
RUN_ID="$(date +%Y%m%d_%H%M%S)"
CLASS_NAME="${POLICY_MODULE##*.}"
TYPE_LABEL="${CONFIG_TYPE:-all}"

RESULTS_DIR="${BENCHMARK_DIR}/results/${CLASS_NAME}_${TYPE_LABEL}_${RUN_ID}"
LOG_DIR="${BENCHMARK_DIR}/logs/${CLASS_NAME}_${TYPE_LABEL}_${RUN_ID}"

# PID tracking for cleanup
SIM_PID=""
POLICY_PID=""
ENGINE_PID=""

cleanup() {
    echo "" >&2
    echo "Cleaning up processes..." >&2
    # Kill host-side background processes
    [ -n "$POLICY_PID" ] && kill "$POLICY_PID" 2>/dev/null || true
    [ -n "$ENGINE_PID" ] && kill "$ENGINE_PID" 2>/dev/null || true
    [ -n "$SIM_PID" ] && kill "$SIM_PID" 2>/dev/null || true
    wait "$POLICY_PID" 2>/dev/null || true
    wait "$ENGINE_PID" 2>/dev/null || true
    wait "$SIM_PID" 2>/dev/null || true
    pkill -f "ros2 run aic_model" 2>/dev/null || true
    pkill -f "ros2 run aic_engine" 2>/dev/null || true
    # Restart container to guarantee all internal processes are cleaned up
    # (docker exec pkill misses rmw_zenohd, robot_state_publisher, component_container, etc.)
    docker restart "$CONTAINER_NAME" &>/dev/null || true
    echo "Cleanup done." >&2
}
trap cleanup EXIT INT TERM

mkdir -p "$RESULTS_DIR" "$LOG_DIR"

echo "=== Benchmark Runner ===" >&2
echo "Policy: ${POLICY_MODULE} (${CLASS_NAME})" >&2
echo "Type: ${TYPE_LABEL}" >&2
echo "Ground truth: ${GROUND_TRUTH}" >&2
echo "Headless: ${HEADLESS}" >&2
echo "Configs: ${TOTAL_CONFIGS} files" >&2
echo "Results: ${RESULTS_DIR}" >&2
echo "Logs: ${LOG_DIR}" >&2
echo "Run ID: ${RUN_ID}" >&2
echo "" >&2

# Helper: run command inside container
run_in_container() {
    docker exec "$CONTAINER_NAME" bash -c "$1"
}

# Step 1: Build policy package
# Extract package name from policy module (e.g. "my_policy.PilzPolicy" -> "my_policy")
POLICY_PACKAGE="${POLICY_MODULE%%.*}"

if [ "$SKIP_BUILD" = "true" ]; then
    echo "Skipping build (--skip-build)" >&2
else
    echo "Building policy package (${POLICY_PACKAGE})..." >&2
    cd "$SRC_DIR"
    pixi run colcon build --packages-select "$POLICY_PACKAGE" 2>&1 | tail -5 >&2
    # Sync to pixi env cache
    COLCON_POLICY_DIR="${WS_DIR}/install/lib/python3.12/site-packages/${POLICY_PACKAGE}"
    PIXI_POLICY_DIR="${SRC_DIR}/.pixi/envs/default/lib/python3.12/site-packages/${POLICY_PACKAGE}"
    if [ -d "$COLCON_POLICY_DIR" ] && [ -d "$PIXI_POLICY_DIR" ]; then
        cp -r "${COLCON_POLICY_DIR}/" "${PIXI_POLICY_DIR}/" 2>/dev/null || true
        echo "Synced ${POLICY_PACKAGE} to pixi env" >&2
    fi
fi

# Step 2: Run each config
config_idx=0
for config_file in "${CONFIG_FILES[@]}"; do
    config_idx=$((config_idx + 1))
    config_name="$(basename "$config_file" .yaml)"
    # Detect which subfolder this config is from
    config_parent="$(basename "$(dirname "$config_file")")"
    echo "" >&2
    echo "=== Config ${config_idx}/${TOTAL_CONFIGS} [${config_parent}]: ${config_name} ===" >&2

    attempt=0
    config_success="false"
    while [ "$config_success" = "false" ] && [ "$attempt" -lt "$MAX_RETRIES" ]; do
    attempt=$((attempt + 1))
    if [ "$attempt" -gt 1 ]; then
        echo "  Retry ${attempt}/${MAX_RETRIES}..." >&2
    fi

    # Kill leftover processes (host + container) for clean state
    pkill -9 -f "aic_model" 2>/dev/null || true
    pkill -f "ros2 run aic_engine" 2>/dev/null || true
    pkill -f "rmw_zenohd" 2>/dev/null || true
    pkill -f "entrypoint.sh" 2>/dev/null || true
    sudo pkill -f "rmw_zenohd" 2>/dev/null || true
    docker restart "$CONTAINER_NAME" &>/dev/null || true
    sleep 5

    # Start simulation
    SIM_ARGS="ground_truth:=${GROUND_TRUTH} start_aic_engine:=false"
    if [ "$HEADLESS" = "true" ]; then
        SIM_ARGS+=" gazebo_gui:=false launch_rviz:=false"
    fi
    echo "  Starting simulation (ground_truth=${GROUND_TRUTH}, headless=${HEADLESS})..." >&2
    docker exec "$CONTAINER_NAME" /entrypoint.sh $SIM_ARGS \
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
        SIM_PID=""
        docker exec "$CONTAINER_NAME" bash -c \
            "pkill -f aic_engine; pkill -f entrypoint" 2>/dev/null || true
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
        source ${WS_DIR}/install/setup.bash 2>/dev/null || true
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
    docker exec "$CONTAINER_NAME" bash -c \
        "pkill -f aic_engine; pkill -f aic_model; pkill -f entrypoint" 2>/dev/null || true
    POLICY_PID=""
    ENGINE_PID=""
    SIM_PID=""

    # Copy results and display score table
    if [ -f "$SCORING_FILE" ]; then
        config_success="true"
        cp "$SCORING_FILE" "${RESULTS_DIR}/${config_name}_scoring.yaml"
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
        echo "total: 0" > "${RESULTS_DIR}/${config_name}_scoring.yaml"
    fi
done

# Step 3: Final summary table
echo "" >&2
echo "=== Final Summary ===" >&2
python3 -c "
import yaml, sys, os
results_dir = '${RESULTS_DIR}'
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
python3 "${SCRIPT_DIR}/collect_scores.py" "$POLICY_MODULE" --results-dir "$RESULTS_DIR" --branch "$BRANCH"

echo "" >&2
echo "=== Benchmark complete ===" >&2
echo "Run ID: ${RUN_ID}" >&2
echo "Results: ${RESULTS_DIR}/" >&2
echo "Logs: ${LOG_DIR}/" >&2
echo "Leaderboard: ${BENCHMARK_DIR}/leaderboard.yaml" >&2
echo "Markdown: ${BENCHMARK_DIR}/LEADERBOARD.md" >&2
