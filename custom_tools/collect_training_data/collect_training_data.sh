#!/usr/bin/env bash
# =============================================================================
# E2E Training Data Collection Pipeline
# =============================================================================
# Sequentially runs training configs and collects all topic data (including
# cameras) plus scoring results for policy learning.
#
# Usage:
#   ./collect_training_data.sh <policy_module> [options]
#
# Examples:
#   ./collect_training_data.sh my_policy.HybridPolicy --headless --task-type sfp --start-idx 0 --end-idx 9
#   ./collect_training_data.sh my_policy.HybridPolicy --ground-truth --no-extra-bag
#
# Prerequisites:
#   - aic_eval distrobox/docker container available
#   - pixi environment set up
# =============================================================================

set -euo pipefail

# =============================================================================
# Global PID tracking for cleanup on interrupt
# =============================================================================
SIM_PID=""
POLICY_PID=""
ENGINE_PID=""
MONITOR_PID=""

SCRIPT_DONE="false"

cleanup_on_exit() {
    local exit_code=$?
    local signal="$1"

    # Skip cleanup on normal exit
    if [[ "$SCRIPT_DONE" == "true" && "$signal" == "EXIT" ]]; then
        return
    fi

    echo "" >&2
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Interrupted (signal=${signal}). Cleaning up..." >&2

    # Kill host-side tracked processes
    for pid in "$MONITOR_PID" "$POLICY_PID" "$ENGINE_PID" "$SIM_PID"; do
        if [[ -n "$pid" ]]; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
    done

    # Kill all aic-related processes on host
    pkill -9 -f "aic_model" 2>/dev/null || true
    pkill -f "ros2 run aic_engine" 2>/dev/null || true
    pkill -f "rmw_zenohd" 2>/dev/null || true
    pkill -f "entrypoint.sh" 2>/dev/null || true
    sudo pkill -f "rmw_zenohd" 2>/dev/null || true

    # Stop container processes (don't restart — just clean up)
    docker exec "$CONTAINER_NAME" bash -c "
        pkill -f 'aic_engine' 2>/dev/null || true
        pkill -f 'gz sim' 2>/dev/null || true
    " 2>/dev/null || true

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleanup complete. Exiting." >&2
    exit "${exit_code}"
}

trap 'cleanup_on_exit INT' INT
trap 'cleanup_on_exit TERM' TERM
trap 'cleanup_on_exit EXIT' EXIT

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_DIR="$(dirname "$SCRIPT_DIR")"          # custom_tools/
AIC_DIR="$(dirname "$TOOLS_DIR")"             # aic/
SRC_DIR="$(dirname "$AIC_DIR")"               # src/
WS_DIR="$(dirname "$(dirname "$SRC_DIR")")"
PIXI_DIR="${AIC_DIR}"                         # pixi workspace root (contains pixi.toml)
BENCHMARK_DIR="${AIC_DIR}/benchmark"
TRAIN_CONFIG_DIR="${TOOLS_DIR}/gen_training_configs/configs/train"
CONTAINER_NAME="aic_eval"

# Defaults
TIMEOUT_PER_CONFIG=660          # 3 trials * 180s + 120s overhead
SIM_STARTUP_TIMEOUT=120
MAX_RETRIES=3

# =============================================================================
# CLI argument parsing
# =============================================================================
POLICY_MODULE=""
HEADLESS="false"
TASK_TYPE="all"
START_IDX=0
END_IDX=999
DATA_DIR="${HOME}/aic_data/raw"
MONITOR="false"
GROUND_TRUTH="true"
SKIP_BUILD="false"

usage() {
    cat <<EOF >&2
Usage: $0 <policy_module> [options]

Options:
  --headless              Run without GUI (gazebo_gui:=false, launch_rviz:=false)
  --task-type <sfp|sc|all>  Config type to run (default: all)
  --start-idx <N>         Start config index (default: 0)
  --end-idx <N>           End config index (default: 999)
  --data-dir <path>       Output directory (default: ~/aic_data/raw)
  --no-ground-truth       Disable ground truth TF (default: enabled)
  --skip-build            Skip pixi build
  --max-retries <N>       Max retries per config (default: 3)
  --monitor               Show camera feed via cv2.imshow (useful with --headless)

Example:
  $0 my_policy.HybridPolicy --headless --monitor --task-type sfp --start-idx 0 --end-idx 9
EOF
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --headless)       HEADLESS="true"; shift ;;
        --task-type)      TASK_TYPE="$2"; shift 2 ;;
        --start-idx)      START_IDX="$2"; shift 2 ;;
        --end-idx)        END_IDX="$2"; shift 2 ;;
        --data-dir)       DATA_DIR="$2"; shift 2 ;;
        --no-ground-truth) GROUND_TRUTH="false"; shift ;;
        --skip-build)     SKIP_BUILD="true"; shift ;;
        --max-retries)    MAX_RETRIES="$2"; shift 2 ;;
        --monitor)        MONITOR="true"; shift ;;
        --help|-h)        usage ;;
        -*)               echo "Unknown option: $1" >&2; usage ;;
        *)
            if [[ -z "$POLICY_MODULE" ]]; then
                POLICY_MODULE="$1"
            else
                echo "Unexpected argument: $1" >&2; usage
            fi
            shift
            ;;
    esac
done

if [[ -z "$POLICY_MODULE" ]]; then
    echo "Error: policy_module is required." >&2
    usage
fi

# Validate task type
case "$TASK_TYPE" in
    sfp|sc|all) ;;
    *) echo "Error: --task-type must be sfp, sc, or all" >&2; exit 1 ;;
esac

LOG_DIR="${DATA_DIR}/logs"
PROGRESS_FILE="${DATA_DIR}/progress.yaml"
COLLECTION_LOG="${DATA_DIR}/collection.log"

mkdir -p "$DATA_DIR" "$LOG_DIR"

# =============================================================================
# Logging helper
# =============================================================================
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" >&2
    echo "$msg" >> "$COLLECTION_LOG"
}

# =============================================================================
# Build config list
# =============================================================================
# Supports two layouts:
#   1. Single folder: config_XXXX.yaml (alternating SFP/SC, new format)
#   2. Legacy folders: sfp/sfp_XXXX.yaml + sc/sc_XXXX.yaml
# Single folder (config_*) is checked first; falls back to legacy if absent.
# =============================================================================
build_config_list() {
    local configs=()

    # Layout: configs/{mode}/sfp/config_sfp_*.yaml, configs/{mode}/sc/config_sc_*.yaml
    if [[ "$TASK_TYPE" == "sfp" || "$TASK_TYPE" == "all" ]]; then
        for f in "${TRAIN_CONFIG_DIR}/sfp"/config_sfp_*.yaml; do
            [[ -f "$f" ]] && configs+=("$f")
        done
    fi
    if [[ "$TASK_TYPE" == "sc" || "$TASK_TYPE" == "all" ]]; then
        for f in "${TRAIN_CONFIG_DIR}/sc"/config_sc_*.yaml; do
            [[ -f "$f" ]] && configs+=("$f")
        done
    fi

    # Sort by numeric index (extract trailing digits before .yaml), then by type
    # e.g. config_sfp_0000.yaml → key "0000_sfp", config_sc_0001.yaml → key "0001_sc"
    # This interleaves SFP and SC by index number
    IFS=$'\n' configs=($(for f in "${configs[@]}"; do
        base=$(basename "$f" .yaml)
        num=$(echo "$base" | grep -oP '\d+$')
        echo "${num}_${f}"
    done | sort | sed 's/^[0-9]*_//')); unset IFS

    # Filter by index range
    local filtered=()
    local idx=0
    for f in "${configs[@]}"; do
        if (( idx >= START_IDX && idx <= END_IDX )); then
            filtered+=("$f")
        fi
        idx=$((idx + 1))
    done

    printf '%s\n' "${filtered[@]}"
}

# =============================================================================
# Resume: check if config already completed
# =============================================================================
is_completed() {
    local config_name="$1"
    if [[ -f "$PROGRESS_FILE" ]]; then
        grep -q "^${config_name}: completed" "$PROGRESS_FILE" 2>/dev/null && return 0
    fi
    return 1
}

mark_completed() {
    local config_name="$1"
    local score_total="$2"
    echo "${config_name}: completed  # score=${score_total} time=$(date '+%Y-%m-%dT%H:%M:%S')" >> "$PROGRESS_FILE"
}

mark_failed() {
    local config_name="$1"
    echo "${config_name}: failed  # time=$(date '+%Y-%m-%dT%H:%M:%S')" >> "$PROGRESS_FILE"
}

# =============================================================================
# Container helper
# =============================================================================
# Build docker exec display flags for GUI forwarding (non-headless mode)
_docker_display_flags() {
    local flags=""
    if [[ -n "${DISPLAY:-}" ]]; then
        flags+=" -e DISPLAY=${DISPLAY}"
    fi
    if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
        flags+=" -e WAYLAND_DISPLAY=${WAYLAND_DISPLAY}"
    fi
    if [[ -n "${XAUTHORITY:-}" ]]; then
        flags+=" -e XAUTHORITY=${XAUTHORITY}"
    fi
    echo "$flags"
}

run_in_container() {
    docker exec "$CONTAINER_NAME" bash -c "$1"
}

# =============================================================================
# Process cleanup
# =============================================================================
cleanup_processes() {
    pkill -9 -f "aic_model" 2>/dev/null || true
    pkill -f "ros2 run aic_engine" 2>/dev/null || true
    pkill -f "rmw_zenohd" 2>/dev/null || true
    pkill -f "entrypoint.sh" 2>/dev/null || true
    sudo pkill -f "rmw_zenohd" 2>/dev/null || true
    docker restart "$CONTAINER_NAME" &>/dev/null || true
    sleep 5
}

# =============================================================================
# Start simulation
# =============================================================================
start_simulation() {
    local sim_log="$1"

    local launch_args="ground_truth:=${GROUND_TRUTH} start_aic_engine:=false"
    local docker_flags=""
    if [[ "$HEADLESS" == "true" ]]; then
        launch_args+=" gazebo_gui:=false launch_rviz:=false"
    else
        # Forward display for GUI mode
        docker_flags="$(_docker_display_flags)"
    fi

    docker exec $docker_flags "$CONTAINER_NAME" /entrypoint.sh $launch_args \
        &>"$sim_log" &
    echo $!
}

# =============================================================================
# Wait for simulation ready (clock topic)
# =============================================================================
wait_for_simulation() {
    local sim_wait=0
    while (( sim_wait < SIM_STARTUP_TIMEOUT )); do
        sleep 5
        sim_wait=$((sim_wait + 5))
        if run_in_container "source /ws_aic/install/setup.bash 2>/dev/null && \
            export RMW_IMPLEMENTATION=rmw_zenoh_cpp && \
            export ZENOH_CONFIG_OVERRIDE=';transport/shared_memory/enabled=false' && \
            export ZENOH_ROUTER_CONFIG_URI=/aic_zenoh_config.json5 && \
            ros2 daemon stop 2>/dev/null; \
            ros2 topic echo /clock --once --spin-time 3" &>/dev/null; then
            log "  Simulation ready (clock detected after ${sim_wait}s)"
            return 0
        fi
        if (( sim_wait % 30 == 0 )); then
            log "  Still waiting for clock... ${sim_wait}s"
        fi
    done
    log "  Simulation not ready after ${SIM_STARTUP_TIMEOUT}s"
    return 1
}

# =============================================================================
# Start extra bag recording (cameras + observations) inside container
# =============================================================================

# =============================================================================
# Start policy on host
# =============================================================================
start_policy() {
    local config_name="$1"
    local policy_log="${LOG_DIR}/${config_name}_policy.log"

    cd "$PIXI_DIR"
    RMW_IMPLEMENTATION=rmw_zenoh_cpp pixi run ros2 daemon stop &>/dev/null || true
    bash -c "
        cd ${PIXI_DIR}
        source ${WS_DIR}/install/setup.bash
        export RMW_IMPLEMENTATION=rmw_zenoh_cpp
        export ZENOH_SESSION_CONFIG_URI=${BENCHMARK_DIR}/configs/zenoh_session_config.json5
        export ROS_DOMAIN_ID=0
        pixi run ros2 run aic_model aic_model --ros-args \
            -p use_sim_time:=true \
            -p policy:=${POLICY_MODULE}
    " &>"$policy_log" &
    echo $!
}

# =============================================================================
# Start aic_engine inside container
# =============================================================================
start_engine() {
    local config_file="$1"
    local results_dir="$2"
    local engine_log="$3"

    docker exec "$CONTAINER_NAME" bash -c "
        source /ws_aic/install/setup.bash
        export RMW_IMPLEMENTATION=rmw_zenoh_cpp
        export ZENOH_CONFIG_OVERRIDE=';transport/shared_memory/enabled=false'
        export ZENOH_ROUTER_CONFIG_URI=/aic_zenoh_config.json5
        export AIC_RESULTS_DIR=${results_dir}
        mkdir -p ${results_dir}
        ros2 run aic_engine aic_engine --ros-args \
            -p config_file_path:=${config_file} \
            -p ground_truth:=${GROUND_TRUTH} \
            -p use_sim_time:=true \
            -p record_all_topics:=true
    " &>"$engine_log" &
    echo $!
}

# =============================================================================
# Wait for scoring.yaml
# =============================================================================
wait_for_scoring() {
    local scoring_file="$1"
    local elapsed=0

    while [[ ! -f "$scoring_file" ]] && (( elapsed < TIMEOUT_PER_CONFIG )); do
        sleep 5
        elapsed=$((elapsed + 5))
        if (( elapsed % 60 == 0 )); then
            log "  Waiting for scoring... ${elapsed}s elapsed"
        fi
    done
    sleep 2

    [[ -f "$scoring_file" ]]
}

# =============================================================================
# Extract score total from scoring.yaml
# =============================================================================
extract_score_total() {
    local scoring_file="$1"
    python3 -c "
import yaml, sys
with open('${scoring_file}') as f:
    data = yaml.safe_load(f)
if not data:
    print('0.0')
    sys.exit(0)
trials = [k for k in data if k.startswith('trial_')]
total = 0.0
for t in trials:
    td = data[t]
    total += float(td.get('tier_1', {}).get('score', 0))
    total += float(td.get('tier_2', {}).get('score', 0))
    total += float(td.get('tier_3', {}).get('score', 0))
avg = total / len(trials) if trials else 0
print(f'{avg:.4f}')
" 2>/dev/null || echo "0.0"
}

# =============================================================================
# Display score table for a config
# =============================================================================
display_scores() {
    local scoring_file="$1"
    python3 -c "
import yaml, sys
with open('${scoring_file}') as f:
    data = yaml.safe_load(f)
if not data:
    print('  No scoring data', file=sys.stderr)
    sys.exit(0)
trials = sorted([k for k in data if k.startswith('trial_')])
print('', file=sys.stderr)
print('  +----------+--------+--------+--------+--------+', file=sys.stderr)
print('  |  Trial   | Tier 1 | Tier 2 | Tier 3 | Total  |', file=sys.stderr)
print('  +----------+--------+--------+--------+--------+', file=sys.stderr)
grand_total = 0
for t in trials:
    td = data[t]
    t1 = float(td.get('tier_1', {}).get('score', 0))
    t2 = float(td.get('tier_2', {}).get('score', 0))
    t3 = float(td.get('tier_3', {}).get('score', 0))
    total = t1 + t2 + t3
    grand_total += total
    name = t.replace('_', ' ').title()
    print(f'  | {name:>8} | {t1:6.2f} | {t2:6.2f} | {t3:6.2f} | {total:6.2f} |', file=sys.stderr)
print('  +----------+--------+--------+--------+--------+', file=sys.stderr)
avg = grand_total / len(trials) if trials else 0
print(f'  | {\"Average\":>8} |        |        |        | {avg:6.2f} |', file=sys.stderr)
print('  +----------+--------+--------+--------+--------+', file=sys.stderr)
" 2>&2
}

# =============================================================================
# Main: build policy if needed
# =============================================================================
log "=== Training Data Collection Pipeline ==="
log "Policy: ${POLICY_MODULE}"
log "Task type: ${TASK_TYPE}"
log "Index range: ${START_IDX}-${END_IDX}"
log "Data dir: ${DATA_DIR}"
log "Headless: ${HEADLESS}"
log "Ground truth: ${GROUND_TRUTH}"
log ""

if [[ "$SKIP_BUILD" == "true" ]]; then
    log "Skipping build (--skip-build)"
else
    log "Building policy package..."
    cd "$PIXI_DIR"
    pixi run colcon build --packages-select aic_example_policies 2>&1 | tail -5 >&2
    COLCON_POLICY_DIR="${WS_DIR}/install/lib/python3.12/site-packages/aic_example_policies"
    PIXI_POLICY_DIR="${PIXI_DIR}/.pixi/envs/default/lib/python3.12/site-packages/aic_example_policies"
    if [[ -d "$COLCON_POLICY_DIR" ]] && [[ -d "$PIXI_POLICY_DIR" ]]; then
        cp -r "${COLCON_POLICY_DIR}/ros/" "${PIXI_POLICY_DIR}/ros/" 2>/dev/null || true
        log "Synced policy to pixi env"
    fi
fi

# =============================================================================
# Main: iterate configs
# =============================================================================
mapfile -t CONFIG_LIST < <(build_config_list)
TOTAL_CONFIGS=${#CONFIG_LIST[@]}

log "Total configs to process: ${TOTAL_CONFIGS}"
log ""

completed_count=0
failed_count=0
skipped_count=0

for config_idx in "${!CONFIG_LIST[@]}"; do
    config_file="${CONFIG_LIST[$config_idx]}"
    config_basename="$(basename "$config_file" .yaml)"
    config_num=$((config_idx + 1))

    log "=== [${config_num}/${TOTAL_CONFIGS}] ${config_basename} ==="

    # Resume check
    if is_completed "$config_basename"; then
        log "  Already completed, skipping."
        skipped_count=$((skipped_count + 1))
        continue
    fi

    # Output directory for this config
    CONFIG_OUTPUT_DIR="${DATA_DIR}/${config_basename}"
    ENGINE_RESULTS_DIR="${CONFIG_OUTPUT_DIR}/engine_results"
    SCORING_FILE="${ENGINE_RESULTS_DIR}/scoring.yaml"

    attempt=0
    config_success="false"

    while [[ "$config_success" == "false" ]] && (( attempt < MAX_RETRIES )); do
        attempt=$((attempt + 1))

        # Reset PID tracking for this attempt
        SIM_PID=""
        POLICY_PID=""
        ENGINE_PID=""
        if (( attempt > 1 )); then
            log "  Retry ${attempt}/${MAX_RETRIES}..."
        fi

        # Clean up from previous attempts
        rm -rf "$CONFIG_OUTPUT_DIR" 2>/dev/null || true
        mkdir -p "$CONFIG_OUTPUT_DIR" "$ENGINE_RESULTS_DIR"

        # 1. Cleanup processes
        cleanup_processes

        # 2. Start simulation
        log "  Starting simulation (headless=${HEADLESS}, ground_truth=${GROUND_TRUTH})..."
        SIM_PID=$(start_simulation "${LOG_DIR}/${config_basename}_sim.log")

        # 3. Wait for simulation ready
        log "  Waiting for simulation..."
        if ! wait_for_simulation; then
            log "  Simulation not ready, retrying..."
            kill "$SIM_PID" 2>/dev/null || true
            wait "$SIM_PID" 2>/dev/null || true
            continue
        fi

        # 4. Start camera monitor (once, restart if dead)
        if [[ "$MONITOR" == "true" ]]; then
            if [[ -z "$MONITOR_PID" ]] || ! kill -0 "$MONITOR_PID" 2>/dev/null; then
                log "  Starting camera monitor..."
                cd "$PIXI_DIR"
                bash -c "
                    cd ${PIXI_DIR}
                    source ${WS_DIR}/install/setup.bash
                    export RMW_IMPLEMENTATION=rmw_zenoh_cpp
                    export ZENOH_SESSION_CONFIG_URI=${BENCHMARK_DIR}/configs/zenoh_session_config.json5
                    export ROS_DOMAIN_ID=0
                    pixi run python3 ${SCRIPT_DIR}/monitor_camera.py
                " &>"${LOG_DIR}/monitor_camera.log" &
                MONITOR_PID=$!
            fi
        fi

        # 5. Start policy
        log "  Starting policy (${POLICY_MODULE})..."
        POLICY_PID=$(start_policy "$config_basename")
        sleep 10

        # 6. Start aic_engine
        #    Engine flow: ModelReady → EndpointsReady → SimulatorReady (spawn)
        #                 → ScoringReady (StartRecording) → TasksExecuting
        #                 → AllTasksCompleted → StopRecording → scoring.yaml
        log "  Starting aic_engine..."
        ENGINE_PID=$(start_engine "$config_file" "$ENGINE_RESULTS_DIR" "${LOG_DIR}/${config_basename}_engine.log")

        # 7. Wait for scoring.yaml (engine handles all recording internally)
        log "  Waiting for scoring results (timeout: ${TIMEOUT_PER_CONFIG}s)..."
        elapsed=0
        while [[ ! -f "$SCORING_FILE" ]] && (( elapsed < TIMEOUT_PER_CONFIG )); do
            sleep 5
            elapsed=$((elapsed + 5))
            if (( elapsed % 60 == 0 )); then
                log "  Still waiting... ${elapsed}s elapsed"
            fi
        done
        sleep 2

        if [[ -f "$SCORING_FILE" ]]; then
            config_success="true"
            log "  Scoring complete!"
        else
            log "  TIMEOUT (attempt ${attempt}/${MAX_RETRIES}) - no scoring.yaml after ${TIMEOUT_PER_CONFIG}s"
        fi

        # 8. Kill processes and reset PIDs
        kill "$POLICY_PID" 2>/dev/null || true
        kill "$ENGINE_PID" 2>/dev/null || true
        kill "$SIM_PID" 2>/dev/null || true
        wait "$POLICY_PID" 2>/dev/null || true
        wait "$ENGINE_PID" 2>/dev/null || true
        wait "$SIM_PID" 2>/dev/null || true
        SIM_PID=""
        POLICY_PID=""
        ENGINE_PID=""

    done  # end retry loop

    if [[ "$config_success" == "true" ]]; then
        # Copy original config for reproducibility
        cp "$config_file" "${CONFIG_OUTPUT_DIR}/config.yaml"

        # Extract task metadata
        python3 "${SCRIPT_DIR}/extract_metadata.py" \
            "$config_file" "${CONFIG_OUTPUT_DIR}/task_metadata.yaml" 2>/dev/null || true

        # Copy scoring to top-level for convenience
        cp "$SCORING_FILE" "${CONFIG_OUTPUT_DIR}/scoring.yaml" 2>/dev/null || true

        # Display scores
        display_scores "$SCORING_FILE"

        # Mark completed
        score_total=$(extract_score_total "$SCORING_FILE")
        mark_completed "$config_basename" "$score_total"
        completed_count=$((completed_count + 1))
        log "  Saved to ${CONFIG_OUTPUT_DIR}/ (avg score: ${score_total})"
    else
        mark_failed "$config_basename"
        failed_count=$((failed_count + 1))
        log "  FAILED after ${MAX_RETRIES} attempts"
        # Clean up failed output
        rm -rf "$CONFIG_OUTPUT_DIR" 2>/dev/null || true
    fi

    log ""
done

# =============================================================================
# Final summary
# =============================================================================
log "=== Collection Complete ==="
log "Completed: ${completed_count}"
log "Failed:    ${failed_count}"
log "Skipped:   ${skipped_count}"
log "Total:     ${TOTAL_CONFIGS}"
log "Data dir:  ${DATA_DIR}"
log ""

# Generate merged results if any configs completed
if (( completed_count > 0 )); then
    log "Generating results summary..."
    python3 "${SCRIPT_DIR}/merge_results.py" "$DATA_DIR" 2>/dev/null || true
    log "Summary saved to ${DATA_DIR}/summary.csv"
fi

SCRIPT_DONE="true"
log "=== Done ==="
