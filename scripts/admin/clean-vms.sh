#!/usr/bin/env bash
# Clean dedicated edge-ai-blueprint/DIGITAfrica test VMs, preserving SSH keys.
set -Eeuo pipefail
SELF="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/$(basename -- "${BASH_SOURCE[0]}")"
die(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }
usage(){ cat <<'EOF'
Usage: clean-vms.sh --inventory <hosts.ini> [--limit <pattern>] [--dry-run] [--yes] [--purge-runtime]
--purge-runtime removes all Docker state and both k3s server and k3s agent state.
Use it only on dedicated disposable VMs.
EOF
}
remote_cleanup(){
  local dry="$1" purge="$2" before after
  before="$(mktemp)"; after="$(mktemp)"
  run(){ if [[ "$dry" == true ]]; then printf '[dry-run] '; printf '%q ' "$@"; printf '\n'; else "$@"; fi; }
  fingerprint(){ find /root /home -xdev -type f -path '*/.ssh/authorized_keys' -print0 2>/dev/null | sort -z | xargs -0r sha256sum | sort; }
  remove(){ local p="$1"; [[ -n "$p" && "$p" != / ]] || die "unsafe removal path: $p"; [[ -e "$p" || -L "$p" ]] && run rm -rf -- "$p" || true; }

  fingerprint >"$before"
  printf '%s\n' 'Preserving SSH authorised_keys:'; cut -d' ' -f3- "$before" || true
  while IFS= read -r unit; do
    [[ -n "$unit" ]] || continue
    run systemctl disable --now "$unit" || true; run rm -f "/etc/systemd/system/$unit"
  done < <(systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -E '^(digitafrica|flower|fl-workshop|jupyterhub)[A-Za-z0-9_.@-]*\.service$' || true)
  run systemctl daemon-reload || true

  if command -v helm >/dev/null 2>&1; then
    while read -r release namespace _; do
      case "${release,,}:${namespace,,}" in *digitafrica*:*|*flower*:*|*jupyterhub*:*) run helm uninstall "$release" -n "$namespace" || true;; esac
    done < <(helm list -A --no-headers 2>/dev/null || true)
  fi
  if command -v kubectl >/dev/null 2>&1; then
    for ns in digitafrica flower jupyterhub; do kubectl get namespace "$ns" >/dev/null 2>&1 && run kubectl delete namespace "$ns" --wait=true --timeout=180s || true; done
  fi
  for p in /opt/edge-ai-blueprint /srv/edge-ai-blueprint /opt/digitafrica /srv/digitafrica /etc/digitafrica /var/lib/digitafrica /var/log/digitafrica /run/digitafrica; do remove "$p"; done
  for p in /home/*/edge-ai-blueprint /home/*/fl-workshop /home/*/.venvs/fl-workshop; do
    [[ -e "$p" || -L "$p" ]] && remove "$p"
  done

  if [[ "$purge" == true ]]; then
    printf '%s\n' 'Purging Docker, k3s-server, and k3s-agent runtime state.'
    run systemctl stop docker.socket || true; run systemctl stop docker.service || true; run systemctl stop containerd.service || true
    run systemctl kill --kill-who=all docker.service || true; run systemctl kill --kill-who=all containerd.service || true
    run pkill -9 -f 'containerd-shim|docker-proxy' || true
    for root in /var/lib/docker /var/lib/containerd; do
      while IFS= read -r mount; do [[ -n "$mount" && "$mount" != / ]] && run umount -l -- "$mount" || true; done < <(findmnt -R -n -o TARGET "$root" 2>/dev/null | sort -r || true)
    done

    # A Tier-1 inventory contains both server and agent VMs. The previous version
    # removed only k3s server state; this explicitly removes agents as well.
    if [[ -x /usr/local/bin/k3s-agent-uninstall.sh ]]; then run /usr/local/bin/k3s-agent-uninstall.sh || true; fi
    if [[ -x /usr/local/bin/k3s-uninstall.sh ]]; then run /usr/local/bin/k3s-uninstall.sh || true
    elif command -v k3s-uninstall.sh >/dev/null 2>&1; then run k3s-uninstall.sh || true; fi
    if command -v microk8s >/dev/null 2>&1; then run microk8s stop || true; run snap remove microk8s --purge || true; fi

    # Cover residual k3s state if an interrupted old installation left it behind.
    for p in /etc/rancher /var/lib/rancher /var/lib/kubelet /var/lib/cni /run/k3s; do remove "$p"; done
    run rm -rf -- /var/lib/docker /var/lib/containerd
    if [[ "$dry" != true ]] && { [[ -e /var/lib/docker ]] || [[ -e /var/lib/containerd ]] || [[ -e /var/lib/rancher ]]; }; then die 'container or k3s runtime state remains after cleanup'; fi
  fi

  fingerprint >"$after"
  if ! cmp -s "$before" "$after"; then diff -u "$before" "$after" || true; die 'SSH authorised_keys changed'; fi
  rm -f -- "$before" "$after"; printf '%s\n' 'Cleanup complete; SSH authorised_keys were preserved.'
}
if [[ "${1:-}" == --remote-cleanup ]]; then shift; remote_cleanup "${1:?}" "${2:?}"; exit 0; fi
inventory=""; limit=all; dry=false; purge=false; yes=false
while [[ $# -gt 0 ]]; do case "$1" in
  -i|--inventory) inventory="${2:?}"; shift 2;; -l|--limit) limit="${2:?}"; shift 2;; --dry-run) dry=true; shift;; --purge-runtime) purge=true; shift;; -y|--yes) yes=true; shift;; -h|--help) usage; exit 0;; *) die "unknown argument: $1";; esac; done
[[ -n "$inventory" && -f "$inventory" ]] || die 'a valid --inventory is required'; command -v ansible >/dev/null || die 'Ansible is required'; [[ "$dry" == true || "$yes" == true ]] || die 'use --dry-run first, then --yes'
printf 'Inventory: %s\nLimit: %s\nDry run: %s\nPurge runtime: %s\n' "$inventory" "$limit" "$dry" "$purge"
# Explicit interpreter prevents Ansible from invoking this Bash script under /bin/sh.
args=("$limit" -i "$inventory" -b -m ansible.builtin.script -a "$SELF --remote-cleanup $dry $purge executable=/bin/bash")
[[ "$dry" == true ]] && args=(-v "${args[@]}")
ansible "${args[@]}"
