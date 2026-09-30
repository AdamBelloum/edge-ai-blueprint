#!/usr/bin/env bash
# Organiser-controlled lifecycle manager for the workshop Flower server.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
WORKSHOP_CONTEXT="$SCRIPT_DIR/workshop-context.sh"
COMMON="$REPOSITORY_ROOT/scripts/lib/common.sh"

readonly FLOWER_SERVICE="fl-workshop-server.service"
readonly ORGANIZER_DROPIN="/etc/systemd/system/fl-workshop-server.service.d/20-organizer-runtime.conf"

usage() {
  cat <<'USAGE'
Usage:
  manage-flower-server.sh [status|start|stop|restart|configure|logs] [OPTIONS]

Actions:
  status                         Show service state, effective configuration, and listener.
  start                          Start a new Flower server run. Refuses when already active.
  stop                           Stop the active Flower server run.
  restart                        Stop any existing run and start a new one.
  configure                      Stop the server and persist the supplied parameters.
  logs                           Show the latest Flower service journal entries.

Options for start, restart, and configure:
  --rounds N                     Number of federated-training rounds; positive integer.
  --min-clients N                Set all three Flower client thresholds to N.
  --defaults                     Use 5 rounds and one required client per active worker.
  -h, --help                     Show this help.

Parameter changes are stored in a systemd drop-in on the control plane.
configure leaves the server stopped. start and restart start it after applying
any supplied parameters. The server always listens on the workshop endpoint
port 8080, as configured for participant JupyterHub pods.
USAGE
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 2
}

require_positive_integer() {
  local label="$1"
  local value="$2"

  [[ "$value" =~ ^[1-9][0-9]*$ ]] ||
    fail "$label must be a positive integer."
  ((value <= 10000)) ||
    fail "$label must not exceed 10000."
}

ACTION="${1:-status}"
case "$ACTION" in
  status|start|stop|restart|configure|logs) shift || true ;;
  -h|--help) usage; exit 0 ;;
  *) fail "Unknown action: $ACTION" ;;
esac

ROUNDS=""
MIN_CLIENTS=""
USE_DEFAULTS=false

while (($#)); do
  case "$1" in
    --rounds)
      ROUNDS="${2:-}"
      require_positive_integer '--rounds' "$ROUNDS"
      shift 2
      ;;
    --min-clients)
      MIN_CLIENTS="${2:-}"
      require_positive_integer '--min-clients' "$MIN_CLIENTS"
      shift 2
      ;;
    --defaults)
      USE_DEFAULTS=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1"
      ;;
  esac
done

if "$USE_DEFAULTS" && [[ -n "$ROUNDS$MIN_CLIENTS" ]]; then
  fail 'Use either --defaults or explicit --rounds and --min-clients, not both.'
fi

case "$ACTION" in
  status|stop|logs)
    [[ -z "$ROUNDS$MIN_CLIENTS" && "$USE_DEFAULTS" == false ]] ||
      fail "$ACTION does not accept parameter options."
    ;;
  configure)
    [[ "$USE_DEFAULTS" == true || ( -n "$ROUNDS" && -n "$MIN_CLIENTS" ) ]] ||
      fail 'configure requires both --rounds and --min-clients, or --defaults.'
    ;;
  start|restart)
    if [[ -n "$ROUNDS$MIN_CLIENTS" ]]; then
      [[ -n "$ROUNDS" && -n "$MIN_CLIENTS" ]] ||
        fail 'Supply both --rounds and --min-clients when changing parameters.'
    fi
    ;;
esac

[[ -r "$WORKSHOP_CONTEXT" ]] ||
  fail "Missing workshop context helper: $WORKSHOP_CONTEXT"
# shellcheck source=workshop-context.sh
source "$WORKSHOP_CONTEXT"
load_workshop_context

[[ -r "$COMMON" ]] || fail "Missing common helper: $COMMON"
# shellcheck source=/dev/null
source "$COMMON"

active_worker_count() {
  local worker_group

  worker_group="$(deployment_worker_group)"
  command -v ansible-inventory >/dev/null 2>&1 ||
    fail 'Required command not found: ansible-inventory.'

  ansible-inventory -i "$DIGITAFRICA_INVENTORY" --list |
    python3 -c '
import json
import sys

inventory = json.load(sys.stdin)
hosts = inventory.get(sys.argv[1], {}).get("hosts", [])
if not isinstance(hosts, list) or len(hosts) < 2:
    raise SystemExit("the active workshop requires at least two worker hosts")
print(len(hosts))
' "$worker_group"
}

if "$USE_DEFAULTS"; then
  MIN_CLIENTS="$(active_worker_count)" ||
    fail 'Could not derive the active worker count from the workshop inventory.'
  ROUNDS="5"
fi

apply_parameters() {
  local rounds="$1"
  local min_clients="$2"

  printf 'Stopping Flower server before applying parameters...\n'
  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
systemctl stop "$FLOWER_SERVICE" || true
systemctl reset-failed "$FLOWER_SERVICE" >/dev/null 2>&1 || true
install -d -m 0755 /etc/systemd/system/fl-workshop-server.service.d
cat > "$ORGANIZER_DROPIN" <<'DROPIN'
[Service]
Environment=NUM_ROUNDS=$rounds
Environment=MIN_FIT_CLIENTS=$min_clients
Environment=MIN_AVAILABLE_CLIENTS=$min_clients
Environment=MIN_EVALUATE_CLIENTS=$min_clients
DROPIN
chmod 0644 "$ORGANIZER_DROPIN"
systemctl daemon-reload
printf 'Applied Flower parameters: rounds=%s, required_clients=%s\\n' "$rounds" "$min_clients"
REMOTE
)"
}

start_server() {
  run_deployment_remote "$(cat <<'REMOTE'
set -euo pipefail

if systemctl is-active --quiet fl-workshop-server.service; then
  echo 'Flower server is already active; use restart to begin a new run.' >&2
  exit 2
fi

systemctl reset-failed fl-workshop-server.service >/dev/null 2>&1 || true
systemctl start fl-workshop-server.service

for _ in {1..15}; do
  if systemctl is-active --quiet fl-workshop-server.service &&
     ss -ltnH | awk '{print $4}' | grep -Eq '(^|:)8080$'; then
    echo 'Flower server is active and listening on TCP port 8080.'
    exit 0
  fi
  sleep 1
done

echo 'Flower server did not become active and listen on TCP port 8080.' >&2
systemctl --no-pager --full status fl-workshop-server.service >&2 || true
journalctl --no-pager -u fl-workshop-server.service -n 50 >&2 || true
exit 1
REMOTE
)"
}

stop_server() {
  run_deployment_remote "$(cat <<'REMOTE'
set -euo pipefail
systemctl stop fl-workshop-server.service || true
systemctl reset-failed fl-workshop-server.service >/dev/null 2>&1 || true

if systemctl is-active --quiet fl-workshop-server.service; then
  echo 'Flower server remains active after stop request.' >&2
  exit 1
fi

if ss -ltnH | awk '{print $4}' | grep -Eq '(^|:)8080$'; then
  echo 'TCP port 8080 remains in use after Flower server stop.' >&2
  ss -ltnp '( sport = :8080 )' >&2 || true
  exit 1
fi

echo 'Flower server is stopped and TCP port 8080 is free.'
REMOTE
)"
}

show_status() {
  run_deployment_remote "$(cat <<'REMOTE'
set -euo pipefail
echo '===== Flower service state ====='
systemctl show fl-workshop-server.service \
  -p ActiveState \
  -p SubState \
  -p ActiveEnterTimestamp \
  -p ExecMainStartTimestamp \
  -p MainPID \
  -p UnitFileState \
  -p Restart \
  -p Environment

echo '===== Organiser parameter override ====='
if [[ -r /etc/systemd/system/fl-workshop-server.service.d/20-organizer-runtime.conf ]]; then
  cat /etc/systemd/system/fl-workshop-server.service.d/20-organizer-runtime.conf
else
  echo 'No organiser override exists; Ansible-rendered service defaults apply.'
fi

echo '===== TCP port 8080 ====='
ss -ltnp '( sport = :8080 )' || true
REMOTE
)"
}

show_logs() {
  run_deployment_remote "$(cat <<'REMOTE'
set -euo pipefail
journalctl --no-pager -u fl-workshop-server.service -n 100
REMOTE
)"
}

case "$ACTION" in
  status)
    show_status
    ;;
  logs)
    show_logs
    ;;
  stop)
    stop_server
    ;;
  configure)
    apply_parameters "$ROUNDS" "$MIN_CLIENTS"
    printf 'Flower parameters were updated; the server remains stopped.\n'
    ;;
  start)
    if [[ -n "$ROUNDS" ]]; then
      apply_parameters "$ROUNDS" "$MIN_CLIENTS"
    fi
    start_server
    ;;
  restart)
    if [[ -n "$ROUNDS" ]]; then
      apply_parameters "$ROUNDS" "$MIN_CLIENTS"
    else
      stop_server
    fi
    start_server
    ;;
esac
