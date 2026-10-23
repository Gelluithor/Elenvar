#!/usr/bin/env bash
# Elenvar demo with simulated NVRs.
#   dev/demo.sh        starts the demo (http://localhost:8080)
#   dev/demo.sh down   stops the demo and deletes its data
set -euo pipefail
cd "$(dirname "$0")/.."

export COMPOSE_PROJECT_NAME=elenvar-demo
compose() { docker compose -f docker-compose.yml -f dev/docker-compose.demo.yml "$@"; }
PORT="${ELENVAR_DEMO_PORT:-8080}"

case "${1:-up}" in
  up)
    echo "Building and starting the demo…"
    compose up -d --build
    echo "Waiting for the app to start…"
    for _ in $(seq 1 60); do
      if compose exec -T app python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)" >/dev/null 2>&1; then
        break
      fi
      sleep 2
    done
    echo "Loading sample data…"
    compose exec -T app python - < dev/demo_seed.py
    cat <<INFO

  Demo is running:   http://localhost:${PORT}

  Administrator   admin     / Elenvar-Demo-2026
  Operator        jnovak    / Operator-Demo-2026      (changes the password at first sign-in)
  Viewer          recepce   / Pozorovatel-Demo-2026   (changes the password at first sign-in)

  Mandatory 2FA is off in the demo – you can turn it on in Settings.
  Stop the demo and delete its data:  dev/demo.sh down
INFO
    ;;
  down)
    compose down -v
    ;;
  *)
    echo "Usage: dev/demo.sh [up|down]" >&2
    exit 1
    ;;
esac
