#!/usr/bin/env bash
# Demo Elenvar se simulovanými NVR.
#   dev/demo.sh        spustí demo (http://localhost:8080)
#   dev/demo.sh down   zastaví demo a smaže jeho data
set -euo pipefail
cd "$(dirname "$0")/.."

export COMPOSE_PROJECT_NAME=elenvar-demo
compose() { docker compose -f docker-compose.yml -f dev/docker-compose.demo.yml "$@"; }
PORT="${ELENVAR_DEMO_PORT:-8080}"

case "${1:-up}" in
  up)
    echo "Sestavuji a spouštím demo…"
    compose up -d --build
    echo "Čekám na start aplikace…"
    for _ in $(seq 1 60); do
      if compose exec -T app python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)" >/dev/null 2>&1; then
        break
      fi
      sleep 2
    done
    echo "Nahrávám ukázková data…"
    compose exec -T app python - < dev/demo_seed.py
    cat <<INFO

  Demo běží:   http://localhost:${PORT}

  Administrátor   admin     / Elenvar-Demo-2026
  Operátor        jnovak    / Operator-Demo-2026   (při prvním přihlášení změní heslo)
  Pozorovatel     recepce   / Pozorovatel-Demo-2026    (při prvním přihlášení změní heslo)

  V demu je vypnuté povinné 2FA – zapnout ho můžete v Nastavení.
  Ukončení a smazání dat demo:  dev/demo.sh down
INFO
    ;;
  down)
    compose down -v
    ;;
  *)
    echo "Použití: dev/demo.sh [up|down]" >&2
    exit 1
    ;;
esac
