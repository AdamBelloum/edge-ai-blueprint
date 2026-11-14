cp scripts/lib/compare_state.sh /tmp/compare_state.sh.bak && python3 - <<'PYEOF'
import re, pathlib
p = pathlib.Path("scripts/lib/compare_state.sh")
s = p.read_text()

HELPERS = r'''# Run one command on a single host; same stdout extraction as remote().
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
'''

anchor = 'echo "Collecting state from tier2_server via Ansible..."\n'
assert s.count(anchor) == 1, "anchor A not found exactly once"
s = s.replace(anchor, HELPERS + "\n" + anchor)

NEW = r'''hdr "RUNTIME ARTEFACTS — control plane (ab-01)"
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
skip "Keycloak accounts group_01/group_02"              "requires Keycloak API — verify via organiser account-check or manual login"'''

pat = re.compile(r'hdr "WORKER NODES \(ab-02, ab-03\)".*?(?=\n\n# ── Summary)', re.S)
assert len(pat.findall(s)) == 1, "worker section not found exactly once"
s = pat.sub(lambda m: NEW, s)
p.write_text(s)
print("patched")
PYEOF
bash -n scripts/lib/compare_state.sh && bash scripts/lib/compare_state.sh
