#!/usr/bin/env bash
# shellcheck disable=SC2154,SC2034,SC2016
# Variables are supplied by common.sh/deploy_image; quoted payload expands remotely.
# Sourced after common.sh. Explicit versions never call resolve_master/read_approval.

release_journal() {
    python3 - "$release_transaction" "$1" "${2:-}" "$environment" <<'PY'
from datetime import datetime, timezone
import json,os,sys
from pathlib import Path
root=Path(sys.argv[1]); manifest=json.loads((root/'release-manifest.json').read_text())
event={'timestamp':datetime.now(timezone.utc).isoformat(),'state':sys.argv[2], 'detail':sys.argv[3],
       'environment':sys.argv[4], 'version':manifest['tag'], 'image':manifest['image']}
if sys.argv[2]=='rolled-back':
    baseline=json.loads((root/'rollback.json').read_text())
    candidates=[s for s in baseline['services'].values() if s.get('container_name')=='cod4-'+sys.argv[4]]
    if candidates:
        event['actual_image_id']=candidates[0]['image']
        event['deployed_version']=(candidates[0].get('labels') or {}).get('io.cod4.release.tag')
if sys.argv[2]=='complete':
    event['actual_image_id']=manifest['image']['id'];event['deployed_version']=manifest['tag']
if sys.argv[2]=='mutating':
    for name in ('release-manifest.json','rollback.json','candidate.json'):
        with (root/name).open('rb') as stream: os.fsync(stream.fileno())
    directory=os.open(root,os.O_RDONLY)
    try: os.fsync(directory)
    finally: os.close(directory)
with (root/'events.jsonl').open('a') as stream:
    stream.write(json.dumps(event,sort_keys=True)+'\n'); stream.flush(); os.fsync(stream.fileno())
PY
}

check_release_effective() {
    local attempt
    for attempt in {1..20}; do
        if check_release_effective_once "$@"; then return 0; fi
        sleep 2
    done
    printf 'Effective release configuration did not become healthy\n' >&2
    return 1
}

check_release_effective_once() {
    local target=${1:-$environment} target_port credential_var credential response
    case "$target" in homolog) target_port=28962; credential_var=COD4_HOMOLOG_RCON_PASSWORD ;;
        production) target_port=28960; credential_var=COD4_PRODUCTION_RCON_PASSWORD ;; *) return 1 ;; esac
    credential=${!credential_var:-}
    [[ -n "$credential" && "$credential" != *$'\n'* && "$credential" != *$'\r'* ]] || {
        printf 'Missing or invalid %s\n' "$credential_var" >&2; return 1;
    }
    # Password travels over SSH stdin, never command argv, files or logs.
    # Each read-only cvar request gets its own response; timeouts fail closed.
    response=$(printf '%s\n' "$credential" | remote timeout 20 bash -c '
set -euo pipefail
IFS= read -r password
exec 3<>/dev/udp/127.0.0.1/"$1"
for query in sv_pure sv_autoupdate bot_enable bot_fill_limit fs_game sv_maxclients bot_status; do
    printf "\377\377\377\377rcon %s %s\n" "$password" "$query" >&3
    dd bs=65535 count=1 <&3 2>/dev/null
    printf "\n"
    sleep 0.3
done
' bash "$target_port") || return 1
    python3 "$OPERATIONS_SCRIPTS/release-health.py" "$mode_fs_game" "$mode_maxclients" <<< "$response"
}

validate_release_image() {
    python3 -c '
import json,sys
m=json.load(open(sys.argv[1])); image=json.load(sys.stdin)[0]
labels=image["Config"].get("Labels") or {}
assert image["Id"]==m["image"]["id"], "Image config digest differs"
assert m["image"]["reference"] in image.get("RepoDigests",[]), "OCI manifest digest differs"
assert labels.get("io.cod4.workspace.revision")==m["workspace"], "Workspace source differs"
assert image["Os"]+"/"+image["Architecture"]==m["image"]["platform"], "Platform differs"
' "$release_transaction/release-manifest.json"
}

verify_release_data() {
    local checks data_path
    data_path=$(python3 -c '
import json,sys
s=json.load(sys.stdin)["services"][sys.argv[1]]
mounts={m["target"]:m for m in s.get("volumes",[]) if isinstance(m,dict)}
for directory in ("main","zone"):
    m=mounts["/home/user/cod4/"+directory]
    assert m.get("type")=="bind" and m.get("read_only") is True, "Read-only game-data bind required"
    assert m["source"].endswith("/"+directory), "Canonical game-data directory required"
    print(m["source"][:-len(directory)])
' "$service" <<< "$config") || return 1
    [[ $(sort -u <<< "$data_path" | wc -l) == 1 ]] || return 1
    data_path=${data_path%%$'\n'*}
    [[ "$data_path" == /opt/services/cod4/* ]] || return 1
    checks=$(python3 -c '
import json,sys
for name,h in sorted(json.load(open(sys.argv[1]))["runtime_data"].items()): print(h+"  "+name)
' "$release_transaction/release-manifest.json") || return 1
    # Read-only validation before image transfer/configuration mutation.
    remote bash -c '
set -euo pipefail
cd -- "$1"
checks=$(cat)
[[ -z $(find main zone -type l -print -quit) ]]
actual=$(find main zone -type f -print | LC_ALL=C sort)
expected=$(sed "s/^[a-f0-9]\{64\}  //" <<< "$checks" | LC_ALL=C sort)
[[ "$actual" == "$expected" ]]
sha256sum --check --strict --status <<< "$checks"
' bash "$data_path" <<< "$checks"
}

validate_release_service() {
    python3 -c '
import json,sys
s=json.load(sys.stdin)["services"][sys.argv[1]]
assert s.get("read_only") is True, "Read-only root required"
assert not s.get("privileged") and s.get("network_mode")!="host", "Unsafe runtime isolation"
assert str(s.get("user", "")) in ("1000", "1000:1000"), "Existing non-root runtime required"
' "$service"
}

release_interrupt() {
    # Dynamic scope retains deploy_image baseline/config; no mutable source resolution.
    trap '' INT TERM HUP
    release_journal interrupted 'Attempting exact baseline restoration'
    if apply_runtime <<< "$(image_config "$previous")" && check_health "$previous_mode" &&
        [[ "$(remote docker inspect --format '{{.Image}}' "$container")" == "$previous" ]]; then
        release_journal rolled-back 'Signal rollback healthy'
    else
        release_journal recovery-required 'Signal rollback failed; retain transaction evidence'
    fi
    exit 1
}

deploy_release() (
    [[ $# == 2 && "$1" =~ ^[a-z][a-z0-9-]*$ && "$2" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-rc\.[1-9][0-9]*)?$ ]] || fail "Usage: deploy-$environment.sh mode-id vMAJOR.MINOR.PATCH[-rc.N]"
    mode_id=$1
    for dependency in python3 gh docker flock; do need "$dependency"; done
    [[ "$environment" != production || "$2" != *-rc.* ]] || fail 'Production rejects prereleases'
    # Validate credentials before any remote operation.
    credential_var="COD4_${environment^^}_RCON_PASSWORD"
    [[ -n ${!credential_var:-} ]] || fail "Required private environment variable: $credential_var"
    if [[ "$environment" == production ]]; then
        [[ -n ${COD4_HOMOLOG_RCON_PASSWORD:-} ]] || fail 'Required COD4_HOMOLOG_RCON_PASSWORD'
    fi
    umask 077
    mkdir -p "$ROOT/.state/deployments/$environment"
    exec 9> "$ROOT/.state/deploy.lock"
    flock -n 9 || fail 'Another deployment/lifecycle operation is running'
    # Do not overwrite interrupted transactions; require reviewed reconciliation.
    python3 - "$ROOT/.state/deployments/$environment" <<'PY'
import json,sys
from pathlib import Path
for p in Path(sys.argv[1]).glob('*/events.jsonl'):
    lines=p.read_text().splitlines()
    if lines and json.loads(lines[-1])['state'] not in ('complete','rolled-back','validation-failed'):
        sys.exit('Unresolved deployment transaction: '+str(p.parent))
PY
    release_transaction=$(mktemp -d "$ROOT/.state/deployments/$environment/transaction.XXXXXX")
    python3 "$OPERATIONS_SCRIPTS/release.py" resolve "$2" "$mode_id" "$environment" "$release_transaction" > "$release_transaction/resolved.json"
    release_active=1
    release_journal validated 'Immutable release and provenance verified'
    local -a values
    mapfile -t values < <(python3 - "$release_transaction/release-manifest.json" <<'PY'
import json,sys
m=json.load(open(sys.argv[1])); d=m['dependencies']
for value in (m['image']['id'],d['engine'],d['engine_dependencies_sha256'],d['bot_warfare'],d['config'],m['config_hash'],m['image']['reference']): print(value)
PY
)
    artifact=${values[0]}; revision=${values[1]}; asset_ref=${values[2]}; bot_revision=${values[3]}
    config_revision=${values[4]}; config_hash=${values[5]}
    docker pull "${values[6]}" || { release_journal validation-failed 'Immutable image unavailable'; return 1; }
    if deploy_image "$artifact"; then
        release_journal healthy 'Runtime identity and effective configuration verified'
        if python3 "$OPERATIONS_SCRIPTS/release.py" record "$release_transaction/release-manifest.json" "$environment" > "$release_transaction/github-deployment.json"; then
            release_journal complete 'GitHub environment history recorded'
        else
            release_journal recovery-required 'Healthy runtime; GitHub evidence write failed. Reconcile without redeploying.'
            return 1
        fi
    else
        # deploy_image records rollback outcome; earlier failures leave a validation event.
        last=$(python3 -c 'import json,sys; print(json.loads(open(sys.argv[1]).readlines()[-1])["state"])' "$release_transaction/events.jsonl")
        [[ "$last" != validated ]] || release_journal validation-failed 'No runtime mutation attempted'
        return 1
    fi
)
