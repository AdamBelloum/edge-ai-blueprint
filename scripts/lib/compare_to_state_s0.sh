#!/usr/bin/env bash
# compare_state.sh — Compare live infrastructure state against S0 baseline.
# Usage: bash scripts/lib/compare_state.sh [inventory]
# Resolves all paths relative to the repository root (two levels up from scripts/lib/).

set -uo pipefail   # NOTE: no -e; remote() uses || true to handle grep/empty safely

INVENTORY="${1:-inventories/workshop/tier2/hosts.ini}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SECRETS_DIR="${REPO_ROOT}/secrets/workshops"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; RESET='\033[0m'
ok()   { echo -e "${GREEN}  ✅ MATCH  ${RESET} $*"; }
fail() { echo -e "${RED}  ❌ DIFFER ${RESET} $*"; }
warn() { echo -e "${YELLOW}  ⚠️  SKIP   ${RESET} $*"; }
hdr()  { echo -e "\n── $* ──────────────────────────────────────────────────"; }

PASS=0; FAIL=0; SKIP=0

check() {
  local label="$1" expected="$2" actual="$3" mode="${4:-exact}"
  actual="$(printf '%s' "$actual" | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  case "$mode" in
    exact)
      if [[ "$actual" == "$expected" ]]; then
        ok "$label"; (( PASS++ )) || true
      else
        fail "$label  (expected: '$expected', got: '$actual')"; (( FAIL++ )) || true
      fi ;;
    accept)
      local matched=false
      IFS='|' read -ra vals <<< "$expected"
      for v in "${vals[@]}"; do [[ "$actual" == "$v" ]] && matched=true && break; done
      if $matched; then ok "$label"; (( PASS++ )) || true
      else fail "$label  (accepted: '$expected', got: '$actual')"; (( FAIL++ )) || true; fi ;;
    integer)
      if [[ "$actual" =~ ^[1-9][0-9]*$ ]]; then
        ok "$label ($actual)"; (( PASS++ )) || true
      else
        fail "$label  (expected positive integer, got: '$actual')"; (( FAIL++ )) || true
      fi ;;
  esac
}

skip() { warn "$1  — $2"; (( SKIP++ )) || true; }

# Run one shell command on tier2_server; print Ansible noise to stderr; return stdout only.
remote() {
  local cmd="$1"
  local raw
  raw=$(ansible tier2_server -i "$INVENTORY" -b -m shell -a "$cmd" -v 2>&1) || true
  # Extract the "stdout" field value from Ansible -v JSON-like output
  printf '%s' "$raw" \
    | grep '"stdout":' \
    | sed 's/.*"stdout": "//; s/", "stdout_lines".*//' \
    | sed 's/\\n/\n/g; s/\\r//g; s/\\t/\t/g' \
    | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' \
    || true
}

# Run one command on a single host; same stdout extraction as remote().
remote_on() {
  local target="$1" cmd="$2" raw
  raw=$(ansible "$target" -i "$INVENTORY" -m shell -a "$cmd" -v </dev/null 2>&1) || true
  printf '%s' "$raw" \
    | grep '"stdout":' \
    | sed 's/.*"stdout": "//; s/", "stdout_lines".*//' \
    | sed 's/\\n/\n/g; s/\\r//g; s/\\t/\t/g' \
    || true
}

# Print the lines of $2 between "##NAME" ($1) and the next "##" marker.
section() {
  printf '%s\n' "$2" | awk -v s="##$1" '$0==s{f=1;next} /^##/{f=0} f' | sed '/^[[:space:]]*$/d'
}

# Pass when content is empty; otherwise fail and show what was found.
expect_empty() {
  local label="$1" content="$2"
  if [[ -z "$content" ]]; then
    ok "$label"; (( PASS++ )) || true
  else
    fail "$label — found:"; printf '%s\n' "$content" | sed 's/^/        /'; (( FAIL++ )) || true
  fi
}

info() { echo -e "  ℹ️  INFO   $*"; }

# Read-only worker probe (no Jinja templates; markers delimit sections).
WORKER_PROBE='if docker info >/dev/null 2>&1; then echo "##STATE"; echo docker-ok; echo "##CONTAINERS"; docker ps -a | tail -n +2; echo "##VOLUMES"; docker volume ls -q; echo "##NETWORKS"; docker network ls --filter type=custom | tail -n +2; echo "##IMAGES"; docker images | tail -n +2; else echo "##STATE"; echo docker-unavailable; fi; echo "##DIRS"; find "$HOME" /opt/digitafrica -maxdepth 5 -iname "m3-containerization*" 2>/dev/null; find "$HOME" /opt/digitafrica -maxdepth 5 -iname "module3-runtime" 2>/dev/null; echo "##END"'

echo "Collecting state from tier2_server via Ansible..."

NS=$(      remote "k3s kubectl get namespaces -o name")
HELM=$(    remote "KUBECONFIG=/etc/rancher/k3s/k3s.yaml helm list -A --short")
HELMREV=$( remote "KUBECONFIG=/etc/rancher/k3s/k3s.yaml helm list -A | awk 'NR>1{printf \"%s %s\\n\",\$1,\$3}'")
PODS=$(    remote "k3s kubectl get pods -n digitafrica -o name")
PVC=$(     remote "k3s kubectl get pvc  -n digitafrica -o name")
WSSTATE=$( remote "k3s kubectl get configmap digitafrica-workshop-state -n digitafrica \
                    -o jsonpath='{.data.workshop_type} {.data.workshop_module} {.data.mode} {.data.solutions_released} {.data.cleanup_status}'")
MOD1CM=$(  remote "k3s kubectl get configmap digitafrica-introduction-to-ai-module1 -n digitafrica --ignore-not-found -o name" | tr -d '[:space:]')
MOD2CM=$(  remote "k3s kubectl get configmap digitafrica-introduction-to-ai-module2 -n digitafrica --ignore-not-found -o name" | tr -d '[:space:]')
MOD3CM=$(  remote "k3s kubectl get configmap digitafrica-introduction-to-ai-module3 -n digitafrica --ignore-not-found -o name" | tr -d '[:space:]')
PORT=$(    remote "ss -tlnp | grep -q ':8080' && echo occupied || echo free" | tr -d '[:space:]')
NP=$(      remote "k3s kubectl get networkpolicy -n digitafrica -o name")

echo "Data collected. Running checks..."

# Workshop state: space-separated jsonpath fields
WS_TYPE=$(   printf '%s' "$WSSTATE" | awk '{print $1}')
WS_MODULE=$( printf '%s' "$WSSTATE" | awk '{print $2}')
WS_MODE=$(   printf '%s' "$WSSTATE" | awk '{print $3}')
WS_SOLREL=$( printf '%s' "$WSSTATE" | awk '{print $4}')
WS_CLEANUP=$(printf '%s' "$WSSTATE" | awk '{print $5}')

# Helm revisions
JHUB_REV=$(   printf '%s\n' "$HELMREV" | awk '/^jhub /{print $2}'    | tr -d '[:space:]')
TRAEFIK_REV=$(printf '%s\n' "$HELMREV" | awk '/^traefik /{print $2}' | tr -d '[:space:]')

# NetworkPolicy: k3s may return full API-group form; match on trailing name
np_present() {
  printf '%s\n' "$NP" | grep -E "(^|/)${1}$" || true
}

# ── Controller-local checks ───────────────────────────────────────────────────
hdr "CONTROLLER (repo root: $REPO_ROOT)"

CRED_FILE="${SECRETS_DIR}/ab-01.lab.uvalight.net-participant-credentials.tsv"
if [[ -f "$CRED_FILE" ]]; then
  ok "Credential export exists"; (( PASS++ )) || true
  check "Credential export permissions (600)" "600" "$(stat -c '%a' "$CRED_FILE")"
else
  fail "Credential export not found: $CRED_FILE"; (( FAIL++ )) || true
fi

TRAIN_CSV="${REPO_ROOT}/data/source/train.csv"
if [[ -f "$TRAIN_CSV" ]]; then
  check "data/source/train.csv size (436833 bytes)" "436833" "$(stat -c '%s' "$TRAIN_CSV")"
else
  fail "data/source/train.csv not found"; (( FAIL++ )) || true
fi

MANIFEST=$(ls "${REPO_ROOT}"/data/fl-recovery/*/partition-manifest.json 2>/dev/null | head -1 || true)
if [[ -n "$MANIFEST" ]]; then
  ok "data/fl-recovery partition-manifest.json present"; (( PASS++ )) || true
else
  fail "data/fl-recovery/*/partition-manifest.json not found"; (( FAIL++ )) || true
fi

if [[ -d "${REPO_ROOT}/data/partitions" ]]; then
  COUNT=$(find "${REPO_ROOT}/data/partitions" -mindepth 1 -maxdepth 1 | wc -l)
else
  COUNT=0
fi
check "data/partitions/ empty after reset" "0" "$COUNT"

# ── Namespaces ────────────────────────────────────────────────────────────────
hdr "NAMESPACES (ab-01)"
for ns in cert-manager default digitafrica digitafrica-identity kube-system kube-public kube-node-lease; do
  match=$(printf '%s\n' "$NS" | grep -x "namespace/${ns}" || true)
  check "namespace/$ns" "namespace/${ns}" "$match"
done

# ── Helm releases ─────────────────────────────────────────────────────────────
hdr "HELM RELEASES (ab-01)"
for rel in cert-manager jhub traefik; do
  match=$(printf '%s\n' "$HELM" | grep -x "$rel" || true)
  check "$rel release present" "$rel" "$match"
done
check "jhub revision (positive integer, grows with each reset)" "$JHUB_REV"    "$JHUB_REV"    integer
check "traefik revision 1"                                       "1"            "$TRAEFIK_REV"

# ── Pods ──────────────────────────────────────────────────────────────────────
hdr "PODS — digitafrica namespace (ab-01)"
for pattern in "pod/hub-" "pod/proxy-" "pod/user-scheduler" "pod/continuous-image-puller"; do
  match=$(printf '%s\n' "$PODS" | grep "$pattern" | head -1 || true)
  label="${pattern//pod\//}"
  check "$label pod present" "present" "$([ -n "$match" ] && echo present || echo absent)"
done
PARTICIPANT_PODS=$(printf '%s\n' "$PODS" | grep 'pod/jupyter-' || true)
if [[ -z "$PARTICIPANT_PODS" ]]; then
  ok "no participant pods (jupyter-*)"; (( PASS++ )) || true
else
  fail "participant pods still present: $PARTICIPANT_PODS"; (( FAIL++ )) || true
fi

# ── PVCs ─────────────────────────────────────────────────────────────────────
hdr "PVCs — digitafrica namespace (ab-01)"
HUB_PVC=$(printf '%s\n' "$PVC" | grep 'hub-db-dir' || true)
check "hub-db-dir PVC present" "present" "$([ -n "$HUB_PVC" ] && echo present || echo absent)"
PARTICIPANT_PVCS=$(printf '%s\n' "$PVC" | grep 'claim-group-' || true)
if [[ -z "$PARTICIPANT_PVCS" ]]; then
  ok "no participant PVCs (claim-group-*)"; (( PASS++ )) || true
else
  fail "participant PVCs still present: $PARTICIPANT_PVCS"; (( FAIL++ )) || true
fi

# ── Workshop state ConfigMap ──────────────────────────────────────────────────
hdr "WORKSHOP STATE ConfigMap (ab-01)"
check "workshop_type: none"           "none"          "$WS_TYPE"
check "workshop_module: none"         "none"          "$WS_MODULE"
check "mode: beginner"                "beginner"      "$WS_MODE"
check "solutions_released: false"     "false"         "$WS_SOLREL"
check "cleanup_status: none|complete" "none|complete" "$WS_CLEANUP" accept

# ── Teaching asset ConfigMaps ─────────────────────────────────────────────────
hdr "TEACHING ASSET ConfigMaps (ab-01)"
check "module1 ConfigMap present" "configmap/digitafrica-introduction-to-ai-module1" "$MOD1CM"
for mod_label in "module2:$MOD2CM" "module3:$MOD3CM"; do
  mod="${mod_label%%:*}"; val="${mod_label##*:}"
  if [[ -n "$val" ]]; then
    skip "$mod ConfigMap" "present (published — acceptable post-reset)"
  else
    skip "$mod ConfigMap" "absent (not yet published — acceptable)"
  fi
done

# ── NetworkPolicies ───────────────────────────────────────────────────────────
hdr "NETWORK POLICIES — digitafrica (ab-01)"
for np in hub proxy singleuser; do
  match=$(np_present "$np")
  check "networkpolicy/$np present" "present" "$([ -n "$match" ] && echo present || echo absent)"
done

# ── Port 8080 ─────────────────────────────────────────────────────────────────
hdr "FLOWER PORT (ab-01)"
check "port 8080 free" "free" "$PORT"

# ── Worker nodes ─────────────────────────────────────────────────────────────
hdr "RUNTIME ARTEFACTS — control plane (ab-01)"
expect_empty "no unexpected pods in digitafrica" \
  "$(printf '%s\n' "$PODS" | grep -vE '^pod/(hub-|proxy-|user-scheduler-|continuous-image-puller-)' | grep -v '^$' || true)"
expect_empty "no unexpected PVCs in digitafrica" \
  "$(printf '%s\n' "$PVC" | sed 's#.*/##' | grep -vx 'hub-db-dir' | grep -v '^$' || true)"
expect_empty "no unexpected NetworkPolicies in digitafrica" \
  "$(printf '%s\n' "$NP" | sed 's#.*/##' | grep -vxE 'hub|proxy|singleuser' | grep -v '^$' || true)"
EP_FILE="$HOME/.local/state/digitafrica/module3-runtime/endpoints.tsv"
if [[ -e "$EP_FILE" ]]; then
  fail "Module 3 endpoint file still present: $EP_FILE"; (( FAIL++ )) || true
else
  ok "Module 3 endpoint file absent"; (( PASS++ )) || true
fi

hdr "RUNTIME ARTEFACTS — workers (tier2_agents)"
WORKERS=$(ansible tier2_agents -i "$INVENTORY" --list-hosts 2>/dev/null </dev/null | tail -n +2 | tr -d ' ')
if [[ -z "$WORKERS" ]]; then
  skip "worker runtime artefacts" "no hosts found in group tier2_agents"
else
  for w in $WORKERS; do
    out=$(remote_on "$w" "$WORKER_PROBE")
    if ! printf '%s\n' "$out" | grep -qx '##END'; then
      fail "$w: probe did not complete"; (( FAIL++ )) || true
      continue
    fi
    if [[ "$(section STATE "$out")" != "docker-ok" ]]; then
      skip "$w Docker artefacts" "Docker not reachable for the SSH user; cannot confirm"
    else
      expect_empty "$w: no Docker containers (running or stopped)" "$(section CONTAINERS "$out")"
      expect_empty "$w: no Docker volumes"                        "$(section VOLUMES "$out")"
      expect_empty "$w: no custom Docker networks"                "$(section NETWORKS "$out")"
      expect_empty "$w: no Module 3 images" \
        "$(section IMAGES "$out" | grep -iE 'm3-|module3|auth|shortener' || true)"
      info "$w: $(section IMAGES "$out" | wc -l) Docker image(s) in total (informational only)"
    fi
    expect_empty "$w: no Module 3 runtime directories" "$(section DIRS "$out")"
  done
fi

hdr "NOT CHECKED BY THIS SCRIPT"
skip "FL worker assets /opt/digitafrica/fl-workshop/"  "not probed by this script"
skip "participant data partitions absent on workers"    "organiser reset output is primary evidence"
skip "Keycloak accounts group_01/group_02"              "requires Keycloak API — verify via organiser account-check or manual login"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════"
echo -e "  ${GREEN}PASS: $PASS${RESET}   ${RED}FAIL: $FAIL${RESET}   ${YELLOW}SKIP: $SKIP${RESET}"
echo "════════════════════════════════════════════════════════════"
if (( FAIL > 0 )); then
  echo -e "${RED}State does NOT match S0 baseline — review DIFFER items above.${RESET}"
  exit 1
else
  echo -e "${GREEN}State matches S0 baseline (skipped items require manual verification).${RESET}"
  exit 0
fi

