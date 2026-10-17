#!/usr/bin/env bash
# Crux Studio — start everything with one command.
#   ./run.sh          start (Redis, Temporal, Celery, Temporal worker, API + editor) and open the browser
#   ./run.sh stop     stop all services
#   ./run.sh status   health of every component
#   ./run.sh test     backend smoke test + browser E2E of the editor
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
RUN="$ROOT/.run"; LOGS="$ROOT/logs"; VENV="$ROOT/.venv"
URL="http://localhost:8787"
mkdir -p "$RUN" "$LOGS"

c_ok() { printf "\033[32m✓\033[0m %s\n" "$*"; }
c_step() { printf "\033[38;5;202m▸\033[0m %s\n" "$*"; }
die() { printf "\033[31m✗ %s\033[0m\n" "$*" >&2; exit 1; }

start_bg() { # name, command...
  local name=$1; shift
  if [ -f "$RUN/$name.pid" ] && kill -0 "$(cat "$RUN/$name.pid")" 2>/dev/null; then return 0; fi
  nohup "$@" > "$LOGS/$name.log" 2>&1 &
  echo $! > "$RUN/$name.pid"
}

stop_all() {
  for n in api worker celery temporal redis; do
    if [ -f "$RUN/$n.pid" ]; then kill "$(cat "$RUN/$n.pid")" 2>/dev/null || true; rm -f "$RUN/$n.pid"; fi
  done
  pkill -f "crux.workflows.worker" 2>/dev/null || true
  pkill -f "celery -A crux.tasks" 2>/dev/null || true
  pkill -f "uvicorn crux.api.main" 2>/dev/null || true
  return 0
}

wait_for() { # url, label, seconds
  local t=0
  until curl -sf -o /dev/null "$1"; do
    sleep 1; t=$((t+1))
    if [ "$t" -ge "$3" ]; then die "$2 did not start (see logs/)"; fi
  done
  return 0
}

case "${1:-start}" in
  stop) stop_all; c_ok "all services stopped"; exit 0 ;;
  status) curl -s "$URL/api/health" && echo; exit 0 ;;
  test) "$VENV/bin/python" scripts/smoke_test.py all && "$VENV/bin/python" tests/e2e_studio.py all; exit $? ;;
  start) ;;
  *) die "usage: ./run.sh [start|stop|status|test]" ;;
esac

# ---------------------------------------------------------------- prerequisites
[ -f .env ] || die ".env missing — copy .env.example to .env and add your keys"
for bin in python3 node npm redis-server temporal potrace; do
  command -v "$bin" >/dev/null || die "missing '$bin' (macOS: brew install ${bin/redis-server/redis})"
done

# ---------------------------------------------------------------- python + editor
if [ ! -x "$VENV/bin/python" ]; then c_step "creating Python env"; python3 -m venv "$VENV"; fi
if [ ! -f "$RUN/.deps" ] || [ backend/requirements.txt -nt "$RUN/.deps" ]; then
  c_step "installing Python deps"; "$VENV/bin/pip" install -q -r backend/requirements.txt
  "$VENV/bin/playwright" install chromium >/dev/null; touch "$RUN/.deps"
fi
if [ ! -d editor/node_modules ]; then c_step "installing editor deps"; (cd editor && npm install --silent); fi
c_step "building Crux Studio"; (cd editor && npm run build >/dev/null) || die "editor build failed"

# ---------------------------------------------------------------- services
c_step "starting Redis, Temporal, Celery, worker and API"
start_bg redis redis-server --port 6390 --bind 127.0.0.1 --save "" --appendonly no
start_bg temporal temporal server start-dev --db-filename "$RUN/temporal.db" --port 7233 --ui-port 8233 --log-level warn
wait_for "http://localhost:8233" "Temporal" 60
cd backend
start_bg celery "$VENV/bin/celery" -A crux.tasks.app:celery_app worker --pool threads --concurrency 24 --loglevel INFO
start_bg worker "$VENV/bin/python" -m crux.workflows.worker
start_bg api "$VENV/bin/uvicorn" crux.api.main:app --host 127.0.0.1 --port 8787
cd "$ROOT"
wait_for "$URL/api/health" "API" 60

# ---------------------------------------------------------------- brand kit
if ! (cd backend && "$VENV/bin/python" -c "import sys; from crux.brand.ingest import catalog_is_fresh; sys.exit(0 if catalog_is_fresh() else 1)"); then
  c_step "analysing the brand kit with AI (first run, ~1 min)"
  (cd backend && "$VENV/bin/python" -m crux.brand.ingest > "$LOGS/ingest.log" 2>&1) || die "brand ingestion failed (logs/ingest.log)"
fi

echo
c_ok "Crux Studio is running"
cat <<INFO
   Landing       $URL
   Studio        $URL/studio
   API health    $URL/api/health
   Temporal UI   http://localhost:8233
   Logs          $LOGS/
   Stop          ./run.sh stop
INFO
command -v open >/dev/null && open "$URL" >/dev/null 2>&1 || true
