#!/usr/bin/env bash
# Setup the aic_eval distrobox container for benchmark runs
# Usage: ./benchmark/scripts/setup_distrobox.sh [--no-gpu] [--rebuild]
#
# Prerequisites:
#   - Docker installed and running (non-root)
#   - distrobox installed (sudo apt install distrobox)
#   - NVIDIA Container Toolkit configured (optional, for GPU support)

set -euo pipefail

IMAGE="ghcr.io/intrinsic-dev/aic/aic_eval:latest"
CONTAINER_NAME="aic_eval"
USE_NVIDIA="true"
REBUILD="false"

for arg in "$@"; do
    case "$arg" in
        --no-gpu)  USE_NVIDIA="false" ;;
        --rebuild) REBUILD="true" ;;
        *)
            echo "Usage: $0 [--no-gpu] [--rebuild]" >&2
            exit 1
            ;;
    esac
done

export DBX_CONTAINER_MANAGER=docker

echo "=== aic_eval Distrobox Setup ==="

# Check prerequisites
if ! command -v docker &>/dev/null; then
    echo "ERROR: docker not found. Install Docker Engine first." >&2
    echo "  https://docs.docker.com/engine/install/" >&2
    exit 1
fi

if ! command -v distrobox &>/dev/null; then
    echo "ERROR: distrobox not found. Install with: sudo apt install distrobox" >&2
    exit 1
fi

if ! docker info &>/dev/null; then
    echo "ERROR: Docker daemon not running or permission denied." >&2
    echo "  Ensure Docker is running and your user is in the docker group." >&2
    exit 1
fi

# Remove existing container if --rebuild
if [ "$REBUILD" = "true" ]; then
    if distrobox list 2>/dev/null | grep -q "$CONTAINER_NAME"; then
        echo "Removing existing ${CONTAINER_NAME} distrobox..."
        distrobox rm -r -f "$CONTAINER_NAME"
    fi
fi

# Check if container already exists
if distrobox list 2>/dev/null | grep -q "$CONTAINER_NAME"; then
    echo "Distrobox '${CONTAINER_NAME}' already exists."
    echo "Use --rebuild to recreate it."
    exit 0
fi

# Pull latest image
echo "Pulling ${IMAGE}..."
docker pull "$IMAGE"

# Create distrobox
echo "Creating distrobox '${CONTAINER_NAME}'..."
DISTROBOX_ARGS=(-r -i "$IMAGE" "$CONTAINER_NAME")
if [ "$USE_NVIDIA" = "true" ]; then
    DISTROBOX_ARGS=(--nvidia "${DISTROBOX_ARGS[@]}")
    echo "  GPU support: enabled (--nvidia)"
else
    echo "  GPU support: disabled (--no-gpu)"
fi
distrobox create "${DISTROBOX_ARGS[@]}"

# Verify container was created
if ! distrobox list 2>/dev/null | grep -q "$CONTAINER_NAME"; then
    echo "ERROR: distrobox creation failed." >&2
    exit 1
fi

# Initialize container (first enter triggers user setup, mounts, etc.)
echo "Initializing container (first enter)... this may take a minute."
distrobox enter -r "$CONTAINER_NAME" -- true

# Verify /entrypoint.sh is accessible
echo "Verifying /entrypoint.sh..."
if distrobox enter -r "$CONTAINER_NAME" -- test -f /entrypoint.sh; then
    echo "  /entrypoint.sh found."
else
    echo "ERROR: /entrypoint.sh not found inside container." >&2
    echo "  The container image may be corrupted. Try: $0 --rebuild" >&2
    exit 1
fi

echo ""
echo "=== Setup Complete ==="
echo "Container: ${CONTAINER_NAME}"
echo ""
echo "Quick test:"
echo "  distrobox enter -r ${CONTAINER_NAME} -- /entrypoint.sh ground_truth:=false start_aic_engine:=false"
echo ""
echo "Run benchmark:"
echo "  ./benchmark/scripts/run_benchmark.sh aic_example_policies.ros.CheatCode --ground-truth"
