#!/usr/bin/env bash
set -euo pipefail
OPERATIONS_SCRIPTS=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd -- "$OPERATIONS_SCRIPTS/.." && pwd)
fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null || fail "Required command: $1"; }
# Quote each argument for the remote login shell; never interpolate untrusted code.
remote() {
    need ssh
    local command
    printf -v command '%q ' "$@"
    ssh -F "$HOME/.ssh/config" -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 aws-prod "$command"
}
select_environment() {
    case "$1" in homolog) port=28962 ;; production) port=28960 ;; *) fail 'Environment must be homolog or production' ;; esac
    environment=$1
    container="cod4-$environment"
}
inspect_runtime() {
    need python3
    inspection=$(remote docker inspect "$container") || fail "Cannot inspect $container"
    read -r project service < <(python3 -c '
import json,sys
c=json.load(sys.stdin)[0]; l=c["Config"].get("Labels") or {}
p=l.get("com.docker.compose.project", ""); s=l.get("com.docker.compose.service", "")
if not p or not s: sys.exit(1)
print(p,s)
' <<< "$inspection")
    [[ ${project:-} =~ ^[a-zA-Z0-9_-]+$ && ${service:-} =~ ^[a-zA-Z0-9_-]+$ ]] || fail 'Container must belong to a Compose project'
}
snapshot_runtime() {
    inspect_runtime
    work=$(python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["Config"]["Labels"].get("com.docker.compose.project.working_dir", ""))' <<< "$inspection")
    [[ "$work" == /opt/services/cod4 || "$work" == /opt/services/cod4/* ]] || fail 'Unexpected Compose directory'
    [[ "$(python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["State"]["Running"])' <<< "$inspection")" == True ]] || fail 'Deployment requires a running baseline for rollback'
    python3 -c 'import json,sys; c=json.load(sys.stdin)[0]; ports=c["HostConfig"].get("PortBindings") or {}; any(k.endswith("/udp") and any(b["HostPort"]==sys.argv[1] for b in (bindings or [])) for k,bindings in ports.items()) or sys.exit("Expected published UDP port missing")' "$port" <<< "$inspection" || fail 'Runtime UDP mapping does not match the selected environment'
    # Resolve the actual files and project directory from Docker labels remotely.
    config=$(remote bash -s -- "$container" <<'REMOTE'
set -euo pipefail
name=$1
for dependency in docker timeout dd grep mktemp mv rm; do command -v "$dependency" >/dev/null || { echo "Missing remote dependency: $dependency" >&2; exit 1; }; done
label() { docker inspect --format "{{index .Config.Labels \"$1\"}}" "$name"; }
project=$(label com.docker.compose.project)
service=$(label com.docker.compose.service)
work=$(label com.docker.compose.project.working_dir)
files=$(label com.docker.compose.project.config_files)
[[ "$work" == /opt/services/cod4 || "$work" == /opt/services/cod4/* ]] || { echo 'Unexpected Compose directory' >&2; exit 1; }
cd -- "$work"
IFS=, read -r -a paths <<< "$files"
args=()
for path in "${paths[@]}"; do [[ -f "$path" ]] || exit 1; args+=(-f "$path"); done
expected=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.config-hash"}}' "$name")
actual=$(docker compose -p "$project" "${args[@]}" config --hash "$service")
[[ "${actual##* }" == "$expected" ]] || { echo 'Runtime differs from Compose; reconcile it before deployment' >&2; exit 1; }
docker compose -p "$project" "${args[@]}" config --format json
REMOTE
) || fail 'Cannot resolve live Compose configuration'
    python3 -c 'import json,sys; c=json.load(sys.stdin); s=c["services"][sys.argv[1]]; s.get("container_name")==sys.argv[2] or sys.exit("Explicit matching container_name required"); not s.get("build") or sys.exit("Prebuilt-only service required")' "$service" "$container" <<< "$config" || fail 'Unsupported Compose service'
}
apply_runtime() {
    # A persistent runtime configuration keeps Compose discovery valid after recreation.
    # Only configuration is written remotely; no deployment scripts are uploaded.
    # The single-quoted Bash payload expands its arguments on the remote host.
    # shellcheck disable=SC2016
    python3 -c '
import json,sys
def escape(v):
    if isinstance(v,str): return v.replace("$","$$")
    if isinstance(v,list): return [escape(x) for x in v]
    if isinstance(v,dict): return {k:escape(x) for k,x in v.items()}
    return v
print(json.dumps(escape(json.load(sys.stdin))))
' | remote bash -c '
set -euo pipefail
umask 077
file="/opt/services/cod4/.operations-$1.json"
temporary=$(mktemp /opt/services/cod4/.operations.XXXXXX)
trap "rm -f -- \"\$temporary\"" EXIT
cat > "$temporary"
mv -- "$temporary" "$file"
docker compose --project-directory "$4" -p "$2" -f "$file" up -d --no-deps --pull never --force-recreate "$3"
' bash "$environment" "$project" "$service" "$work"
}
check_health() {
    remote bash -s -- "${2:-$container}" "${3:-$port}" "${1:-}" <<'REMOTE'
set -euo pipefail
expected_gametype=
case "$3" in mods/btd_alpha_001) expected_gametype=war ;; mods/pml220) expected_gametype=sd ;; esac
for attempt in {1..90}; do
    state=$(docker inspect --format '{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$1")
    if [[ "$state" == 'true healthy' || "$state" == 'true none' ]]; then
        if response=$(timeout 3 bash -c 'exec 3<>/dev/udp/127.0.0.1/"$1"; printf "\377\377\377\377getstatus\n" >&3; dd bs=65535 count=1 <&3 2>/dev/null ' bash "$2"); then
            if LC_ALL=C grep -aq statusResponse <<< "$response" && { [[ -z "$3" ]] || grep -Fq -- "\\fs_game\\$3\\" <<< "$response"; }; then
                if [[ -z "$expected_gametype" ]] || { grep -Fq -- "\\g_gametype\\$expected_gametype\\" <<< "$response" && grep -Fq -- '\sv_pure\1\' <<< "$response"; }; then exit 0; fi
            fi
        fi
    fi
    sleep 2
done
echo 'Startup or UDP query check failed' >&2
exit 1
REMOTE
}
image_config() {
    if [[ ${2:-original} == artifact ]]; then
        python3 "$OPERATIONS_SCRIPTS/runtime.py" adapt "$service" "$1" "$mode_id" "$config_hash" \
            "$mode_fs_game" "$startup_map" "$mode_maps" "$mode_maxclients" <<< "$config"
    else
        # Rollback retains the exact original command and private runtime configuration.
        python3 -c 'import json,sys; c=json.load(sys.stdin); c["services"][sys.argv[1]]["image"]=sys.argv[2]; print(json.dumps(c))' "$service" "$1" <<< "$config"
    fi
}
runtime_mode() {
    python3 -c '
import json,sys
args=json.load(sys.stdin)["services"][sys.argv[1]].get("command",[])
values=[args[i+2] for i in range(len(args)-2) if args[i:i+2]==["+set","fs_game"]]
if len(values)!=1: sys.exit("Expected one explicit game mode")
print(values[0])
' "$service" <<< "$config"
}
verify_homolog() {
    local evidence
    evidence=$(remote docker inspect cod4-homolog) || return 1
    python3 "$OPERATIONS_SCRIPTS/runtime.py" verify "$1" "$revision" "$config_revision" \
        "$mode_id" "$config_hash" "$mode_fs_game" "$startup_map" "$mode_maps" "$mode_maxclients" <<< "$evidence" || {
        printf 'Homolog artifact provenance failed; nothing deployed\n' >&2; return 1;
    }
    check_health "$mode_fs_game" cod4-homolog 28962
}
confirm() {
    [[ -t 0 ]] || fail 'Interactive terminal required'
    local answer
    read -r -p "$1 Type yes: " answer
    [[ "$answer" == yes ]] || fail 'Confirmation declined'
}
deploy_image_locked() {
    need docker
    need python3
    local metadata identity image_revision platform host_platform previous candidate previous_mode startup_contract
    local -a startup_values
    metadata=$(docker image inspect "$1") || fail "Local image not found: $1"
    identity=$(python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["Id"])' <<< "$metadata")
    [[ "$identity" =~ ^sha256:[a-f0-9]{64}$ && "$identity" == "$1" ]] || fail 'Local image identity differs from the recorded artifact'
    image_revision=$(python3 -c 'import json,sys; print((json.load(sys.stdin)[0]["Config"].get("Labels") or {}).get("org.opencontainers.image.revision", ""))' <<< "$metadata")
    [[ "$image_revision" == "$revision" ]] || fail 'Image revision differs from approved artifact'
    startup_contract=$(python3 "$OPERATIONS_SCRIPTS/runtime.py" identity "$identity" "$revision" "$asset_ref" \
        "$bot_revision" "$config_revision" "$mode_id" "$config_hash" "$ENGINE_REPOSITORY" <<< "$metadata") || fail 'Image dependency identity mismatch'
    mapfile -t startup_values <<< "$startup_contract"
    mode_fs_game=${startup_values[0]}; startup_map=${startup_values[1]}; mode_maps=${startup_values[2]}; mode_maxclients=${startup_values[3]}
    platform=$(python3 -c 'import json,sys; c=json.load(sys.stdin)[0]; print(c["Os"]+"/"+c["Architecture"])' <<< "$metadata")
    host_platform=$(remote docker version --format '{{.Server.Os}}/{{.Server.Arch}}') || fail 'Cannot verify the host platform'
    [[ "$platform" == "$host_platform" ]] || fail "Image platform $platform differs from host $host_platform"
    if [[ "$environment" == production ]]; then
        [[ "$(remote docker inspect --format '{{.Image}} {{.State.Running}}' cod4-homolog)" == "$identity true" ]] || fail 'Approved image is no longer running in homolog'
        verify_homolog "$identity" || return 1
    fi
    snapshot_runtime || return 1
    previous=$(python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["Image"])' <<< "$inspection")
    candidate=$(image_config "$identity" artifact) || fail 'Cannot safely adapt this runtime configuration'
    previous_mode=$(runtime_mode) || return 1
    if [[ "$environment" == production ]]; then
        printf 'Production plan: host=aws-prod container=%s project=%s service=%s UDP=%s mode=%s\nPrevious image: %s\nApproved image: %s\nSource revision: %s\nMounts and other runtime settings retained; packaged binary/mods selected. Failure triggers rollback.\n' "$container" "$project" "$service" "$port" "$mode_id" "$previous" "$identity" "$revision"
        confirm 'Recreate cod4-production and disconnect players?' || return 1
        verify_homolog "$identity" || return 1
    fi
    # Keep rollback evidence even if this process or SSH is interrupted.
    image_config "$previous" > "$ROOT/.state/rollback-$environment.json" || fail 'Cannot persist the exact rollback configuration'
    # pipefail prevents applying an incomplete image transfer.
    docker image save "$identity" | remote docker image load >/dev/null || fail 'Image transfer failed; runtime was not changed'
    host_runtime_safe=0
    if apply_runtime <<< "$candidate" && check_health "$mode_fs_game" && [[ "$(remote docker inspect --format '{{.Image}}' "$container")" == "$identity" ]]; then
        host_runtime_safe=1
        printf 'Deployed %s revision %s to %s\n' "$identity" "$revision" "$environment"
    else
        printf 'Deployment failed for %s. Restoring previous image %s.\n' "$environment" "$previous" >&2
        if apply_runtime <<< "$(image_config "$previous")" && check_health "$previous_mode" && [[ "$(remote docker inspect --format '{{.Image}}' "$container")" == "$previous" ]]; then
            host_runtime_safe=1
            printf 'Rollback healthy: %s\n' "$previous" >&2
        else
            printf 'ROLLBACK FAILED: inspect %s immediately.\n' "$container" >&2
        fi
        return 1
    fi
    if [[ "$environment" == homolog ]]; then
        confirm 'Health checks passed. Approve this exact artifact for production?' || return 1
        mkdir -p -- "$ROOT/.state" || fail 'Cannot create approval directory'
        write_artifact_record "$identity" > "$ROOT/.state/approved.next" || fail 'Cannot write complete approval record'
        mv -- "$ROOT/.state/approved.next" "$ROOT/.state/approved" || fail 'Cannot commit approval record'
    fi
}

# Production deployment and the host mode controller share this host lease.
# Before bridge installation the absent file preserves the existing workflow.
# Installation creates a root-owned 0644 lock in a root-owned parent directory.
deploy_image() {
    local lease_pid lease_read lease_write lease_state result=0
    if [[ "$environment" == production ]]; then
        coproc MODE_LEASE { remote bash -c '
set -euo pipefail
file=/opt/services/cod4/.production-transition.lock
if [[ ! -e "$file" ]]; then printf "legacy\n"; read -r release; exit; fi
[[ ! -L "$file" && "$(stat -c %u "$file")" == 0 && "$(stat -c %a "$file")" == 644 ]] || exit 1
exec 9< "$file"
flock -n 9 || exit 2
marker=/opt/services/cod4/.production-deployment.json
[[ ! -e "$marker" && ! -L "$marker" ]] || exit 2
umask 077
(set -o noclobber; printf "{\"phase\":\"deployment-in-progress-or-interrupted\"}\n" > "$marker")
printf "locked\n"
if read -r release && [[ "$release" == release ]]; then rm -- "$marker"; fi
' mode-deployment-lease; }
        lease_pid=$MODE_LEASE_PID
        lease_read=${MODE_LEASE[0]}; lease_write=${MODE_LEASE[1]}
        IFS= read -r -t 15 lease_state <&"$lease_read" || fail 'Host production transition lock unavailable'
        if [[ "$lease_state" == locked || "$lease_state" == legacy ]]; then
            host_runtime_safe=1
        else fail 'Invalid production transition lock response'; fi
    fi
    deploy_image_locked "$@" || result=$?
    if [[ "$environment" == production ]]; then
        if [[ $host_runtime_safe == 1 ]]; then printf "release\n" >&"$lease_write" || true
        else printf "hold\n" >&"$lease_write" || true; fi
        wait "$lease_pid" || true
    fi
    return "$result"
}

CONFIG_REPOSITORY=https://github.com/ghptc/cod4-config-server.git
ENGINE_REPOSITORY=https://github.com/ghptc/cod4x-server.git
BUILDER=sha256:92528811226fabd05fee63074e22b7b5afd0fa9d63d5994bd3a8f74c8543cbfe
RUNTIME_BASE=sha256:7050ddb6927fdf0b6703d605f23ebcf2bfb14553c1db01173ec0035294995770
checkout_master() {
    git init -q "$2" || fail 'Cannot create isolated checkout'
    git -C "$2" remote add origin "$1" || fail 'Cannot configure origin'
    git -C "$2" fetch --no-tags origin '+refs/heads/master:refs/remotes/origin/master' || fail 'Cannot fetch origin/master; nothing deployed'
    local commit
    commit=$(git -C "$2" rev-parse --verify 'origin/master^{commit}') || fail 'Cannot resolve master commit'
    [[ "$commit" =~ ^[a-f0-9]{40}$ ]] || fail 'Invalid master revision'
    git -C "$2" -c advice.detachedHead=false checkout -q --detach "$commit" || fail 'Checkout failed'
    [[ -z "$(git -C "$2" status --porcelain --untracked-files=all)" ]] || fail 'Checkout is not clean'
}
resolve_master() {
    need python3
    checkout_master "$ENGINE_REPOSITORY" "$stage/engine"
    revision=$(git -C "$stage/engine" rev-parse HEAD)
    checkout_master "$CONFIG_REPOSITORY" "$stage/config"
    config_revision=$(git -C "$stage/config" rev-parse HEAD)
    select_mode
    local dependency_lock=bots/dependencies.json
    if [[ "$mode_fs_game" == mods/btd_alpha_001 ]]; then dependency_lock=tools/btd/dependencies.json; fi
    bridge_protocol=disabled
    if [[ -f "$stage/engine/src/sv_mode_bridge.c" ]]; then bridge_protocol=C4M1; fi
    asset_ref=$(sha256sum "$stage/engine/$dependency_lock") || fail 'Dependency lock missing'
    asset_ref=${asset_ref%% *}
    bot_revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["bot_warfare"]["commit"])' "$stage/engine/bots/dependencies.json") || fail 'Cannot read Bot Warfare revision'
    if [[ "$mode_fs_game" == mods/btd_alpha_001 ]]; then bot_revision=none; fi
    [[ "$bot_revision" == none || "$bot_revision" =~ ^[a-f0-9]{40}$ ]] || fail 'Invalid locked Bot Warfare revision'
    printf 'Resolved engine=%s config=%s mode=%s bot-warfare=%s\n' "$revision" "$config_revision" "$mode_id" "$bot_revision"
}
select_mode() {
    local contract
    local -a values
    contract=$(python3 "$OPERATIONS_SCRIPTS/modes.py" select "$stage/config" "$mode_id") || fail 'Invalid mode catalog'
    mapfile -t values <<< "$contract"
    mode_fs_game=${values[0]}; startup_map=${values[1]}; config_hash=${values[2]}; mode_maps=${values[3]}; mode_maxclients=${values[4]}
}
build_selected_mode() {
    case "$mode_fs_game" in
        mods/pml220) build_promod ;;
        mods/btd_alpha_001) build_zombies ;;
        *) fail 'No verified asset preparation recipe for selected fs_game' ;;
    esac
}
build_promod() {
    need python3
    need gcc
    python3 -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required on local host"' || fail 'Local Python dependency unavailable'
    local promod headers bot_repository base_tag
    [[ -n ${COD4_PROMOD_ASSETS:-} && -n ${COD4_INTEGRITY_HEADERS:-} ]] || fail 'Explicit authorized COD4_PROMOD_ASSETS and COD4_INTEGRITY_HEADERS required; no historical workspace fallback'
    [[ -n ${COD4_OAT:-} && -x "$COD4_OAT/Linker" && -x "$COD4_OAT/Unlinker" ]] || fail 'COD4_OAT must contain official OAT v0.34.0 tools'
    promod=$(realpath -- "${COD4_PROMOD_ASSETS}") || fail 'Cannot resolve Promod asset path'
    headers=$(realpath -- "${COD4_INTEGRITY_HEADERS}") || fail 'Cannot resolve header path'
    [[ -d "$promod" && -d "$headers" ]] || fail 'Verified local Promod assets and integrity headers are required'
    bot_repository=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["bot_warfare"]["repository"])' "$stage/engine/bots/dependencies.json") || fail 'Cannot read Bot Warfare source'
    [[ "$bot_repository" == https://github.com/ineedbots/iw3_bot_warfare ]] || fail 'Unexpected Bot Warfare source; review dependency change'
    git init -q "$stage/bots" || fail 'Cannot create Bot Warfare checkout'
    git -C "$stage/bots" remote add origin "$bot_repository" || fail 'Cannot configure Bot Warfare origin'
    git -C "$stage/bots" fetch --depth 1 origin "$bot_revision" || fail 'Cannot fetch locked Bot Warfare source'
    git -C "$stage/bots" -c advice.detachedHead=false checkout -q --detach "$bot_revision" || fail 'Cannot check out locked Bot Warfare commit'
    [[ "$(git -C "$stage/bots" rev-parse HEAD)" == "$bot_revision" && -z "$(git -C "$stage/bots" status --porcelain --untracked-files=all)" ]] || fail 'Bot Warfare checkout identity/cleanliness mismatch'
    docker image inspect "$BUILDER" "$RUNTIME_BASE" >/dev/null || fail 'Pinned local builder/runtime image missing; see README'
    docker run --rm --pull never --network none --user "$(id -u):$(id -g)" \
        --mount "type=bind,src=$stage/engine,dst=/src" --workdir /src "$BUILDER" \
        bash -euo pipefail -c 'make -j2; gcc -Wall -Wextra -Werror tests/test_bot_policy.c -o /tmp/cod4-policy; /tmp/cod4-policy; readelf -h bin/cod4x18_dedrun | grep -q "Intel 80386"' || fail 'Local compilation or engine validation failed'
    python3 "$stage/engine/tests/test_integrity_headers.py" || fail 'Local integrity validation failed'
    python3 -m unittest discover -s "$stage/engine/tests" -p 'test_fps_menu.py' || fail 'FPS policy validation failed'
    python3 -m unittest discover -s "$stage/engine/tests" -p 'test_punkbuster_policy.py' || fail 'PB policy validation failed'
    python3 "$stage/engine/tools/bots/prepare.py" --promod "$promod" --bot-warfare "$stage/bots" \
        --headers "$headers" --binary "$stage/engine/bin/cod4x18_dedrun" --output "$stage/runtime" \
        --allow-no-punkbuster --allow-map-voting || fail 'Runtime assets failed verification'
    [[ -s "$stage/runtime/mods/pml220/promod/comp.gsx" && -s "$stage/runtime/mods/pml220/promod/readyup.gsx" ]] || fail 'Promod voting/Ready Up overlays missing'
    [[ -s "$stage/runtime/mods/pml220/promod/servercheck.gsx" ]] || fail 'Promod PB warning overlay missing'
    python3 "$stage/engine/tools/promod/fps333.py" --promod "$promod/mod.ff" \
        --oat "$COD4_OAT" --output "$stage/fps333" || fail 'FPS menu rebuild failed'
    cp -- "$stage/fps333/project/zone_out/fps333/mod.ff" "$stage/runtime/mods/pml220/mod.ff" || fail 'FPS asset missing'
    cp -- "$stage/fps333/manifest.json" "$stage/runtime/fps333.json"
    cp -r -- "$stage/fps333/project/raw" "$stage/runtime/fps333-source"
    python3 "$OPERATIONS_SCRIPTS/modes.py" package "$stage/config" "$mode_id" "$stage/runtime" \
        "$revision" "$config_revision" "$bot_revision" || fail 'Mode configuration packaging failed'
    mkdir "$stage/runtime/licenses" || fail 'Cannot prepare runtime notices'
    cp -- "$stage/engine/License.md" "$stage/engine/Copyright.md" "$stage/engine/copying.md" "$stage/engine/docs/third-party-bots.md" "$stage/runtime/licenses/" || fail 'Cannot retain engine notices'
    cp -- "$stage/bots/README.md" "$stage/runtime/licenses/Bot-Warfare-README.md" || fail 'Cannot retain Bot Warfare notices'
    package_image
}
build_zombies() {
    need python3
    [[ -n ${COD4_BTD_ASSETS:-} && -n ${COD4_INTEGRITY_HEADERS:-} ]] || fail 'Explicit authorized COD4_BTD_ASSETS and COD4_INTEGRITY_HEADERS required'
    local source headers
    source=$(realpath -- "$COD4_BTD_ASSETS") || fail 'Cannot resolve BTD asset path'
    headers=$(realpath -- "$COD4_INTEGRITY_HEADERS") || fail 'Cannot resolve header path'
    [[ -d "$source" && -d "$headers" ]] || fail 'Private original BTD package and headers required'
    docker image inspect "$BUILDER" "$RUNTIME_BASE" >/dev/null || fail 'Pinned local builder/runtime image missing'
    docker run --rm --pull never --network none --user "$(id -u):$(id -g)" \
        --mount "type=bind,src=$stage/engine,dst=/src" --workdir /src "$BUILDER" \
        bash -euo pipefail -c 'make -j2; readelf -h bin/cod4x18_dedrun | grep -q "Intel 80386"' || fail 'Local engine compilation failed'
    python3 "$stage/engine/tools/btd/prepare.py" --source "$source" --headers "$headers" \
        --binary "$stage/engine/bin/cod4x18_dedrun" --output "$stage/runtime" || fail 'Original BTD asset verification failed'
    python3 "$OPERATIONS_SCRIPTS/modes.py" package "$stage/config" "$mode_id" "$stage/runtime" \
        "$revision" "$config_revision" "$bot_revision" || fail 'Mode configuration packaging failed'
    cp -- "$stage/engine/License.md" "$stage/engine/Copyright.md" "$stage/engine/copying.md" "$stage/runtime/licenses/"
    package_image
}
package_image() {
    local base_tag
    base_tag="ec2-workspace-base:${RUNTIME_BASE#sha256:}"
    docker image tag "$RUNTIME_BASE" "$base_tag" || fail 'Cannot tag the pinned local runtime base'
    cat > "$stage/Dockerfile" <<DOCKERFILE
FROM $base_tag
COPY runtime/ /opt/cod4-artifact/
USER root
RUN chmod -R a+rX /opt/cod4-artifact && ln -s /home/user/cod4/main /opt/cod4-artifact/main && ln -s /home/user/cod4/zone /opt/cod4-artifact/zone && ln -s /home/user/cod4/usermaps /opt/cod4-artifact/usermaps && ln -s /home/user/cod4/plugins /opt/cod4-artifact/plugins
USER 1000:1000
WORKDIR /opt/cod4-artifact
ENTRYPOINT ["/opt/cod4-artifact/cod4x18_dedrun"]
LABEL io.cod4.rcon-mode-bridge="$bridge_protocol" org.opencontainers.image.source="$ENGINE_REPOSITORY" org.opencontainers.image.revision="$revision" io.cod4.assets.lock="$asset_ref" io.cod4.bot-warfare.revision="$bot_revision" io.cod4.config.revision="$config_revision" io.cod4.mode="$mode_id" io.cod4.config.hash="$config_hash" io.cod4.fs-game="$mode_fs_game" io.cod4.startup-map="$startup_map" io.cod4.maps="$mode_maps" io.cod4.maxclients="$mode_maxclients"
DOCKERFILE
    # Keep source and Git metadata out of the Docker context and runtime image.
    printf 'engine\nconfig\nbots\nfps333\n' > "$stage/.dockerignore"
    docker build --pull=false --network none --iidfile "$stage/image-id" "$stage" || fail 'Local image build failed'
    artifact=$(cat "$stage/image-id") || fail 'Image builder did not record an identity'
    docker run --rm --pull never --network none --read-only --entrypoint /bin/sh "$artifact" \
        -ec 'test -x /opt/cod4-artifact/cod4x18_dedrun; test -s "/opt/cod4-artifact/$1/mod.ff"; test -s "/opt/cod4-artifact/$1/canonical-shared.cfg"; test -s "/opt/cod4-artifact/$1/canonical-mode.cfg"; test -s /opt/cod4-artifact/configuration/mode.cfg; test -s /opt/cod4-artifact/inputs.json; test -s /opt/cod4-artifact/integrity/addiwdheaders/jcod4x_00.dat; if [ "$1" = mods/pml220 ]; then test -s /opt/cod4-artifact/mods/pml220/promod/servercheck.gsx; test -s /opt/cod4-artifact/fps333.json; else for name in btd_images btd_music btd_weapons; do test -s "/opt/cod4-artifact/$1/$name.iwd"; done; fi; libraries=$(ldd /opt/cod4-artifact/cod4x18_dedrun); case "$libraries" in *"not found"*) exit 1;; esac' sh "$mode_fs_game" || fail 'Packaged runtime validation failed'

}
write_artifact_record() {
    printf '%s %s %s %s %s %s %s\n' "$1" "$revision" "$asset_ref" "$bot_revision" "$config_revision" "$mode_id" "$config_hash"
}
read_approval() {
    local approved_mode extra
    [[ -f "$ROOT/.state/approved" ]] || fail 'No approved homolog artifact; deploy homolog first'
    [[ $(wc -l < "$ROOT/.state/approved") == 1 ]] || fail 'Malformed approval record'
    read -r artifact revision asset_ref bot_revision config_revision approved_mode config_hash extra < "$ROOT/.state/approved" || fail 'Malformed approval record'
    [[ "$config_revision" =~ ^[a-f0-9]{40}$ && -z "$extra" && "$revision" =~ ^[a-f0-9]{40}$ && "$asset_ref" =~ ^[a-f0-9]{64}$ && ( "$bot_revision" == none || "$bot_revision" =~ ^[a-f0-9]{40}$ ) && "$config_hash" =~ ^[a-f0-9]{64}$ && "$approved_mode" =~ ^[a-z][a-z0-9-]*$ ]] || fail 'Malformed approval record; legacy artifacts require fresh homolog qualification'
    [[ "$approved_mode" == "$mode_id" ]] || fail 'Requested mode differs from approved homolog artifact'
}
# Deployment resolution intentionally stays inside its operation subshell.
# shellcheck disable=SC2030
deploy() (
    [[ $# == 1 && "$1" =~ ^[a-z][a-z0-9-]*$ ]] || fail "Usage: deploy-$environment.sh mode-id"
    mode_id=$1
    for dependency in docker python3 flock; do need "$dependency"; done
    umask 077
    mkdir -p -- "$ROOT/.state"
    exec 9> "$ROOT/.state/deploy.lock"
    flock -n 9 || fail 'Another deployment is running in this checkout'
    if [[ "$environment" == homolog ]]; then
        for dependency in git sha256sum realpath; do need "$dependency"; done
        stage=$(mktemp -d "$ROOT/.state/build.XXXXXX")
        trap 'rm -rf -- "$stage"' EXIT
        resolve_master
        build_selected_mode
    else
        read_approval
    fi
    [[ "$artifact" =~ ^sha256:[a-f0-9]{64}$ ]] || fail 'Invalid artifact image ID'
    if [[ ${COD4_PREPARE_ONLY:-0} == 1 ]]; then
        write_artifact_record "$artifact" > "$ROOT/.state/prepared"
        printf 'Prepared locally: %s\n' "$artifact"
    else
        deploy_image "$artifact"
    fi
)
