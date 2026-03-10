FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    ffmpeg \
    espeak-ng-data \
    libgomp1 \
    libstdc++6 \
    libatomic1 \
    build-essential \
    cmake \
    git \
    pkg-config \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir yt-dlp

# Build whisper.cpp / whisper-cli
RUN git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git /tmp/whisper.cpp && \
    cmake -S /tmp/whisper.cpp -B /tmp/whisper.cpp/build -DWHISPER_FFMPEG=ON && \
    cmake --build /tmp/whisper.cpp/build -j"$(nproc)" --config Release && \
    test -f /tmp/whisper.cpp/build/bin/whisper-cli && \
    cp /tmp/whisper.cpp/build/bin/whisper-cli /usr/local/bin/whisper-cli && \
    chmod +x /usr/local/bin/whisper-cli && \
    rm -rf /tmp/whisper.cpp

RUN mkdir -p /workspace /opt/picobot/models/piper /opt/picobot/models/whisper /opt/picobot/runtime/lib
WORKDIR /workspace

COPY docker/picobot-runtime-bootstrap.sh /usr/local/bin/picobot-runtime-bootstrap
COPY docker/picobot-sandbox-entrypoint.sh /usr/local/bin/picobot-sandbox-entrypoint

RUN chmod +x /usr/local/bin/picobot-runtime-bootstrap /usr/local/bin/picobot-sandbox-entrypoint

ENV PATH="/usr/local/bin:${PATH}"
ENV LD_LIBRARY_PATH="/opt/picobot/runtime/lib:${LD_LIBRARY_PATH:-}"
ENV ESPEAK_DATA_PATH="/opt/picobot/runtime/espeak-ng-data"

ENTRYPOINT ["/usr/local/bin/picobot-sandbox-entrypoint"]
CMD ["sleep", "infinity"]
