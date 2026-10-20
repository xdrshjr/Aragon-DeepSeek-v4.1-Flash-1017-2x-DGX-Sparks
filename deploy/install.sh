#!/usr/bin/env bash
# Install these deployment files on the head Spark, where they were first used.
#
# Copies the two operator commands, the two download helpers, the three systemd
# units and the sudoers drop-in into place. Idempotent, and it starts nothing:
# the server is brought up with `serve v41` afterwards.
#
#   ./deploy/install.sh
#   ./deploy/install.sh --dry-run
set -euo pipefail

HERE=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
BIN=$HOME/bin
STATE=$HOME/.local/state/dsv41-tensorfold
DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

log() { printf '[install] %s\n' "$*"; }
die() { printf '[install] ERROR: %s\n' "$*" >&2; exit 1; }
run() { if (( DRY )); then printf '[dry-run] %s\n' "$*"; else "$@"; fi; }
as_root() {
  if (( DRY )); then printf '[dry-run] sudo %s\n' "$*"; return 0; fi
  sudo -n "$@" 2>/dev/null || sudo "$@"
}

[[ -f $HERE/bin/serve ]] || die "$HERE does not look like the deploy directory"

log "operator commands -> $BIN"
run mkdir -p "$BIN"
run install -m 755 "$HERE/bin/serve" "$BIN/serve"
run install -m 755 "$HERE/bin/prepare-v41" "$BIN/prepare-v41"

log "download helpers -> $STATE"
run mkdir -p "$STATE"
run install -m 755 "$HERE/state/download.py" "$STATE/download.py"
run install -m 755 "$HERE/state/engram_download.py" "$STATE/engram_download.py"

log "systemd units -> /etc/systemd/system"
for unit in "$HERE"/systemd/*.service; do
  as_root install -m 644 "$unit" "/etc/systemd/system/$(basename "$unit")"
done
as_root systemctl daemon-reload

# Passwordless start/stop for exactly the two serving units, so `serve` is one
# command. Still not enabled: the boot default is left as it was.
log "sudoers drop-in -> /etc/sudoers.d/dsv41-switch"
if (( DRY )); then
  printf '[dry-run] install -m 440 %s /etc/sudoers.d/dsv41-switch\n' "$HERE/sudoers/dsv41-switch"
else
  as_root install -m 440 -o root -g root "$HERE/sudoers/dsv41-switch" /etc/sudoers.d/dsv41-switch
  as_root visudo -c -f /etc/sudoers.d/dsv41-switch >/dev/null || die "the sudoers drop-in does not parse"
fi

log "done. Nothing was started."
log "  serve status   what is up"
log "  serve v41      switch to DeepSeek-V4.1-Flash-1017"
log "  serve v4       switch back"
