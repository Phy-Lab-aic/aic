#!/usr/bin/env bash
# run_trial3.sh — trial_3_only.yaml 전용 성능 측정 스크립트
# Usage: ./benchmark/scripts/run_trial3.sh [policy_module] [--ground-truth] [--skip-build] [--runs N]
# Default policy: aic_example_policies.ros.CheatCodeJoint
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
CONFIG_FILE="${SRC_DIR}/aic_engine/config/trial_3_only.yaml"
RESULTS_DIR="${BENCHMARK_DIR}/results"
LOG_DIR="${BENCHMARK_DIR}/logs"
AIC_RESULTS_DIR="${AIC_RESULTS_DIR:-${HOME}/aic_results}"
SCORING_FILE="${AIC_RESULTS_DIR}/scoring.yaml"
CONTAINER_NAME="aic_eval"
TIMEOUT_PER_CONFIG=300
MAX_RETRIES=3
DEFAULT_POLICY="aic_example_policies.ros.CheatCodeJoint"

# Parse arguments
POLICY_MODULE=""
GROUND_TRUTH="false"
SKIP_BUILD="false"
N_RUNS=1

_next_is_runs="false"
for arg in "$@"; do
    if [ "$_next_is_runs" = "true" ]; then
        N_RUNS="$arg"
        _next_is_runs="false"
        continue
    fi
    case "$arg" in
        --ground-truth)
            GROUND_TRUTH="true"
            ;;
        --skip-build)
            SKIP_BUILD="true"
            ;;
        --runs)
            _next_is_runs="true"
            ;;
        *)
            if [ -z "$POLICY_MODULE" ]; then
                POLICY_MODULE="$arg"
            fi
            ;;
    esac
done

POLICY_MODULE="${POLICY_MODULE:-$DEFAULT_POLICY}"
CLASS_NAME="${POLICY_MODULE##*.}"
POLICY_RESULTS_DIR="${RESULTS_DIR}/${CLASS_NAME}"

mkdir -p "$POLICY_RESULTS_DIR" "$LOG_DIR"

echo "=== Trial 3 Only — ${CLASS_NAME} ===" >&2
echo "Policy:       ${POLICY_MODULE}" >&2
echo "Config:       ${CONFIG_FILE}" >&2
echo "Ground truth: ${GROUND_TRUTH}" >&2
echo "Runs:         ${N_RUNS}" >&2
echo "Results dir:  ${POLICY_RESULTS_DIR}" >&2
echo "" >&2

if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR: Config file not found: ${CONFIG_FILE}" >&2
    exit 1
fi

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
    COLCON_POLICY_DIR="${WS_DIR}/install/lib/python3.12/site-packages/aic_example_policies"
    PIXI_POLICY_DIR="${SRC_DIR}/.pixi/envs/default/lib/python3.12/site-packages/aic_example_policies"
    if [ -d "$COLCON_POLICY_DIR" ] && [ -d "$PIXI_POLICY_DIR" ]; then
        cp -r "${COLCON_POLICY_DIR}/ros/" "${PIXI_POLICY_DIR}/ros/" 2>/dev/null || true
        echo "Synced policy to pixi env" >&2
    fi
fi

# Step 2: Run N_RUNS times
SESSION_SCORES=()

for run in $(seq 1 "$N_RUNS"); do
if [ "$N_RUNS" -gt 1 ]; then
    echo "" >&2
    echo "╔══════════════════════════════════╗" >&2
    echo "║  RUN ${run} / ${N_RUNS}$(printf '%*s' $((26 - ${#run} - ${#N_RUNS})) '')║" >&2
    echo "╚══════════════════════════════════╝" >&2
fi

LOG_SFX="trial3_only"
[ "$N_RUNS" -gt 1 ] && LOG_SFX="trial3_only_run${run}"

attempt=0
run_success="false"

while [ "$run_success" = "false" ] && [ "$attempt" -lt "$MAX_RETRIES" ]; do
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

    # Start simulation (headless, background)
    echo "  Starting simulation (ground_truth=${GROUND_TRUTH})..." >&2
    docker exec "$CONTAINER_NAME" /entrypoint.sh \
        ground_truth:="${GROUND_TRUTH}" \
        start_aic_engine:=false \
        &>"${LOG_DIR}/${LOG_SFX}_sim.log" &
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
    rm -rf "${AIC_RESULTS_DIR}/bag_"* 2>/dev/null || true

    # Start policy on host via pixi
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
    " &>"${LOG_DIR}/${LOG_SFX}_policy.log" &
    POLICY_PID=$!

    echo "  Policy started (PID ${POLICY_PID}). Waiting 10s for init..." >&2
    sleep 10

    # Start aic_engine inside container
    echo "  Starting aic_engine..." >&2
    docker exec "$CONTAINER_NAME" bash -c "
        source /ws_aic/install/setup.bash
        export RMW_IMPLEMENTATION=rmw_zenoh_cpp
        export ZENOH_CONFIG_OVERRIDE=';transport/shared_memory/enabled=false'
        export ZENOH_ROUTER_CONFIG_URI=/aic_zenoh_config.json5
        export AIC_RESULTS_DIR='${AIC_RESULTS_DIR}'
        ros2 run aic_engine aic_engine --ros-args \
            -p config_file_path:=${CONFIG_FILE} \
            -p ground_truth:=${GROUND_TRUTH} \
            -p use_sim_time:=true
    " &>"${LOG_DIR}/${LOG_SFX}_engine.log" &
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

    # Send SIGTERM to engine inside container so score_run() can write scoring.yaml
    docker exec "$CONTAINER_NAME" bash -c "pkill -TERM -f 'aic_engine' 2>/dev/null || true" &>/dev/null || true
    sleep 3

    # Cleanup processes
    kill "$POLICY_PID" 2>/dev/null || true
    kill "$ENGINE_PID" 2>/dev/null || true
    kill "$SIM_PID" 2>/dev/null || true
    wait "$POLICY_PID" 2>/dev/null || true
    wait "$ENGINE_PID" 2>/dev/null || true
    wait "$SIM_PID" 2>/dev/null || true

    # Copy results and display score table + save markdown
    if [ -f "$SCORING_FILE" ]; then
        run_success="true"
        TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
        TIMESTAMPED_YAML="${POLICY_RESULTS_DIR}/trial3_only_${TIMESTAMP}_scoring.yaml"
        cp "$SCORING_FILE" "${POLICY_RESULTS_DIR}/trial3_only_scoring.yaml"
        cp "$SCORING_FILE" "${TIMESTAMPED_YAML}"

        RUN_SCORE="$(python3 -c "
import yaml, sys, os
from datetime import datetime

scoring_file = '${SCORING_FILE}'
results_dir  = '${RESULTS_DIR}'
policy       = '${POLICY_MODULE}'
class_name   = '${CLASS_NAME}'
ground_truth = '${GROUND_TRUTH}'
timestamp    = '${TIMESTAMP}'
n_runs       = ${N_RUNS}
run_idx      = ${run}
history_path = os.path.join(results_dir, 'trial3_history.yaml')
md_path      = os.path.join(results_dir, 'TRIAL3_RESULTS.md')

with open(scoring_file) as f:
    data = yaml.safe_load(f)

if not data:
    print('  No scoring data', file=sys.stderr)
    print('0.0')
    sys.exit(0)

# --- 이번 실행 결과 파싱 ---
trial_keys = sorted([k for k in data if k.startswith('trial_')])
if n_runs > 1:
    print(f'  --- Run {run_idx}/{n_runs} ---', file=sys.stderr)
print('', file=sys.stderr)
print('  ┌─────────┬────────┬────────┬────────┬────────┐', file=sys.stderr)
print('  │  Trial  │ Tier 1 │ Tier 2 │ Tier 3 │ Total  │', file=sys.stderr)
print('  ├─────────┼────────┼────────┼────────┼────────┤', file=sys.stderr)
grand_total = 0
trial_rows = []
for tk in trial_keys:
    td = data[tk]
    t1 = float(td.get('tier_1', {}).get('score', 0))
    t2 = float(td.get('tier_2', {}).get('score', 0))
    t3 = float(td.get('tier_3', {}).get('score', 0))
    total = t1 + t2 + t3
    grand_total += total
    cats = {}
    for cat, v in td.get('tier_2', {}).get('categories', {}).items():
        cats[cat] = {'score': float(v.get('score', 0)), 'message': v.get('message', '')}
    trial_rows.append({
        'name': tk.replace('_', ' ').title(),
        't1': t1, 't2': t2, 't3': t3, 'total': total,
        'tier2_categories': cats,
        'tier3_message': td.get('tier_3', {}).get('message', ''),
    })
    name = tk.replace('_', ' ').title()
    print(f'  │ {name:>7} │ {t1:6.2f} │ {t2:6.2f} │ {t3:6.2f} │ {total:6.2f} │', file=sys.stderr)
print('  └─────────┴────────┴────────┴────────┴────────┘', file=sys.stderr)
print(f'  Total score: {grand_total:.2f}', file=sys.stderr)
print(f'{grand_total:.4f}')  # stdout: for SESSION_SCORES

# --- YAML 이력 파일에 추가 ---
history = []
if os.path.isfile(history_path):
    with open(history_path) as f:
        history = yaml.safe_load(f) or []

history.append({
    'timestamp': timestamp,
    'policy': policy,
    'class_name': class_name,
    'ground_truth': ground_truth,
    'total': round(grand_total, 4),
    'tier1': round(sum(r['t1'] for r in trial_rows) / len(trial_rows), 4),
    'tier2': round(sum(r['t2'] for r in trial_rows) / len(trial_rows), 4),
    'tier3': round(sum(r['t3'] for r in trial_rows) / len(trial_rows), 4),
    'trials': trial_rows,
})

with open(history_path, 'w') as f:
    yaml.dump(history, f, default_flow_style=False, allow_unicode=True)

# --- MD 전체 재생성 (점수 내림차순) ---
sorted_history = sorted(history, key=lambda e: e['total'], reverse=True)

lines = [
    '# Trial 3 Only — Results',
    '',
    '> SC connector insertion benchmark (trial_3_only.yaml). Score: T1+T2+T3 total (max ~100).',
    '',
    '| Rank | Policy | GT | T1 | T2 | T3 | Total | Date |',
    '|------|--------|----|----|----|----|-------|------|',
]
for rank, entry in enumerate(sorted_history, 1):
    dt = datetime.strptime(entry['timestamp'], '%Y%m%d_%H%M%S').strftime('%Y-%m-%d %H:%M')
    gt = 'yes' if entry['ground_truth'] == 'true' else 'no'
    lines.append(
        f\"| {rank} | {entry['class_name']} | {gt} \"
        f\"| {entry['tier1']:.2f} | {entry['tier2']:.2f} | {entry['tier3']:.2f} \"
        f\"| **{entry['total']:.2f}** | {dt} |\"
    )

lines += ['', '## Run Details', '']

for rank, entry in enumerate(sorted_history, 1):
    dt = datetime.strptime(entry['timestamp'], '%Y%m%d_%H%M%S').strftime('%Y-%m-%d %H:%M:%S')
    gt = 'yes' if entry['ground_truth'] == 'true' else 'no'
    lines.append(
        f\"<details><summary>#{rank} {entry['class_name']} — {entry['total']:.2f} \"\
        f\"({dt}, gt={gt})</summary>\"
    )
    lines.append('')
    lines.append(f\"- **Policy:** \`{entry['policy']}\`\")
    lines.append('')
    for tr in entry['trials']:
        lines.append(f\"**{tr['name']}** — T1: {tr['t1']:.2f} | T2: {tr['t2']:.2f} | T3: {tr['t3']:.2f} | Total: {tr['total']:.2f}\")
        lines.append('')
        if tr['tier2_categories']:
            lines.append('Tier 2 breakdown:')
            lines.append('')
            for cat, v in tr['tier2_categories'].items():
                lines.append(f\"- **{cat}** ({v['score']:.2f}): {v['message']}\")
            lines.append('')
        if tr['tier3_message']:
            lines.append(f\"Tier 3: {tr['tier3_message']}\")
            lines.append('')
    lines.append('</details>')
    lines.append('')

with open(md_path, 'w') as f:
    f.write('\n'.join(lines))

print(f'  Markdown saved: {md_path}', file=sys.stderr)
print(f'  History saved:  {history_path}', file=sys.stderr)
" 2>&2)"
        SESSION_SCORES+=("$RUN_SCORE")
    else
        echo "  TIMEOUT (attempt ${attempt}/${MAX_RETRIES}) — no scoring.yaml after ${TIMEOUT_PER_CONFIG}s" >&2
    fi

done  # end retry loop

if [ "$run_success" = "false" ]; then
    echo "" >&2
    echo "Run ${run} FAILED after ${MAX_RETRIES} attempts. Check logs:" >&2
    echo "  Sim:    ${LOG_DIR}/${LOG_SFX}_sim.log" >&2
    echo "  Policy: ${LOG_DIR}/${LOG_SFX}_policy.log" >&2
    echo "  Engine: ${LOG_DIR}/${LOG_SFX}_engine.log" >&2
    SESSION_SCORES+=("0.0")
fi

done  # end run loop

# Step 3: Multi-run summary
if [ "$N_RUNS" -gt 1 ]; then
    echo "" >&2
    echo "=== ${N_RUNS}-Run Summary ===" >&2
    python3 -c "
scores = [float(s) for s in '${SESSION_SCORES[*]}'.split()]
n = len(scores)
avg = sum(scores) / n if n else 0
mn  = min(scores) if scores else 0
mx  = max(scores) if scores else 0
print('', file=__import__('sys').stderr)
import sys
print('  ┌───────┬────────┐', file=sys.stderr)
print('  │  Run  │ Score  │', file=sys.stderr)
print('  ├───────┼────────┤', file=sys.stderr)
for i, s in enumerate(scores, 1):
    print(f'  │  {i:>3}  │ {s:6.2f} │', file=sys.stderr)
print('  ├───────┼────────┤', file=sys.stderr)
print(f'  │   Avg │ {avg:6.2f} │', file=sys.stderr)
print(f'  │   Min │ {mn:6.2f} │', file=sys.stderr)
print(f'  │   Max │ {mx:6.2f} │', file=sys.stderr)
print('  └───────┴────────┘', file=sys.stderr)
" 2>&2
fi

echo "" >&2
echo "=== Done ===" >&2
echo "Results: ${POLICY_RESULTS_DIR}/trial3_only_scoring.yaml" >&2
echo "History: ${POLICY_RESULTS_DIR}/TRIAL3_RESULTS.md" >&2
echo "Logs:    ${LOG_DIR}/trial3_only_{sim,policy,engine}.log" >&2
