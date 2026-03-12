FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    ffmpeg \
    jq \
    xz-utils \
    git \
    build-essential \
    cmake \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir yt-dlp

# Piper runtime
RUN curl -L -o /tmp/piper.tar.gz \
      "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz" && \
    mkdir -p /opt/picobot/tools && \
    tar -xzf /tmp/piper.tar.gz -C /opt/picobot/tools && \
    rm -f /tmp/piper.tar.gz && \
    ln -sf /opt/picobot/tools/piper/piper /usr/local/bin/piper

# whisper.cpp runtime
RUN git clone --depth 1 https://github.com/ggml-org/whisper.cpp /tmp/whisper.cpp && \
    cmake -S /tmp/whisper.cpp -B /tmp/whisper.cpp/build -DCMAKE_BUILD_TYPE=Release && \
    cmake --build /tmp/whisper.cpp/build -j"$(nproc)" && \
    mkdir -p /opt/picobot/tools/whisper/lib && \
    (install /tmp/whisper.cpp/build/bin/whisper-cli /usr/local/bin/whisper || \
     install /tmp/whisper.cpp/build/bin/main /usr/local/bin/whisper) && \
    find /tmp/whisper.cpp/build -type f \( -name "libwhisper.so*" -o -name "libggml*.so*" \) -exec cp {} /opt/picobot/tools/whisper/lib/ \; && \
    cp /opt/picobot/tools/whisper/lib/libwhisper.so* /usr/local/lib/ 2>/dev/null || true && \
    cp /opt/picobot/tools/whisper/lib/libggml*.so* /usr/local/lib/ 2>/dev/null || true && \
    ldconfig && \
    rm -rf /tmp/whisper.cpp

ENV LD_LIBRARY_PATH=/opt/picobot/tools/whisper/lib:/usr/local/lib

RUN mkdir -p /opt/picobot/models/piper /opt/picobot/models/whisper

# Piper voices
RUN curl -L -o /opt/picobot/models/piper/it_IT-paola-medium.onnx \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx" && \
    curl -L -o /opt/picobot/models/piper/it_IT-paola-medium.onnx.json \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx.json" && \
    curl -L -o /opt/picobot/models/piper/en_US-lessac-medium.onnx \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx" && \
    curl -L -o /opt/picobot/models/piper/en_US-lessac-medium.onnx.json \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json" && \
    curl -L -o /opt/picobot/models/piper/en_US-amy-medium.onnx \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx" && \
    curl -L -o /opt/picobot/models/piper/en_US-amy-medium.onnx.json \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json" && \
    curl -L -o /opt/picobot/models/piper/en_US-ryan-high.onnx \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx" && \
    curl -L -o /opt/picobot/models/piper/en_US-ryan-high.onnx.json \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx.json" && \
    curl -L -o /opt/picobot/models/piper/it_IT-aurora-medium.onnx \
      "https://huggingface.co/kirys79/piper_italiano/resolve/main/Aurora/it_IT-aurora-medium.onnx" && \
    curl -L -o /opt/picobot/models/piper/it_IT-aurora-medium.onnx.json \
      "https://huggingface.co/kirys79/piper_italiano/resolve/main/Aurora/it_IT-aurora-medium.onnx.json"

# Whisper model for whisper.cpp
RUN curl -L -o /opt/picobot/models/whisper/ggml-small.bin \
      "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"

# Runtime bootstrap command expected by tools-bootstrap
RUN cat > /usr/local/bin/picobot-runtime-bootstrap <<'SH' && chmod +x /usr/local/bin/picobot-runtime-bootstrap
#!/usr/bin/env bash
set -euo pipefail

command -v yt-dlp >/dev/null
command -v ffmpeg >/dev/null
command -v piper >/dev/null
command -v whisper >/dev/null

test -f /opt/picobot/models/piper/it_IT-paola-medium.onnx
test -f /opt/picobot/models/whisper/ggml-small.bin

echo "picobot runtime bootstrap OK"
SH

RUN mkdir -p /workspace
WORKDIR /workspace
