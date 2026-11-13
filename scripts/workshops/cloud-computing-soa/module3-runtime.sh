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

# Run the Module 3 endpoint store (organiser reference file).
# CLOUD_MODULE3_ENDPOINTS_PATH is a test hook; unset uses the store default.
cloud_module3_runtime_endpoints() {
  local store="${CLOUD_MODULE3_DIR:-}/module3_endpoints.py"
  local -a path_args=()

  [[ -n "${CLOUD_MODULE3_DIR:-}" ]] || {
    echo "Module 3 endpoint store: CLOUD_MODULE3_DIR is not set." >&2
    return 3
  }
  [[ -f "$store" ]] || {
    echo "Module 3 endpoint store not found: $store" >&2
    return 3
  }
  command -v python3 >/dev/null 2>&1 || {
    echo "Module 3 endpoint store requires python3 on the control host." >&2
    return 3
  }
  if [[ -n "${CLOUD_MODULE3_ENDPOINTS_PATH:-}" ]]; then
    path_args=(--path "$CLOUD_MODULE3_ENDPOINTS_PATH")
  fi
  python3 "$store" ${path_args[@]+"${path_args[@]}"} "$@"
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
import re
import sys
import tempfile

path, group_id, alias, inventory, worker_group = sys.argv[1:]
if not re.fullmatch(r"group_[0-9]+", group_id) or not re.fullmatch(r"[A-Za-z0-9_.-]+", alias):
    raise SystemExit("Refusing to record an unsafe Module 3 runtime target.")
state = {"schema": 1, "targets": {}}
if os.path.exists(path):
    with open(path, encoding="utf-8") as stream:
        state = json.load(stream)
if state.get("schema") != 1 or not isinstance(state.get("targets"), dict):
    raise SystemExit("Module 3 runtime target record has an unknown format.")

key = f"{group_id}@{alias}"
legacy = state["targets"].get(group_id)
if isinstance(legacy, dict) and legacy.get("inventory_alias") == alias:
    del state["targets"][group_id]
state["targets"][key] = {
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

# Prints validated "group<TAB>alias<TAB>inventory" lines from the local target
# record. Exit 1: some entries were skipped as invalid. Exit 2: record unusable.
cloud_module3_runtime_history_targets() {
  local state_file="${XDG_STATE_HOME:-$HOME/.local/state}/digitafrica/module3-runtime/targets.json"
  [[ -e "$state_file" ]] || return 0

  python3 - "$state_file" <<'PY'
import json
import re
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        state = json.load(stream)
except (OSError, ValueError) as exc:
    print(f"Cannot read Module 3 runtime target record: {exc}", file=sys.stderr)
    raise SystemExit(2)
if not isinstance(state, dict) or state.get("schema") != 1 or not isinstance(state.get("targets"), dict):
    print("Module 3 runtime target record has an unknown format.", file=sys.stderr)
    raise SystemExit(2)

group_re = re.compile(r"group_[0-9]+")
alias_re = re.compile(r"[A-Za-z0-9_.-]+")
inventory_re = re.compile(r"/[^\s'\"]+")
bad = 0
for key in sorted(state["targets"]):
    entry = state["targets"][key]
    problem = None
    if not isinstance(entry, dict):
        problem = "malformed entry"
    else:
        group, _, key_alias = key.partition("@")
        alias = entry.get("inventory_alias")
        inventory = entry.get("inventory")
        runtime_path = entry.get("runtime_path")
        if not group_re.fullmatch(group):
            problem = "unsafe group"
        elif not isinstance(alias, str) or not alias_re.fullmatch(alias):
            problem = "unsafe alias"
        elif "@" in key and key_alias != alias:
            problem = "key/alias mismatch"
        elif not isinstance(inventory, str) or not inventory_re.fullmatch(inventory):
            problem = "unsafe inventory path"
        elif runtime_path is not None and runtime_path != f"/var/lib/digitafrica/module3-runtime/{group}":
            problem = "unexpected runtime path"
    if problem:
        print(f"Skipping invalid Module 3 runtime target record {key!r}: {problem}.", file=sys.stderr)
        bad = 1
        continue
    print(f"{group}\t{alias}\t{inventory}")
raise SystemExit(bad)
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
  [[ -f "$marker" && ! -L "$marker" ]] &&
    grep -Fxq 'module=cloud-computing-soa-module3' "$marker" &&
    grep -Fxq "group=${group_id}" "$marker" &&
    grep -Fxq "inventory_alias=${inventory_alias}" "$marker" &&
    grep -Fxq "compose_project=${project}" "$marker" &&
    grep -Fxq "runtime_path=${runtime_dir}" "$marker"
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
  mkdir -p "$source_dir/auth_service/data" "$source_dir/shortener_service/data" "$source_dir/auth_service/keys" "$source_dir/shortener_service/keys"
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
  printf 'AUTH_ENDPOINT=%s\nSHORTENER_ENDPOINT=%s\n' \
    "$AUTH_HOST_PORT" "$SHORTENER_HOST_PORT"

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
elif [[ "$operation" == "reset" || "$operation" == "reset-plan" ]]; then
  [[ "$group_id" =~ ^group_[0-9]+$ ]] || {
    echo "ERROR: Invalid Module 3 participant group." >&2
    exit 2
  }
  dry_run=false
  if [[ "$operation" == "reset-plan" ]]; then dry_run=true; fi
  label="com.docker.compose.project=${project}"
  containers="$(docker ps -aq --filter "label=${label}")"
  networks="$(docker network ls -q --filter "label=${label}")"
  volumes="$(docker volume ls -q --filter "label=${label}")"

  if [[ ! -e "$runtime_dir" && ! -L "$runtime_dir" ]]; then
    if [[ -z "${containers}${networks}${volumes}" ]]; then
      printf 'NOT_PROVISIONED group=%s inventory_alias=%s\n' "$group_id" "$inventory_alias"
      exit 0
    fi
    echo "ERROR: Docker resources exist for ${project} without a runtime ownership marker; refusing to remove them." >&2
    exit 3
  fi
  [[ -d "$runtime_dir" && ! -L "$runtime_dir" ]] && owner_matches || {
    echo "ERROR: Runtime path has no matching Module 3 ownership marker; refusing to modify it." >&2
    exit 3
  }

  if [[ "$dry_run" == true ]]; then
    printf 'WOULD_REMOVE group=%s project=%s runtime_dir=%s containers=%s networks=%s volumes=%s\n' \
      "$group_id" "$project" "$runtime_dir" \
      "$(wc -w <<< "$containers")" "$(wc -w <<< "$networks")" "$(wc -w <<< "$volumes")"
    exit 0
  fi

  if [[ -f "${source_dir}/docker-compose.yml" ]]; then
    # Capture Compose progress so the result line stays clean; show it on failure only.
    compose_log="$(
      cd "$source_dir" &&
        export AUTH_HOST_PORT=127.0.0.1:5001 SHORTENER_HOST_PORT=127.0.0.1:5000 &&
        docker compose --project-name "$project" config --quiet 2>&1 &&
        docker compose --project-name "$project" down --volumes --remove-orphans --rmi local 2>&1
    )" || {
      printf '%s\n' "$compose_log" >&2
      echo "ERROR: Module 3 Compose cleanup failed; preserving the runtime directory for recovery." >&2
      exit 3
    }
  elif [[ -n "${containers}${networks}${volumes}" ]]; then
    echo "ERROR: Owned Module 3 runtime is missing its Compose definition while Docker resources exist; refusing to claim cleanup." >&2
    exit 3
  fi
  # No Compose definition and no labelled Docker resources: an interrupted
  # start left only the owned directory, so fall through to verification
  # and removal below.

  containers="$(docker ps -aq --filter "label=${label}")"
  networks="$(docker network ls -q --filter "label=${label}")"
  volumes="$(docker volume ls -q --filter "label=${label}")"
  if [[ -n "$containers" ]]; then
    docker rm -f $containers > /dev/null || {
      echo "ERROR: Failed to remove Module 3 containers for ${group_id}; runtime directory preserved for retry." >&2
      exit 3
    }
  fi
  if [[ -n "$networks" ]]; then
    docker network rm $networks > /dev/null || {
      echo "ERROR: Failed to remove Module 3 networks for ${group_id}; runtime directory preserved for retry." >&2
      exit 3
    }
  fi
  if [[ -n "$volumes" ]]; then
    docker volume rm $volumes > /dev/null || {
      echo "ERROR: Failed to remove Module 3 volumes for ${group_id}; runtime directory preserved for retry." >&2
      exit 3
    }
  fi

  # Verify Docker resources are gone BEFORE touching the runtime directory,
  # so a failed reset keeps its ownership marker and stays retryable.
  remaining_containers="$(docker ps -aq --filter "label=${label}")"
  remaining_networks="$(docker network ls -q --filter "label=${label}")"
  remaining_volumes="$(docker volume ls -q --filter "label=${label}")"
  if [[ -n "${remaining_containers}${remaining_networks}${remaining_volumes}" ]]; then
    echo "ERROR: Module 3 Docker resources remain for ${group_id}; runtime directory and ownership marker preserved for retry." >&2
    exit 3
  fi

  # Remove contents first and the ownership marker last.
  find "$runtime_dir" -xdev -mindepth 1 ! -path "$marker" -delete
  rm -f -- "$marker"
  rmdir -- "$runtime_dir"
  if [[ -e "$runtime_dir" || -L "$runtime_dir" ]]; then
    echo "ERROR: Module 3 runtime directory remains for ${group_id} after reset." >&2
    exit 3
  fi
  printf 'RESET_OK group=%s inventory_alias=%s project=%s\n' "$group_id" "$inventory_alias" "$project"
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

cloud_module3_runtime_endpoint_value() {
  local key="$1" output="$2" line value="" count=0

  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" == "${key}="* ]]; then
      count=$((count + 1))
      value="${line#"${key}="}"
    fi
  done <<< "$output"

  [[ "$count" -eq 1 ]] || return 1
  [[ -n "$value" && "$value" != *[[:space:]=]* ]] || return 1
  printf '%s\n' "$value"
}

cloud_module3_runtime_run() {
  local operation="$1" targets group_id inventory_alias script
  local archive_b64="" failures=0
  local repo_root asset_dir remote_output endpoint_line auth_ip shortener_ip
  local auth_endpoint shortener_endpoint

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
  if [[ "$operation" == "start" && ! -d "$asset_dir" ]]; then
    echo "Missing Module 3 containerization assets: $asset_dir" >&2
    return 2
  fi

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
      if auth_endpoint="$(cloud_module3_runtime_endpoint_value \
        AUTH_ENDPOINT "$remote_output")" &&
        shortener_endpoint="$(cloud_module3_runtime_endpoint_value \
          SHORTENER_ENDPOINT "$remote_output")"; then
        cloud_module3_runtime_endpoints save "$WORKSHOP_INVENTORY" \
          "$group_id" "$inventory_alias" "$auth_endpoint" "$shortener_endpoint" || {
          echo "Could not save Module 3 endpoint reference for ${group_id}." >&2
          failures=1
        }
      else
        echo "Missing or ambiguous Module 3 endpoint lines for ${group_id}; endpoint reference not updated." >&2
        failures=1
      fi
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

# Delete only per-group Module 3 egress policies (exact name pattern).
cloud_module3_runtime_reset_egress_policies() {
  local dry_run="${1:-false}"
  declare -F run_deployment_remote >/dev/null &&
    [[ -n "${DIGITAFRICA_DEPLOYMENT_GROUP:-}" ]] || {
    echo "Module 3 policy reset requires the deployment control-plane context." >&2
    return 2
  }
  run_deployment_remote "dry_run='${dry_run}'
$(cat <<'REMOTE'
set -euo pipefail
pattern='^networkpolicy(\.networking\.k8s\.io)?/module3-group-[0-9]+-runtime-egress$'
list_policies() {
  local output
  output="$(k3s kubectl -n digitafrica get networkpolicy -o name)" || return $?
  [[ -n "$output" ]] || return 0
  grep -E "$pattern" <<< "$output" || [[ $? -eq 1 ]]
}
names="$(list_policies)"
if [[ -z "$names" ]]; then
  echo "NO_MODULE3_EGRESS_POLICIES"
  exit 0
fi
if [[ "$dry_run" == true ]]; then
  printf 'WOULD_DELETE %s\n' $names
  exit 0
fi
failed=0
while IFS= read -r name; do
  if ! k3s kubectl -n digitafrica delete "$name" --ignore-not-found; then
    echo "ERROR: failed to delete $name" >&2
    failed=1
  fi
done <<< "$names"
remaining="$(list_policies)"
if [[ -n "$remaining" ]]; then
  printf 'ERROR: Module 3 egress policy remains: %s\n' $remaining >&2
  exit 3
fi
if [[ "$failed" -ne 0 ]]; then
  echo "ERROR: delete reported failures; re-run to confirm." >&2
  exit 4
fi
echo "MODULE3_EGRESS_POLICIES_REMOVED"
REMOTE
)"
}

# Succeeds only if the remote output has the exact result line for this target.
cloud_module3_runtime_result_ok() {
  local mode="$1" group_id="$2" alias="$3" output="$4"
  printf '%s\n' "$output" | awk -v mode="$mode" -v group="$group_id" -v alias="$alias" '
    BEGIN {
      project = "m3-containerization-" group
      none = "NOT_PROVISIONED group=" group " inventory_alias=" alias
      done = "RESET_OK group=" group " inventory_alias=" alias " project=" project
      plan = "WOULD_REMOVE group=" group " project=" project " runtime_dir="
    }
    $0 == none { ok = 1 }
    mode == "reset" && $0 == done { ok = 1 }
    mode == "reset-plan" && index($0, plan) == 1 { ok = 1 }
    END { exit (ok ? 0 : 1) }'
}

# Removes only the given verified "group<TAB>alias<TAB>inventory" targets from
# the local record; deletes the record file only when no targets remain.
cloud_module3_runtime_forget_targets() {
  local state_file="${XDG_STATE_HOME:-$HOME/.local/state}/digitafrica/module3-runtime/targets.json"
  [[ -e "$state_file" ]] || return 0

  python3 - "$state_file" "$@" <<'PY'
import json
import os
import sys
import tempfile

path = sys.argv[1]
verified = {tuple(item.split("\t")) for item in sys.argv[2:]}
try:
    with open(path, encoding="utf-8") as stream:
        state = json.load(stream)
except (OSError, ValueError) as exc:
    raise SystemExit(f"Cannot read Module 3 runtime target record: {exc}")
if not isinstance(state, dict) or state.get("schema") != 1 or not isinstance(state.get("targets"), dict):
    raise SystemExit("Module 3 runtime target record has an unknown format.")

targets = state["targets"]
for key in list(targets):
    entry = targets[key]
    if isinstance(entry, dict) and (
        key.partition("@")[0], entry.get("inventory_alias"), entry.get("inventory")
    ) in verified:
        del targets[key]

if not targets:
    os.unlink(path)
    raise SystemExit(0)

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

# Succeeds only if the egress-policy cleanup output has an exact success line.
cloud_module3_runtime_policy_result_ok() {
  local dry_run="$1" output="$2"
  printf '%s\n' "$output" | awk -v dry="$dry_run" '
    $0 == "NO_MODULE3_EGRESS_POLICIES" { ok = 1 }
    dry != "true" && $0 == "MODULE3_EGRESS_POLICIES_REMOVED" { ok = 1 }
    dry == "true" && /^WOULD_DELETE networkpolicy(\.networking\.k8s\.io)?\/module3-group-[0-9]+-runtime-egress$/ { ok = 1 }
    END { exit (ok ? 0 : 1) }'
}

# mode: reset-plan (no changes) or reset (default).
# Covers current inventory targets AND recorded history; a target counts as
# verified only when its exact result line is present.
cloud_module3_runtime_reset() {
  local mode="${1:-reset}" dry_run=false failures=0 rc=0
  local current="" history="" combined="" group_id alias inventory script output policy_output
  local -a verified=()
  case "$mode" in
    reset) ;;
    reset-plan) dry_run=true ;;
    *) echo "Unsupported Module 3 reset mode: $mode" >&2; return 2 ;;
  esac
  declare -F run_inventory_target_remote >/dev/null || {
    echo "Module 3 runtime reset requires run_inventory_target_remote." >&2
    return 2
  }
  [[ -n "${WORKSHOP_INVENTORY:-}" ]] || {
    echo "Module 3 runtime reset requires a loaded workshop inventory (WORKSHOP_INVENTORY)." >&2
    return 2
  }

  current="$(cloud_module3_runtime_targets)" || {
    echo "Cannot enumerate current Module 3 worker targets; reset cannot be verified complete." >&2
    failures=1
    current=""
  }
  history="$(cloud_module3_runtime_history_targets)" || rc=$?
  if ((rc)); then
    echo "Module 3 runtime target history is incomplete or unreadable (status ${rc}); reset cannot be verified complete." >&2
    echo "Review ${XDG_STATE_HOME:-$HOME/.local/state}/digitafrica/module3-runtime/targets.json and correct invalid entries manually; remove an entry only after confirming that worker holds no Module 3 runtime." >&2
    failures=1
  fi

  combined="$(
    {
      while IFS=$'\t' read -r group_id alias; do
        [[ -n "$group_id" && -n "$alias" ]] &&
          printf '%s\t%s\t%s\n' "$group_id" "$alias" "${WORKSHOP_INVENTORY:-}"
      done <<< "$current"
      printf '%s\n' "$history"
    } | awk -F '\t' 'NF == 3 && $3 != "" && !seen[$0]++'
  )"

  # Cut participant access first, then remove the runtimes. Both steps are
  # always attempted; either one failing makes the overall result incomplete.
  printf '\n=== Module 3 egress policies (%s) ===\n' "$mode"
  if policy_output="$(cloud_module3_runtime_reset_egress_policies "$dry_run")"; then
    printf '%s\n' "$policy_output"
    if ! cloud_module3_runtime_policy_result_ok "$dry_run" "$policy_output"; then
      echo "No verified egress-policy result line; treating as incomplete." >&2
      failures=1
    fi
  else
    printf '%s\n' "$policy_output"
    echo "Module 3 egress policy cleanup failed." >&2
    failures=1
  fi

  while IFS=$'\t' read -r group_id alias inventory; do
    [[ -n "$group_id" && -n "$alias" && -n "$inventory" ]] || continue
    printf '\n=== Module 3 runtime %s: %s → %s (%s) ===\n' \
      "$mode" "$group_id" "$alias" "$inventory"
    script="$(cloud_module3_runtime_build_remote_script "$mode" "$group_id" "$alias" "")" || {
      failures=1
      continue
    }
    if output="$(DIGITAFRICA_INVENTORY="$inventory" run_inventory_target_remote "$alias" "$script")"; then
      printf '%s\n' "$output"
    else
      printf '%s\n' "$output" >&2
      echo "Module 3 runtime reset failed for ${group_id} on ${alias}." >&2
      failures=1
      continue
    fi
    if cloud_module3_runtime_result_ok "$mode" "$group_id" "$alias" "$output"; then
      verified+=("${group_id}"$'\t'"${alias}"$'\t'"${inventory}")
    else
      echo "No verified result line for ${group_id} on ${alias}; treating as incomplete." >&2
      failures=1
    fi
  done <<< "$combined"

  if [[ "$dry_run" == false && ${#verified[@]} -gt 0 ]]; then
    cloud_module3_runtime_forget_targets "${verified[@]}" || {
      echo "Could not update the local Module 3 target record." >&2
      failures=1
    }
  fi

  if ((failures)); then
    echo "Module 3 runtime reset incomplete; unverified local target records preserved." >&2
    return 1
  fi
  if [[ "$dry_run" == false ]]; then
    echo "Module 3 runtime reset verified: containers, volumes, runtime directories and egress policies removed."
  else
    echo "Module 3 runtime reset preview complete; nothing was changed."
  fi
}

cloud_module3_runtime_reset_confirmed() {
  local DIGITAFRICA_ASSUME_YES=false ASSUME_YES=false
  declare -F confirm >/dev/null || {
    echo "Explicit organiser confirmation is unavailable; runtime reset blocked." >&2
    return 2
  }
  printf '%s\n' \
    "This permanently deletes Module 3 runtime state:" \
    "  - Compose containers, networks and named volumes (service data such as user and URL records), on current and previously recorded worker targets" \
    "  - Compose-built images without a custom tag (docker compose down --rmi local)" \
    "  - runtime directories, including generated authentication keys" \
    "  - every module3-group-N-runtime-egress NetworkPolicy in namespace digitafrica, for any group" \
    "Option 11 previews the reset without changing anything."
  confirm "Permanently delete this Module 3 runtime state" ||
    return 1
  cloud_module3_runtime_reset reset
}
