# syntax=docker/dockerfile:1.7
# =============================================================================
# FastH3 Omni GPU Worker — RTX PRO 6000 Blackwell (sm_120, 96 GB)
#
# FastVideo (git) + FastH3-OmniRef NVFP4-QAD, 8-step PDD, 24 fps video +
# 32 kHz stereo audio. Device profile rtx-pro-6000: everything resident,
# no AdaLN table, no text-encoder offload.
#
# Build (from this worker/ directory):
#   docker build --build-arg HF_TOKEN=xxx \
#       -t <dockerhub-username>/fasth3-worker:latest .
#
# The image bakes in: CUDA 13.0 + torch 2.12.0, fastvideo-kernel built for
# sm_120 (FP4 attention kernels), flash-attn 2 (prebuilt wheel), the NVFP4-QAD
# model (~69 GB, downloaded at build time) and the composed model directory.
# =============================================================================

ARG CUDA_VERSION=13.0.0
FROM nvidia/cuda:${CUDA_VERSION}-cudnn-devel-ubuntu22.04

# sm_120 = RTX PRO 6000 Blackwell. Build machines have no GPU, so
# fastvideo-kernel is compiled for this arch list instead of probing.
ARG PYTHON_VERSION=3.12
ARG TORCH_CUDA_ARCH_LIST=12.0a
# FastVideo ref to install (git branch/tag). main == v0.2.1 as of Oct 2026.
ARG FASTVIDEO_REF=main
# HF token used only for the build-time model download (repo is public,
# token is optional but recommended to avoid HF rate limits).
ARG HF_TOKEN=
# Set to 0 to skip the build-time model download (download at first boot
# instead, e.g. when the build disk is too small for ~69 GB).
ARG DOWNLOAD_MODELS=1

ENV DEBIAN_FRONTEND=noninteractive \
    CUDA_HOME=/usr/local/cuda \
    PATH=/usr/local/cuda/bin:${PATH} \
    LD_LIBRARY_PATH=/usr/local/cuda/lib64:${LD_LIBRARY_PATH} \
    UV_CACHE_DIR=/opt/uv/cache \
    UV_LINK_MODE=copy \
    UV_TORCH_BACKEND=cu130 \
    PYTHONUNBUFFERED=1

# ---- system packages ----
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl wget ca-certificates ffmpeg \
        libgl1 libglib2.0-0 \
        gcc-11 g++-11 clang-11 cmake pkg-config build-essential libssl-dev \
    && rm -rf /var/lib/apt/lists/* \
    && update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-11 100 \
        --slave /usr/bin/g++ g++ /usr/bin/g++-11

# ---- uv package manager ----
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && echo 'source $HOME/.local/bin/env' >> /root/.bashrc

# ---- FastVideo (editable install; pulls torch 2.12.0 + transformers etc.) ----
WORKDIR /FastVideo
RUN git clone --depth 1 --branch ${FASTVIDEO_REF} \
        https://github.com/hao-ai-lab/FastVideo.git . \
    && echo "# placeholder" > README.md

# bash shell: the RUN steps use `source`, which /bin/sh (dash) lacks.
# Placed here (not earlier) so the apt/uv/clone layers stay Docker-cached.
SHELL ["/bin/bash", "-c"]
RUN source $HOME/.local/bin/env \
    && uv venv --python ${PYTHON_VERSION} --seed /opt/venv \
    && source /opt/venv/bin/activate \
    && uv pip install --upgrade pip \
    && uv pip install -e .

# ---- fastvideo-kernel for sm_120 (FP4 sparse-attention CUDA kernels) ----
RUN source $HOME/.local/bin/env \
    && source /opt/venv/bin/activate \
    && cd fastvideo-kernel \
    && CMAKE_ARGS= TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST} \
        CMAKE_BUILD_PARALLEL_LEVEL=2 ./build.sh --wheel-dir /opt/wheels \
    && cd /FastVideo \
    && uv pip install /opt/wheels/fastvideo_kernel-*.whl \
        --reinstall-package fastvideo-kernel --no-deps

# ---- flash-attn 2 (prebuilt wheel: cu130 + torch 2.12 + cp312 x86_64) ----
RUN source $HOME/.local/bin/env \
    && source /opt/venv/bin/activate \
    && uv pip install \
        "https://github.com/mjun0812/flash-attention-prebuild-wheels/releases/download/v0.9.17/flash_attn-2.8.3+cu130torch2.12-cp312-cp312-linux_x86_64.whl"

# ---- worker application dependencies ----
COPY requirements.txt compose_model.py /worker/
RUN source $HOME/.local/bin/env \
    && source /opt/venv/bin/activate \
    && uv pip install -r /worker/requirements.txt

# ---- model download + compose (build time, no GPU needed) ----
RUN if [ "${DOWNLOAD_MODELS}" = "1" ]; then \
        source /opt/venv/bin/activate \
        && HF_TOKEN=${HF_TOKEN} hf download \
            FastVideo/FastH3-OmniRef-NVFP4-QAD --local-dir /models/export \
        && python /worker/compose_model.py /models/export /models/composed; \
    else \
        echo "DOWNLOAD_MODELS=0 — model will be downloaded at first boot"; \
    fi

# ---- FastH3 Omni device profile: rtx-pro-6000 ----
# Must be set before fastvideo is imported (read at pipeline load time).
# Source: examples/serving/openai_fasth3_omniref_rtx_pro6000.yaml +
# DeviceProfile("rtx-pro-6000") in basic_fasth3_omniref_pdd.py.
ENV FASTVIDEO_ATTENTION_BACKEND=VIDEO_SPARSE_ATTN_H3 \
    FASTVIDEO_H3_VSA_FP4=1 \
    FASTVIDEO_H3_VSA_FP4_PREFIX=fp8 \
    FASTVIDEO_H3_VSA_FP4_TWO_LEVEL_P=1 \
    FASTVIDEO_H3_VSA_FP4_K_SMOOTH=1 \
    FASTVIDEO_H3_GATE_CHUNK_ROWS=8192 \
    FASTVIDEO_MINIMAX_H3_FUSIONS=all \
    FASTVIDEO_VSA_TRITON=1 \
    FASTVIDEO_VSA_PTX_BLACKWELL=0 \
    FASTVIDEO_FA4=0 \
    FASTVIDEO_H3_VAE_TILE_BATCH=8

# ---- worker app ----
COPY handler.py test_input.json /worker/

ENV HOST=0.0.0.0 \
    PORT=8080 \
    MODEL_PATH=/models/composed

EXPOSE 8080

CMD ["bash", "-lc", "source /opt/venv/bin/activate && exec uvicorn handler:app --host ${HOST} --port ${PORT} --workers 1 --timeout-keep-alive 75"]
