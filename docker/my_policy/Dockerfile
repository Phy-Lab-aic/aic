# my_policy submission image — π0.5 PI05Policy via lerobot 0.4.3.
#
# Layered on the same ros:kilted-ros-core + pixi base as docker/aic_model so
# that aic_model framework + lerobot 0.4.3 (already pinned in pixi.toml) are
# available without extra installs.
#
# Build expects context = workspace/src/aic (same as aic_model image).
#
# Build args:
#   PI05_CKPT_HOST_PATH  — host path of converted lerobot checkpoint
#                          (default: ../../models/pi05_ur5e_lerobot relative
#                          to the build context). Layout:
#                            <PI05_CKPT_HOST_PATH>/
#                              ├ model.safetensors
#                              ├ config.json
#                              └ norm_stats/
#
# Runtime env:
#   AIC_ROUTER_ADDR=<host:7447>  Zenoh router (required, see aic_model)
#   AIC_ENABLE_ACL / AIC_MODEL_PASSWD  Optional ACL passthrough
#   PI05_CKPT=/models/pi05_ur5e_lerobot  Checkpoint dir inside the image

FROM docker.io/library/ros:kilted-ros-core AS build

RUN apt update && apt install -y git && curl -fsSL https://pixi.sh/install.sh | bash
ENV PATH="/root/.pixi/bin:$PATH"

# AIC sources — identical to docker/aic_model/Dockerfile so any changes there
# stay in lockstep.
COPY aic_example_policies /ws_aic/src/aic/aic_example_policies
COPY aic_model /ws_aic/src/aic/aic_model
COPY aic_interfaces /ws_aic/src/aic/aic_interfaces
COPY aic_utils /ws_aic/src/aic/aic_utils
COPY pixi.toml pixi.lock /ws_aic/src/aic/
COPY pixi_env_setup.sh /ws_aic/src/aic/

SHELL ["/bin/bash", "-c"]

# Resolve pixi env (lerobot==0.4.3 + huggingface_hub already pinned).
RUN --mount=type=cache,target=/root/.cache/rattler/cache \
    --mount=type=cache,target=/ws_aic/src/aic/.pixi/build \
    cd /ws_aic/src/aic && pixi install --locked

# B5 — pre-cache the paligemma tokenizer so first AIC trial does not race a
# 5MB HuggingFace download against the 180s timeout. Tokenizer assets only
# (~5MB), no model weights pulled.
ENV HF_HOME=/opt/hf_cache
RUN --mount=type=cache,target=/root/.cache/rattler/cache \
    cd /ws_aic/src/aic && pixi run --as-is python -c "\
from transformers import AutoTokenizer; \
AutoTokenizer.from_pretrained('google/paligemma-3b-pt-224')"

# Converted lerobot checkpoint. Build context expectation:
#   <build context>/../models/pi05_ur5e_lerobot   ← produced by Phase 3.7
# Adjust the COPY src to wherever the conversion output is staged.
ARG PI05_CKPT_HOST_PATH=../models/pi05_ur5e_lerobot
COPY ${PI05_CKPT_HOST_PATH} /models/pi05_ur5e_lerobot
ENV PI05_CKPT=/models/pi05_ur5e_lerobot

WORKDIR /ws_aic/src/aic

COPY --chmod=755 <<"EOF" /entrypoint.sh
#!/bin/bash
set -e

export RMW_IMPLEMENTATION=rmw_zenoh_cpp

if [[ -z "$AIC_ROUTER_ADDR" ]]; then
  echo "AIC_ROUTER_ADDR must be provided"
  exit 1
fi

should_enable_acl() {
  [[ "$AIC_ENABLE_ACL" == "true" || "$AIC_ENABLE_ACL" == "1" ]]
}

if should_enable_acl; then
  if [[ ! (-n "$AIC_MODEL_PASSWD" ) ]]; then
    echo "AIC_MODEL_PASSWD must be provided"
    exit 1
  fi
  echo "model:$AIC_MODEL_PASSWD" >> /credentials.txt
fi

ZENOH_CONFIG_OVERRIDE='connect/endpoints=["tcp/'"$AIC_ROUTER_ADDR"'"]'
ZENOH_CONFIG_OVERRIDE+=';transport/shared_memory/enabled=false'
if should_enable_acl; then
  ZENOH_CONFIG_OVERRIDE+=';transport/auth/usrpwd/user="model"'
  ZENOH_CONFIG_OVERRIDE+=';transport/auth/usrpwd/password="'"$AIC_MODEL_PASSWD"'"'
  ZENOH_CONFIG_OVERRIDE+=';transport/auth/usrpwd/dictionary_file="/credentials.txt"'
fi
export ZENOH_CONFIG_OVERRIDE
echo "ZENOH_CONFIG_OVERRIDE=$ZENOH_CONFIG_OVERRIDE"
echo "PI05_CKPT=$PI05_CKPT"
exec pixi run --as-is ros2 run aic_model aic_model "$@"
EOF

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--ros-args", "-p", "policy:=aic_example_policies.ros.MyPi05Policy"]
