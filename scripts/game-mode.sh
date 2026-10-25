#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
[[ $# == 2 ]] || fail 'Usage: game-mode.sh homolog|production promod'
select_environment "$1"
[[ "$2" == promod ]] || fail 'Only promod is supported'
snapshot_runtime
# Change only an existing explicit fs_game argument; do not guess startup syntax.
updated=$(python3 -c '
import json,sys
c=json.load(sys.stdin); s=c["services"][sys.argv[1]]; a=s.get("command")
if not isinstance(a,list): sys.exit("Compose command must be an argument list")
indices=[i+2 for i in range(len(a)-2) if a[i:i+2]==["+set","fs_game"]]
if len(indices)!=1: sys.exit("Expected one explicit +set fs_game argument")
i=indices[0]
if a[i] in ("promod","mods/promod","mods/pml220"): print("unchanged"); sys.exit()
a[i]="mods/pml220"; print(json.dumps(c))
' "$service" <<< "$config")
if [[ "$updated" == unchanged ]]; then
    printf '%s already selects promod\n' "$container"
    exit 0
fi
remote docker exec "$container" test -d mods/pml220
if ! { apply_runtime <<< "$updated" && check_health; }; then
    printf 'Mode change failed; restoring previous configuration\n' >&2
    apply_runtime <<< "$config" && check_health || fail 'Mode rollback failed; inspect container'
    exit 1
fi
printf 'Promod enabled for %s\n' "$environment"
