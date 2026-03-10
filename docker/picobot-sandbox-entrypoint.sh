#!/usr/bin/env bash
set -euo pipefail

if [ "${PICO_BOOTSTRAP_TOOLS:-0}" = "1" ]; then
  /usr/local/bin/picobot-runtime-bootstrap
fi

exec "$@"
