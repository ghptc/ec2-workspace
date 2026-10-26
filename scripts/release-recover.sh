#!/usr/bin/env bash
# Explicit operator recovery only. Never invoked by CI or during this task.
set -euo pipefail
# shellcheck source=scripts/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
# shellcheck source=scripts/release-deploy.sh
source "$OPERATIONS_SCRIPTS/release-deploy.sh"
[[ $# == 3 && ( "$3" == rollback || "$3" == complete ) ]] || fail 'Usage: release-recover.sh homolog|production transaction-directory rollback|complete'
select_environment "$1"
release_transaction=$(realpath -- "$2")
[[ "$release_transaction" == "$ROOT/.state/deployments/$environment/transaction."* ]] || fail 'Transaction does not belong to this environment/checkout'
[[ -f "$release_transaction/events.jsonl" && -f "$release_transaction/rollback.json" ]] || fail 'Incomplete transaction evidence'
umask 077
exec 9> "$ROOT/.state/deploy.lock"
flock -n 9 || fail 'Another operation is running'
snapshot_runtime
observed=$(python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["Image"])' <<< "$inspection")
previous=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["services"][sys.argv[2]]["image"])' "$release_transaction/rollback.json" "$service")
artifact=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["image"]["id"])' "$release_transaction/release-manifest.json")
[[ "$observed" == "$previous" || "$observed" == "$artifact" ]] || fail 'Runtime changed outside this transaction; review manually'
if [[ "$environment" == production ]]; then confirm "Recover production using $3?"; fi
if [[ "$3" == rollback ]]; then
    config=$(cat "$release_transaction/rollback.json")
    previous_mode=$(runtime_mode)
    if apply_runtime <<< "$config" && check_health "$previous_mode" &&
        [[ $(remote docker inspect --format '{{.Image}}' "$container") == "$previous" ]]; then
        release_journal rolled-back 'Operator restored exact saved baseline'
    else
        release_journal recovery-required 'Operator rollback failed'
        exit 1
    fi
else
    [[ "$observed" == "$artifact" ]] || fail 'Candidate is not running'
    metadata=$(remote docker image inspect "$artifact")
    mode_fs_game=$(python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["Config"]["Labels"]["io.cod4.fs-game"])' <<< "$metadata")
    mode_maxclients=$(python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["Config"]["Labels"]["io.cod4.maxclients"])' <<< "$metadata")
    # Exact original Compose candidate, including private argv/mounts, must still match.
    python3 -c 'import json,sys; a=json.load(open(sys.argv[1])); b=json.load(sys.stdin); assert a["services"][sys.argv[2]]==b["services"][sys.argv[2]], "Candidate configuration drift"' "$release_transaction/candidate.json" "$service" <<< "$config"
    check_health "$mode_fs_game"
    check_release_effective
    evidence=$(mktemp "$release_transaction/recovered-github.XXXXXX.json")
    python3 "$OPERATIONS_SCRIPTS/release.py" record "$release_transaction/release-manifest.json" "$environment" > "$evidence"
    release_journal complete 'Operator reconciled healthy runtime and GitHub deployment evidence'
fi
