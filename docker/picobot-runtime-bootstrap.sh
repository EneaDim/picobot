#!/usr/bin/env bash
set -euo pipefail

PICO_PIPER_VOICES="${PICO_PIPER_VOICES:-it_IT-paola-medium,it_IT-aurora-medium,en_US-lessac-medium,en_US-amy-medium,en_US-ryan-high}"
PICO_PIPER_CUSTOM_VOICE_URLS="${PICO_PIPER_CUSTOM_VOICE_URLS:-{}}"
PICO_BOOTSTRAP_TOOLS="${PICO_BOOTSTRAP_TOOLS:-0}"

mkdir -p /opt/picobot/models/piper
mkdir -p /opt/picobot/models/whisper
mkdir -p /opt/picobot/runtime

download() {
  local url="$1"
  local dest="$2"
  if [ ! -f "$dest" ]; then
    curl -L --fail --retry 3 -o "$dest" "$url"
  fi
}

voice_url_base() {
  local voice="$1"
  IFS='-' read -r locale rest <<< "$voice"
  local quality="${voice##*-}"
  local speaker="${voice#${locale}-}"
  speaker="${speaker%-${quality}}"
  local lang="${locale%%_*}"
  echo "https://huggingface.co/rhasspy/piper-voices/resolve/main/${lang}/${locale}/${speaker}/${quality}/${voice}.onnx"
}

custom_voice_urls() {
  local voice="$1"
  python - <<'PY' "$voice"
import json
import os
import sys

voice = sys.argv[1]
raw = os.environ.get("PICO_PIPER_CUSTOM_VOICE_URLS", "{}")
try:
    data = json.loads(raw)
except Exception:
    data = {}

entry = data.get(voice) or {}
onnx = str(entry.get("onnx") or "").strip()
js = str(entry.get("json") or "").strip()

print(onnx)
print(js)
PY
}

install_piper_voices() {
  IFS=',' read -r -a voices <<< "$PICO_PIPER_VOICES"
  for voice in "${voices[@]}"; do
    voice="$(echo "$voice" | xargs)"
    [ -z "$voice" ] && continue

    local onnx_url=""
    local json_url=""

    mapfile -t lines < <(custom_voice_urls "$voice")
    if [ "${#lines[@]}" -ge 2 ] && [ -n "${lines[0]}" ] && [ -n "${lines[1]}" ]; then
      onnx_url="${lines[0]}"
      json_url="${lines[1]}"
    else
      local base
      base="$(voice_url_base "$voice")"
      onnx_url="$base"
      json_url="${base}.json"
    fi

    echo "[bootstrap] installing Piper voice: $voice"
    download "$onnx_url" "/opt/picobot/models/piper/${voice}.onnx"
    download "$json_url" "/opt/picobot/models/piper/${voice}.onnx.json"
  done
}

install_whisper_model() {
  download \
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin" \
    "/opt/picobot/models/whisper/ggml-small.bin"
}

verify_runtime() {
  command -v yt-dlp >/dev/null 2>&1
  command -v ffmpeg >/dev/null 2>&1
  command -v piper >/dev/null 2>&1
  command -v whisper >/dev/null 2>&1
  command -v whisper-cli >/dev/null 2>&1
  test -f /opt/picobot/models/whisper/ggml-small.bin
}

if [ "$PICO_BOOTSTRAP_TOOLS" = "1" ]; then
  install_piper_voices
  install_whisper_model
  verify_runtime
fi
