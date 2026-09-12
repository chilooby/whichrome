#!/usr/bin/env bash
# Re-capture the real output that scripts/make-demo-gif.py renders.
# Uses a throwaway registry of EXAMPLE accounts and the WHICHROME_HOSTNAME /
# WHICHROME_DEVICE_KEY overrides, so a public GIF never shows a real machine.
set -euo pipefail
cd "$(dirname "$0")/.."
export WHICHROME_REGISTRY="${WHICHROME_REGISTRY:-./.demo-registry.json}"
export WHICHROME_HOSTNAME=DESKPC
export WHICHROME_DEVICE_KEY="DESKPC|11111111-2222-3333-4444-555555555555"
python bin/whichrome.py roster --connected "${1:-./.demo-connected.json}"
python bin/whichrome.py resolve cyborg --quiet
python bin/whichrome.py beacon start --port 8803 --nonce ctest --seconds 30 &
sleep 2
curl -s "http://127.0.0.1:8803/ctest" >/dev/null    # stands in for the browser
sleep 1
python bin/whichrome.py beacon check --nonce ctest --port 8803 || true
