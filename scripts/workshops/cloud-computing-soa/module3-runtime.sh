# Module 3-only Compose runtime controls.
# Sourced by scripts/workshops/cloud-computing-soa/module3-main.sh.

cloud_module3_runtime_targets() {
  local repo_root
  repo_root="$(cd -- "$CLOUD_MODULE3_DIR/../../.." && pwd)" || return 1

  python3 - "$repo_root" "$WORKSHOP_INVENTORY" "$WORKSHOP_WORKER_GROUP" <<'PY'
import json
import re
import subprocess
import sys

root, inventory, group = sys.argv[1:]
try:
    result = subprocess.run(
        ["ansible-inventory", "-i", inventory, "--list"],
        cwd=root, check=True, capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    hosts = data.get(group, {}).get("hosts", [])
except Exception as exc:
    print(f"Cannot read worker inventory: {exc}", file=sys.stderr)
    raise SystemExit(1)

if not hosts:
    print(f"Worker inventory group is empty or missing: {group}", file=sys.stderr)
    raise SystemExit(1)
if len(hosts) != len(set(hosts)):
    print("Worker inventory contains duplicate host aliases.", file=sys.stderr)
    raise SystemExit(1)

for index, host in enumerate(hosts, start=1):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", host):
        print(f"Unsafe inventory host alias: {host!r}", file=sys.stderr)
        raise SystemExit(1)
    print(f"group_{index:02d}\t{host}")
PY
}

cloud_module3_runtime_record_target() {
  local group_id="$1" inventory_alias="$2"
  local state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/digitafrica/module3-runtime"
  mkdir -p "$state_dir" || return 1
  chmod 700 "$state_dir" || return 1

  python3 - "$state_dir/targets.json" "$group_id" "$inventory_alias" \
    "$WORKSHOP_INVENTORY" "$WORKSHOP_WORKER_GROUP" <<'PY'
import datetime
import json
import os
import sys
import tempfile

path, group_id, alias, inventory, worker_group = sys.argv[1:]
state = {"schema": 1, "targets": {}}
if os.path.exists(path):
    with open(path, encoding="utf-8") as stream:
        state = json.load(stream)
if state.get("schema") != 1 or not isinstance(state.get("targets"), dict):
    raise SystemExit("Module 3 runtime target record has an unknown format.")

state["targets"][group_id] = {
    "inventory_alias": alias,
    "inventory": os.path.abspath(inventory),
    "worker_group": worker_group,
    "runtime_path": f"/var/lib/digitafrica/module3-runtime/{group_id}",
    "compose_project": f"m3-containerization-{group_id}",
    "recorded_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
fd, temporary = tempfile.mkstemp(prefix=".targets-", dir=os.path.dirname(path))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(state, stream, indent=2)
        stream.write("\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
}

cloud_module3_runtime_build_remote_script() {
  local operation="$1" group_id="$2" inventory_alias="$3" archive_b64="${4:-}"
  local script
  script="$(cat <<'REMOTE'
set -euo pipefail
operation='@@OPERATION@@'
group_id='@@GROUP_ID@@'
inventory_alias='@@INVENTORY_ALIAS@@'
project="m3-containerization-${group_id}"
runtime_dir="/var/lib/digitafrica/module3-runtime/${group_id}"
source_dir="${runtime_dir}/containerization"
marker="${runtime_dir}/.module3-runtime-owner"

owner_matches() {
  [[ -f "$marker" ]] &&
    grep -Fxq 'module=cloud-computing-soa-module3' "$marker" &&
    grep -Fxq "group=${group_id}" "$marker" &&
    grep -Fxq "inventory_alias=${inventory_alias}" "$marker" &&
    grep -Fxq "compose_project=${project}" "$marker"
}

configure_runtime_bind() {
  local host_ip
  host_ip="$(ip -4 -o addr show dev cni0 |
    awk 'NR == 1 { split($4, address, "/"); print address[1] }')" || return 1
  [[ -n "$host_ip" ]] || {
    echo "ERROR: No IPv4 address found on worker cni0; refusing a public bind." >&2
    return 1
  }
  export AUTH_HOST_PORT="${host_ip}:5001"
  export SHORTENER_HOST_PORT="${host_ip}:5000"
}

if [[ "$operation" == "start" ]]; then
  configure_runtime_bind || exit 3
  if [[ -e "$runtime_dir" || -L "$runtime_dir" ]]; then
    [[ -d "$runtime_dir" && ! -L "$runtime_dir" ]] || {
      echo "ERROR: Runtime path exists but is not an owned directory." >&2
      exit 3
    }
    owner_matches || {
      echo "ERROR: Runtime path has no matching Module 3 ownership marker; refusing to modify it." >&2
      exit 3
    }
  else
    install -d -m 0750 "$runtime_dir"
    {
      echo 'module=cloud-computing-soa-module3'
      echo "group=${group_id}"
      echo "inventory_alias=${inventory_alias}"
      echo "compose_project=${project}"
      echo "runtime_path=${runtime_dir}"
      echo "host_ports=${AUTH_HOST_PORT},${SHORTENER_HOST_PORT}"
      echo "runtime_host=$(hostname -f 2>/dev/null || hostname)"
    } > "$marker"
    chmod 0640 "$marker"
  fi

  install -d -m 0750 "$source_dir"
  printf '%s' '@@ARCHIVE@@' | base64 -d | tar -xz -C "$source_dir"
  mkdir -p "$source_dir/auth_service/data" "$source_dir/shortener_service/data"
  cd "$source_dir"
  command -v docker >/dev/null
  docker compose version >/dev/null
  keygen_override="$source_dir/.module3-keygen-compose.yml"
  cat > "$keygen_override" <<'KEYGEN_COMPOSE'
services:
  auth:
    volumes:
      - type: bind
        source: ./auth_service/keys
        target: /app/keys
        read_only: false
KEYGEN_COMPOSE
  chmod 0640 "$keygen_override"

  docker compose --project-name "$project" -f docker-compose.yml \
    -f "$keygen_override" config --format json |
    python3 -c 'import json,sys; s=json.load(sys.stdin)["services"]["auth"]; m=[v for v in s.get("volumes",[]) if v.get("target")=="/app/keys"]; assert len(m)==1 and not m[0].get("read_only",False), "auth key mount is not writable"'

  docker compose --project-name "$project" -f docker-compose.yml \
    -f "$keygen_override" build auth
  docker compose --project-name "$project" -f docker-compose.yml \
    -f "$keygen_override" run --rm --no-deps --entrypoint python auth \
    -c 'import os,sys; os.chdir("/app"); sys.path.insert(0,"/app"); import auth; auth.ensure_keys_exist()'

  chmod 0600 auth_service/keys/private_key.pem
  chmod 0644 auth_service/keys/public_key.pem
  cp auth_service/keys/public_key.pem shortener_service/keys/public_key.pem
  chmod 0644 shortener_service/keys/public_key.pem
  rm -f "$keygen_override"

  docker compose --project-name "$project" config --quiet
  docker compose --project-name "$project" up --build -d
  printf 'GROUP=%s INVENTORY_ALIAS=%s HOST=%s\n' \
    "$group_id" "$inventory_alias" "$(hostname -f 2>/dev/null || hostname)"
  docker compose --project-name "$project" ps --all

  if grep -q '^host_ports=' "$marker"; then
    sed -i "s|^host_ports=.*|host_ports=${AUTH_HOST_PORT},${SHORTENER_HOST_PORT}|" "$marker"
  else
    printf 'host_ports=%s,%s\n' "$AUTH_HOST_PORT" "$SHORTENER_HOST_PORT" >> "$marker"
  fi

  auth_container="$(docker compose --project-name "$project" ps -q auth)"
  shortener_container="$(docker compose --project-name "$project" ps -q shortener)"
  [[ -n "$auth_container" && -n "$shortener_container" ]] || {
    echo "ERROR: Module 3 service containers were not found." >&2
    exit 3
  }
  docker inspect "$auth_container" "$shortener_container" | python3 -c '
import ipaddress, json, sys
group_id, project = sys.argv[1:]
containers = json.load(sys.stdin)
if len(containers) != 2:
    raise SystemExit("Expected exactly two Module 3 service containers.")
ips = [str(ipaddress.IPv4Address(
    item["NetworkSettings"]["Networks"][project + "_default"]["IPAddress"]
)) for item in containers]
print("MODULE3_POLICY_TARGET", group_id, *ips)
' "$group_id" "$project"

elif [[ "$operation" == "status" ]]; then
  if [[ ! -e "$runtime_dir" && ! -L "$runtime_dir" ]]; then
    printf 'NOT_PROVISIONED group=%s inventory_alias=%s\n' "$group_id" "$inventory_alias"
    exit 0
  fi
  [[ -d "$runtime_dir" && ! -L "$runtime_dir" ]] && owner_matches || {
    echo "ERROR: Runtime path has no matching Module 3 ownership marker." >&2
    exit 3
  }
  cd "$source_dir"
  configure_runtime_bind || exit 3
  docker compose --project-name "$project" ps --all
else
  echo "ERROR: Unsupported Module 3 runtime operation." >&2
  exit 2
fi
REMOTE
)" || return 1

  script="${script//@@OPERATION@@/$operation}"
  script="${script//@@GROUP_ID@@/$group_id}"
  script="${script//@@INVENTORY_ALIAS@@/$inventory_alias}"
  script="${script//@@ARCHIVE@@/$archive_b64}"
  printf '%s\n' "$script"
}

cloud_module3_runtime_apply_egress_policy() {
  local group_id="$1" auth_ip="$2" shortener_ip="$3" manifest_b64
  manifest_b64="$(python3 - "$group_id" "$auth_ip" "$shortener_ip" <<'POLICY_JSON'
import base64
import ipaddress
import json
import re
import sys

group_id, auth_ip, shortener_ip = sys.argv[1:]
if not re.fullmatch(r"group_[0-9]+", group_id):
    raise SystemExit("Invalid Module 3 participant group.")
auth_ip = str(ipaddress.IPv4Address(auth_ip))
shortener_ip = str(ipaddress.IPv4Address(shortener_ip))
policy = {
    "apiVersion": "networking.k8s.io/v1",
    "kind": "NetworkPolicy",
    "metadata": {
        "name": "module3-" + group_id.replace("_", "-") + "-runtime-egress",
        "namespace": "digitafrica",
    },
    "spec": {
        "podSelector": {"matchLabels": {"hub.jupyter.org/username": group_id}},
        "policyTypes": ["Egress"],
        "egress": [
            {"to": [{"ipBlock": {"cidr": ip + "/32"}}],
             "ports": [{"protocol": "TCP", "port": port}]}
            for ip, port in [(auth_ip, 5001), (shortener_ip, 5000)]
        ],
    },
}
print(base64.b64encode(json.dumps(policy).encode()).decode())
POLICY_JSON
)" || return 1
  run_deployment_remote "set -euo pipefail
printf '%s' '${manifest_b64}' | base64 -d | k3s kubectl apply -f -"
}

cloud_module3_runtime_run() {
  local operation="$1" targets group_id inventory_alias script
  local archive_b64="" failures=0
  local repo_root asset_dir remote_output endpoint_line auth_ip shortener_ip

  [[ -n "${WORKSHOP_INVENTORY:-}" && -n "${WORKSHOP_WORKER_GROUP:-}" ]] || {
    echo "Module 3 runtime requires loaded workshop inventory context." >&2
    return 2
  }
  declare -F run_inventory_target_remote >/dev/null || {
    echo "Module 3 runtime requires run_inventory_target_remote." >&2
    return 2
  }

  repo_root="$(cd -- "$CLOUD_MODULE3_DIR/../../.." && pwd)" || return 1
  asset_dir="$repo_root/workshop_assets/cloud-computing-soa/module3-containerization-orchestration/beginner/containerization"
  [[ -d "$asset_dir" ]] || {
    echo "Missing Module 3 containerization assets: $asset_dir" >&2
    return 2
  }

  if [[ "$operation" == "start" ]]; then
    declare -F run_deployment_remote >/dev/null &&
      [[ -n "${DIGITAFRICA_DEPLOYMENT_GROUP:-}" ]] || {
      echo "Module 3 runtime start requires the deployment control-plane context." >&2
      return 2
    }
  fi

  targets="$(cloud_module3_runtime_targets)" || return $?
  if [[ "$operation" == "start" ]]; then
    command -v tar >/dev/null && command -v base64 >/dev/null || {
      echo "Module 3 runtime staging requires tar and base64 on the control host." >&2
      return 2
    }
    archive_b64="$(
      set -o pipefail
      tar -C "$asset_dir" -czf - \
        docker-compose.yml setup_local_keys.sh \
        auth_service/auth.py auth_service/Dockerfile \
        auth_service/.dockerignore auth_service/requirements.txt \
        shortener_service/shortener.py shortener_service/Dockerfile \
        shortener_service/.dockerignore shortener_service/requirements.txt |
        base64 | tr -d '\r\n'
    )" || return 1
  fi

  while IFS=$'\t' read -r group_id inventory_alias; do
    [[ -n "$group_id" && -n "$inventory_alias" ]] || continue
    printf '\n=== Module 3 runtime %s: %s → %s ===\n' \
      "$operation" "$group_id" "$inventory_alias"

    if [[ "$operation" == "start" ]]; then
      cloud_module3_runtime_record_target "$group_id" "$inventory_alias" || {
        echo "Could not record Module 3 runtime target; skipping remote changes." >&2
        failures=1
        continue
      }
    fi

    script="$(cloud_module3_runtime_build_remote_script \
      "$operation" "$group_id" "$inventory_alias" "$archive_b64")" || {
      failures=1
      continue
    }
    if remote_output="$(run_inventory_target_remote "$inventory_alias" "$script")"; then
      printf '%s\n' "$remote_output"
    else
      printf '%s\n' "$remote_output" >&2
      failures=1
      continue
    fi

    if [[ "$operation" == "start" ]]; then
      endpoint_line="$(printf '%s\n' "$remote_output" |
        awk -v group="$group_id" \
          '$1 == "MODULE3_POLICY_TARGET" && $2 == group && NF >= 4 { print $3, $4 }')"
      [[ -n "$endpoint_line" && "$endpoint_line" != *$'\n'* ]] || {
        echo "Missing or ambiguous Module 3 endpoint report for ${group_id}." >&2
        failures=1
        continue
      }
      read -r auth_ip shortener_ip <<< "$endpoint_line"
      cloud_module3_runtime_apply_egress_policy "$group_id" "$auth_ip" "$shortener_ip" || {
        echo "Could not reconcile Module 3 egress policy for ${group_id}." >&2
        failures=1
      }
    fi
  done <<< "$targets"

  return "$failures"
}

cloud_module3_runtime_start() {
  local DIGITAFRICA_ASSUME_YES=false ASSUME_YES=false
  declare -F confirm >/dev/null || {
    echo "Explicit organiser confirmation is unavailable; runtime start blocked." >&2
    return 2
  }
  confirm "Start the Module 3 beginner containerization runtime on assigned worker VMs; preserve existing data" ||
    return 1
  cloud_module3_runtime_run start
}

cloud_module3_runtime_status() {
  cloud_module3_runtime_run status
}
