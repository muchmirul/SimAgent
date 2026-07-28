#!/usr/bin/env bash
# One command to open a fully configured SimAgent notebook.
#
# Why this exists: the notebook server loads Python once when it starts, so a
# server left running for days keeps executing that day's code and fails in
# ways that look like broken code. This always starts from a killed process,
# a pi runtime that matches its source, and a URL with the run controls
# already set.
#
# It sets up the session but never picks the problem: that choice is yours,
# in the dropdown. Override anything from the environment:
#   PORT=8700 THINKING=high TURNS=60 ./start.sh
#   PROBLEM=circumcenter-in-triangle ./start.sh   # only if you want it preset
#   MODEL=openai-codex/gpt-5.6-sol ./start.sh
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8642}"
# No default problem on purpose: WHICH problem to work on is the user's choice,
# not the launcher's. Empty leaves the dropdown on "choose a bundled problem".
PROBLEM="${PROBLEM:-}"
THINKING="${THINKING:-max}"
TURNS="${TURNS:-40}"
MODEL="${MODEL:-}"   # empty means: let pi route its first authenticated model

if [ ! -x .venv/bin/simagent ]; then
  echo "no .venv here. Install first:" >&2
  echo "  uv venv .venv && uv pip install -p .venv/bin/python -e '.[dev]'" >&2
  exit 1
fi

# 1. No stale server. An old process runs old code, whatever the files say.
pkill -f "simagent web" 2>/dev/null || true

# 2. The pi runtime must match its source, or the model talks to an old kernel.
if [ ! -f agent/dist/cli.js ] ||
   [ -n "$(find agent/src -name '*.ts' -newer agent/dist/cli.js -print -quit)" ]; then
  echo "building the pi runtime (agent/src changed)..."
  (cd agent && PI_OFFLINE=1 npm run build)
fi

# 3. Say plainly if no model can be routed, rather than failing at Run agent.
if [ ! -f "$HOME/.pi/agent/auth.json" ]; then
  echo "WARNING: pi has no authenticated provider, so 'Run agent' will fail."
  echo "         Bundled problems still solve without any model, for example:"
  echo "           .venv/bin/simagent solve circumcenter-in-tetrahedron"
  echo "         To fix: (cd agent && npx pi)   then /login inside pi"
fi

URL="http://localhost:${PORT}/?thinking=${THINKING}&turns=${TURNS}"
[ -n "$PROBLEM" ] && URL="${URL}&problem=${PROBLEM}"
[ -n "$MODEL" ] && URL="${URL}&model=${MODEL}"

.venv/bin/simagent web --port "$PORT" --no-browser &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT INT TERM

# 4. Open the browser only once the server answers, so the page is never blank.
for _ in $(seq 1 60); do
  if curl -sf "http://localhost:${PORT}/api/problems" >/dev/null 2>&1; then break; fi
  sleep 0.25
done

echo "SimAgent notebook: $URL"
echo "problem=${PROBLEM:-yours to pick in the dropdown}  thinking=$THINKING  turns=$TURNS"
echo "model=${MODEL:-first authenticated model}"
echo "Ctrl-C stops the server."
xdg-open "$URL" >/dev/null 2>&1 || true

wait $SERVER
