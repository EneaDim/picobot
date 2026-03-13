FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIPER_VERSION=2023.11.14-2
ENV WHISPER_CPP_TAG=v1.7.4
ENV LD_LIBRARY_PATH=/opt/piper/lib:${LD_LIBRARY_PATH:-}

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
    pkg-config \
    alsa-utils \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir yt-dlp

# Piper runtime
RUN curl -L -o /tmp/piper.tar.gz \
      "https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_linux_x86_64.tar.gz" && \
    mkdir -p /opt/piper && \
    tar -xzf /tmp/piper.tar.gz -C /opt/piper --strip-components=1 && \
    ln -sf /opt/piper/piper /usr/local/bin/piper && \
    chmod +x /usr/local/bin/piper && \
    rm -f /tmp/piper.tar.gz

# whisper.cpp
RUN git clone --depth 1 --branch ${WHISPER_CPP_TAG} https://github.com/ggerganov/whisper.cpp /opt/whisper.cpp && \
    cmake -S /opt/whisper.cpp -B /opt/whisper.cpp/build && \
    cmake --build /opt/whisper.cpp/build -j"$(nproc)" && \
    if [ -x /opt/whisper.cpp/build/bin/whisper-cli ]; then \
        ln -sf /opt/whisper.cpp/build/bin/whisper-cli /usr/local/bin/whisper-cli; \
        ln -sf /opt/whisper.cpp/build/bin/whisper-cli /usr/local/bin/whisper; \
    elif [ -x /opt/whisper.cpp/build/bin/main ]; then \
        ln -sf /opt/whisper.cpp/build/bin/main /usr/local/bin/whisper-cli; \
        ln -sf /opt/whisper.cpp/build/bin/main /usr/local/bin/whisper; \
    elif [ -x /opt/whisper.cpp/build/main ]; then \
        ln -sf /opt/whisper.cpp/build/main /usr/local/bin/whisper-cli; \
        ln -sf /opt/whisper.cpp/build/main /usr/local/bin/whisper; \
    else \
        echo "whisper executable not found after build" >&2; \
        exit 1; \
    fi && \
    chmod +x /usr/local/bin/whisper /usr/local/bin/whisper-cli

# Models
RUN mkdir -p /opt/picobot/models/piper /opt/picobot/models/whisper

# Piper voices
RUN curl -L -o /opt/picobot/models/piper/it_IT-paola-medium.onnx \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx" && \
    curl -L -o /opt/picobot/models/piper/it_IT-paola-medium.onnx.json \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx.json" && \
    curl -L -o /opt/picobot/models/piper/it_IT-aurora-medium.onnx \
      "https://huggingface.co/kirys79/piper_italiano/resolve/main/Aurora/it_IT-aurora-medium.onnx" && \
    curl -L -o /opt/picobot/models/piper/it_IT-aurora-medium.onnx.json \
      "https://huggingface.co/kirys79/piper_italiano/resolve/main/Aurora/it_IT-aurora-medium.onnx.json" && \
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
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx.json"

# Whisper model
RUN curl -L -o /opt/picobot/models/whisper/ggml-small.bin \
      "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"

COPY docker/picobot-runtime-bootstrap.sh /usr/local/bin/picobot-runtime-bootstrap
COPY docker/picobot-sandbox-entrypoint.sh /usr/local/bin/picobot-sandbox-entrypoint
RUN chmod +x /usr/local/bin/picobot-runtime-bootstrap /usr/local/bin/picobot-sandbox-entrypoint

RUN mkdir -p /workspace
WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/picobot-sandbox-entrypoint"]
CMD ["sleep", "infinity"]
