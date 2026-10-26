#!/usr/bin/env bash
# Local fixtures and mocks only: never contact EC2 or the Docker daemon.
# Mocked deployment subshells intentionally do not alter parent fixture identities.
# shellcheck disable=SC2031
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
source scripts/common.sh
python3 -m unittest discover -s tests -p 'test_*.py'
mkdir -p -- "$ROOT/.state"
test_root=$(mktemp -d "$ROOT/.state/test.XXXXXX")
trap 'rm -rf -- "$test_root"' EXIT
mkdir "$test_root/bin"
export MOCK_LOG="$test_root/commands"
cat > "$test_root/bin/ssh" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MOCK_LOG"
exit "${MOCK_SSH_EXIT:-0}"
MOCK
cat > "$test_root/bin/docker" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MOCK_LOG"
MOCK
chmod +x "$test_root/bin/ssh" "$test_root/bin/docker"
export PATH="$test_root/bin:$PATH"
for action in on on off off status; do scripts/homolog.sh "$action"; done
[[ $(wc -l < "$MOCK_LOG") == 5 ]]
grep -q 'BatchMode=yes.*StrictHostKeyChecking=yes' "$MOCK_LOG"
if grep -Eq 'production|bard|compose|create' "$MOCK_LOG"; then exit 1; else [[ $? == 1 ]]; fi
for script in production homolog deploy-homolog deploy-production game-mode; do
    if "scripts/$script.sh" >/dev/null 2>&1; then exit 1; fi
done
for script in deploy-homolog deploy-production; do
    if "scripts/$script.sh" ../invalid >/dev/null 2>&1; then exit 1; fi
done
if MOCK_SSH_EXIT=255 scripts/homolog.sh status >/dev/null 2>&1; then exit 1; fi
if (confirm 'Production test') </dev/null >/dev/null 2>&1; then exit 1; fi
printf 'PASS: command boundaries, lifecycle repetition/isolation, SSH options/failure, terminal requirement\n'

mkdir "$test_root/lifecycle"
cp scripts/common.sh scripts/production.sh "$test_root/lifecycle/"
cat >> "$test_root/lifecycle/common.sh" <<'MOCK'
remote() {
    printf '%s\n' "$*" >> "$MOCK_LOG"
    case "$1 $2" in
        'docker inspect')
            if [[ "$*" == *'configured_image='* ]]; then
                printf 'cod4-production running=%s image=sha256:fixture\n' "$(cat "$MOCK_STATE")"
            else cat "$MOCK_STATE"; fi ;;
        'docker start') printf true > "$MOCK_STATE" ;;
        'docker stop') printf false > "$MOCK_STATE" ;;
        *) return 1 ;;
    esac
}
confirm() { printf 'confirm disconnect players\n' >> "$MOCK_LOG"; [[ ${MOCK_APPROVE:-no} == yes ]]; }
MOCK
export MOCK_STATE="$test_root/lifecycle-state"
printf false > "$MOCK_STATE"
: > "$MOCK_LOG"
for action in on on; do "$test_root/lifecycle/production.sh" "$action"; done
[[ $(cat "$MOCK_STATE") == true && $(grep -c 'docker start' "$MOCK_LOG") == 1 ]]
if "$test_root/lifecycle/production.sh" off >/dev/null 2>&1; then exit 1; fi
[[ $(cat "$MOCK_STATE") == true ]]
if grep -q 'docker stop' "$MOCK_LOG"; then exit 1; fi
MOCK_APPROVE=yes "$test_root/lifecycle/production.sh" off
"$test_root/lifecycle/production.sh" off
[[ $(cat "$MOCK_STATE") == false && $(grep -c 'docker stop' "$MOCK_LOG") == 1 ]]
[[ $(grep -c 'confirm disconnect players' "$MOCK_LOG") == 2 ]]
[[ $(tail -1 "$MOCK_LOG") == *'{{.State.Running}} cod4-production' ]]
"$test_root/lifecycle/production.sh" status > "$test_root/status"
grep -q 'running=false image=sha256:fixture' "$test_root/status"
if grep -Eq 'homolog|bard|compose|build|docker rm|volume' "$MOCK_LOG"; then exit 1; fi
printf 'PASS: production lifecycle, state idempotency, shutdown confirmation, status image and isolation\n'

# Execute the real health payload locally, mocking its Docker/UDP commands only.
mkdir "$test_root/health-bin"
cat > "$test_root/health-bin/docker" <<'MOCK'
#!/usr/bin/env bash
printf 'true none\n'
MOCK
cat > "$test_root/health-bin/timeout" <<'MOCK'
#!/usr/bin/env bash
printf 'statusResponse\n\\fs_game\\%s\\g_gametype\\%s\\sv_pure\\1\\mapname\\mp_crash\n' "$MOCK_HEALTH_MODE" "${MOCK_HEALTH_GAMETYPE:-sd}"
MOCK
cat > "$test_root/health-bin/sleep" <<'MOCK'
#!/usr/bin/env bash
exit 1
MOCK
chmod +x "$test_root/health-bin/"*
(
    export PATH="$test_root/health-bin:$PATH"
    remote() { "$@"; }
    select_environment production
    export MOCK_HEALTH_MODE=mods/pml220
    check_health mods/pml220
    export MOCK_HEALTH_MODE=mods/btd_alpha_001 MOCK_HEALTH_GAMETYPE=war
    check_health mods/btd_alpha_001
    export MOCK_HEALTH_GAMETYPE=sd
    if check_health mods/btd_alpha_001 >/dev/null 2>&1; then exit 1; fi
    export MOCK_HEALTH_MODE=mods/other
    if check_health mods/pml220 >/dev/null 2>&1; then exit 1; fi
)
printf 'PASS: actual health payload accepts Promod and rejects wrong UDP game mode\n'

# The mode-switch interface delegates to the exact same approval/deploy path.
mkdir "$test_root/scripts"
cp scripts/*.sh scripts/*.py "$test_root/scripts/"
cat >> "$test_root/scripts/common.sh" <<'MOCK'
deploy() { printf '%s %s %s\n' "$environment" "$container" "$1" >> "$MOCK_LOG"; }
MOCK
: > "$MOCK_LOG"
"$test_root/scripts/game-mode.sh" homolog fixture
"$test_root/scripts/game-mode.sh" production fixture
grep -qx 'homolog cod4-homolog fixture' "$MOCK_LOG"
grep -qx 'production cod4-production fixture' "$MOCK_LOG"
if "$test_root/scripts/game-mode.sh" invalid fixture >/dev/null 2>&1; then exit 1; fi
# Execute the actual remote configuration payload against a local temporary path.
remote() {
    [[ "$1 $2" == 'bash -c' ]] || return 1
    local code=${3//\/opt\/services\/cod4/$test_root}
    bash -c "$code" "${@:4}"
}
select_environment homolog
project=cod4-homolog; service=homolog; work=/opt/services/cod4
# Literal dollar signs exercise Compose interpolation escaping.
# shellcheck disable=SC2016
apply_runtime <<< '{"services":{"homolog":{"environment":{"SECRET":"a$b"}}}}'
[[ $(stat -c %a "$test_root/.operations-homolog.json") == 600 ]]
# shellcheck disable=SC2016
grep -Fq 'a$$b' "$test_root/.operations-homolog.json"
grep -q -- '--no-deps --pull never --force-recreate homolog' "$MOCK_LOG"
[[ $(find "$test_root" -maxdepth 1 -name '.operations.*' | wc -l) == 0 ]]
printf 'PASS: mode-switch delegation/isolation, private atomic configuration, interpolation escaping and cleanup\n'

mkdir -p "$test_root/source/bots" "$test_root/source/tools/bots" "$test_root/source/docs" "$test_root/assets" "$test_root/headers"
git init -q -b master "$test_root/source"
printf '{"bot_warfare":{"repository":"https://github.com/ineedbots/iw3_bot_warfare","commit":"%s"}}\n' "$(printf 'c%.0s' {1..40})" > "$test_root/source/bots/dependencies.json"
for file in License.md Copyright.md copying.md docs/third-party-bots.md; do printf notice > "$test_root/source/$file"; done
# Stand-in for the upstream verified-asset preparation tool, not a deployment implementation.
cat > "$test_root/source/tools/bots/prepare.py" <<'PY'
import argparse,pathlib,json,hashlib
p=argparse.ArgumentParser()
for key in ('promod','bot-warfare','headers','binary','output'): p.add_argument('--'+key,required=True)
p.add_argument('--allow-no-punkbuster', action='store_true', required=True)
p.add_argument('--allow-map-voting', action='store_true', required=True)
a=p.parse_args(); out=pathlib.Path(a.output); out.mkdir(); (out/'cod4x18_dedrun').write_text('fixture'); (out/'mods/pml220').mkdir(parents=True); (out/'integrity/addiwdheaders').mkdir(parents=True); headers={'jcod4x_00.dat':hashlib.sha256(b'header').hexdigest()} | {f'localized_english_iw{i:02}.dat':hashlib.sha256(b'header').hexdigest() for i in range(7)}
for name in headers: (out/'integrity/addiwdheaders'/name).write_bytes(b'header')
(out/'mods/pml220/promod').mkdir()
(out/'mods/pml220/promod/servercheck.gsx').write_text('verified upstream overlay fixture')
for name in ('comp', 'readyup'): (out/f'mods/pml220/promod/{name}.gsx').write_text('verified upstream overlay fixture')
(out/'inputs.json').write_text(json.dumps({'maps':['mp_crash','mp_strike'], 'headers':headers, 'punkbuster_warning_policy_overlay':a.allow_no_punkbuster}))
PY
git -C "$test_root/source" add bots tools docs License.md Copyright.md copying.md
git -C "$test_root/source" -c user.name=Test -c user.email=test@example.invalid commit -qm 'test: fixture'
expected=$(git -C "$test_root/source" rev-parse HEAD)
printf uncommitted > "$test_root/source/dirty"
mkdir -p "$test_root/config-source"
command git init -q -b master "$test_root/config-source"
PYTHONPATH=tests python3 -c 'from pathlib import Path; from test_modes import write_catalog; import sys; write_catalog(Path(sys.argv[1]))' "$test_root/config-source"
command git -C "$test_root/config-source" add modes shared
command git -C "$test_root/config-source" -c user.name=Test -c user.email=test@example.invalid commit -qm 'test: config'
CONFIG_REPOSITORY="$test_root/config-source"
expected_config=$(command git -C "$CONFIG_REPOSITORY" rev-parse HEAD)
ENGINE_REPOSITORY="$test_root/source"
stage="$test_root/resolution"
mkdir "$stage"
mode_id=promod
resolve_master
[[ "$config_revision" == "$expected_config" ]]
[[ -z "$(git -C "$stage/config" status --porcelain)" ]]
[[ "$revision" == "$expected" && ! -e "$stage/engine/dirty" ]]
[[ -z "$(git -C "$stage/engine" status --porcelain)" ]]
[[ $(cat "$test_root/source/dirty") == uncommitted ]]
if bash -c 'source scripts/common.sh; ENGINE_REPOSITORY=$1; stage=$2; mkdir "$stage"; resolve_master' bash "$test_root/missing" "$test_root/failed-fetch" > "$test_root/result" 2>&1; then exit 1; fi
grep -q 'Cannot fetch origin/master' "$test_root/result"
printf 'PASS: real local master fetch, exact SHA, isolated clean checkout, developer changes preserved, fetch failure\n'

if (mode_fs_game=mods/unqualified; build_selected_mode) > "$test_root/result" 2>&1; then exit 1; fi
grep -q 'No verified asset preparation recipe' "$test_root/result"
if (COD4_PROMOD_ASSETS=; build_promod) > "$test_root/result" 2>&1; then exit 1; fi
grep -q 'Explicit authorized' "$test_root/result"
# Exercise an absent executable using an intentionally empty search path.
# shellcheck disable=SC2123
if (PATH=/nonexistent; need python3) > "$test_root/result" 2>&1; then exit 1; fi
grep -q 'Required command: python3' "$test_root/result"
if (COD4_PROMOD_ASSETS="$test_root/assets"; COD4_INTEGRITY_HEADERS="$test_root/headers"; COD4_OAT=; build_promod) > "$test_root/result" 2>&1; then exit 1; fi
grep -q 'COD4_OAT' "$test_root/result"
COD4_PROMOD_ASSETS="$test_root/assets"
COD4_OAT="$test_root/oat"
mkdir "$COD4_OAT"
printf '#!/bin/sh\n' > "$COD4_OAT/Linker"
cp "$COD4_OAT/Linker" "$COD4_OAT/Unlinker"
chmod +x "$COD4_OAT/"*
mkdir -p "$stage/engine/tests" "$stage/engine/tools/promod"
printf 'pass\n' > "$stage/engine/tests/test_integrity_headers.py"
for policy in fps_menu punkbuster_policy; do
    printf 'import unittest\nclass Fixture(unittest.TestCase):\n def test_fixture(self): self.assertTrue(True)\n' > "$stage/engine/tests/test_$policy.py"
done
cat > "$stage/engine/tools/promod/fps333.py" <<'PYTHON'
import argparse,pathlib,json,hashlib
p=argparse.ArgumentParser()
for key in ('promod','oat','output'): p.add_argument('--'+key)
a=p.parse_args(); out=pathlib.Path(a.output); (out/'project/zone_out/fps333').mkdir(parents=True)
(out/'project/raw').mkdir(); (out/'project/raw/menu').write_text('333')
(out/'project/zone_out/fps333/mod.ff').write_bytes(b'patched333')
(out/'manifest.json').write_text(json.dumps({'mod_ff_sha256':hashlib.sha256(b'patched333').hexdigest()}))
PYTHON
COD4_INTEGRITY_HEADERS="$test_root/headers"
if (COD4_PROMOD_ASSETS="$test_root/missing-assets"; build_selected_mode) > "$test_root/result" 2>&1; then exit 1; fi
grep -q 'Verified local Promod assets' "$test_root/result"
artifact_id="sha256:$(printf 'a%.0s' {1..64})"
old_id="sha256:$(printf 'b%.0s' {1..64})"
git() {
    if [[ "$*" == *'/bots fetch '* ]]; then return 0; fi
    if [[ "$*" == *'/bots -c advice.detachedHead=false checkout '* ]]; then printf notice > "$stage/bots/README.md"; return 0; fi
    if [[ "$*" == *'/bots rev-parse HEAD' ]]; then printf '%s\n' "$bot_revision"; return 0; fi
    if [[ "$*" == *'/bots status '* ]]; then return 0; fi
    command git "$@"
}
docker() {
    printf '%s\n' "$*" >> "$test_root/docker.log"
    case "$1 $2" in
        'image inspect')
            [[ ${missing_image:-0} == 0 ]] || return 1
            printf '[{"Id":"%s","Os":"linux","Architecture":"amd64","Config":{"Labels":{"org.opencontainers.image.revision":"%s","org.opencontainers.image.source":"%s","io.cod4.config.revision":"%s","io.cod4.mode":"promod","io.cod4.config.hash":"%s","io.cod4.fs-game":"mods/pml220","io.cod4.startup-map":"mp_crash","io.cod4.maps":"mp_crash,mp_strike","io.cod4.maxclients":"12","io.cod4.assets.lock":"%s","io.cod4.bot-warfare.revision":"%s"}}}]\n' "$artifact_id" "${image_revision_override:-$revision}" "$ENGINE_REPOSITORY" "$config_revision" "${config_hash_override:-$config_hash}" "${asset_ref_override:-$asset_ref}" "$bot_revision" ;;
        'image save') [[ ${fail_save:-0} == 0 ]] || return 1; printf image ;;
        'image tag') return 0 ;;
        'run --rm') [[ ${fail_build:-0} == 0 ]] || return 1 ;;
        'build --pull=false') printf '%s\n' "$artifact_id" > "$stage/image-id" ;;
        *) return 1 ;;
    esac
}
if (fail_build=1; build_promod) >/dev/null 2>&1; then exit 1; fi
rm -rf -- "$stage/bots"
build_promod >/dev/null
# The failed build runs in isolation; build_promod above sets the parent artifact.
# shellcheck disable=SC2031
[[ "$artifact" == "$artifact_id" ]]
[[ $(cat "$stage/runtime/mods/pml220/mod.ff") == patched333 ]]
cmp "$stage/config/modes/promod/server.cfg" "$stage/runtime/mods/pml220/canonical-mode.cfg"
grep -qx 'set promod_allow_no_punkbuster "1"' "$stage/runtime/mods/pml220/canonical-shared.cfg"
[[ -s "$stage/runtime/mods/pml220/promod/servercheck.gsx" ]]
grep -q 'test -s /opt/cod4-artifact/mods/pml220/promod/servercheck.gsx' "$test_root/docker.log"
cmp "$stage/config/modes/promod/mode.cfg" "$stage/runtime/configuration/mode.cfg"
[[ $(find "$stage/runtime/mods" -mindepth 1 -maxdepth 1 -type d | wc -l) == 1 ]]
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["punkbuster_warning_policy_overlay"] is True and d["mode_id"]=="promod" and len(d["config_files"])==3 and len(d["headers"])==8' "$stage/runtime/inputs.json"
grep -q '^COPY runtime/' "$stage/Dockerfile"
grep -q '^engine$' "$stage/.dockerignore"
if grep -q 'python3' "$test_root/docker.log"; then exit 1; fi
# Local-only preparation cannot call the remote deployment path.
(
    ROOT="$test_root/local-only"; mkdir -p "$ROOT"
    select_environment homolog
    # Fixture assignments intentionally stay within this preparation subshell.
    # shellcheck disable=SC2030
    resolve_master() { revision=$expected; config_revision=$expected_config; asset_ref=$(printf 'd%.0s' {1..64}); bot_revision=$(printf 'c%.0s' {1..40}); }
    build_selected_mode() { artifact=$artifact_id; }
    # shellcheck disable=SC2329
    remote() { exit 99; }
    deploy_image() { exit 98; }
    COD4_PREPARE_ONLY=1 deploy promod
    [[ -s "$ROOT/.state/prepared" && ! -e "$ROOT/.state/approved" ]]
)
printf 'PASS: local build orchestration, build failure gate, recorded image identity, runtime-only packaging\n'

ROOT=$test_root
mkdir -p "$ROOT/.state"
select_environment homolog
apply_count=0
remote() {
    printf '%s\n' "$*" >> "$test_root/remote.log"
    case "$1 $2" in
        'docker version') printf 'linux/amd64\n' ;;
        'docker inspect')
            if [[ "$*" == *'{{.Image}} {{.State.Running}}'* ]]; then printf '%s true\n' "${homolog_id:-$artifact_id}"
            elif [[ "$*" == 'docker inspect cod4-homolog' ]]; then
                printf '[{"Name":"/cod4-homolog","Image":"%s","State":{"Running":true},"Path":"%s","Mounts":[],"Config":{"WorkingDir":"/opt/cod4-artifact","Labels":{"org.opencontainers.image.revision":"%s","io.cod4.config.revision":"%s","io.cod4.mode":"promod","io.cod4.config.hash":"%s","io.cod4.fs-game":"mods/pml220","io.cod4.startup-map":"mp_crash","io.cod4.maps":"mp_crash,mp_strike","io.cod4.maxclients":"12"},"Cmd":["+set","fs_game","mods/pml220","+set","fs_basepath","/opt/cod4-artifact","+set","fs_localizedHeadersPath","/opt/cod4-artifact/integrity","+set","sv_autoupdate","0","+set","sv_maxclients","12","+exec","canonical-shared.cfg","+exec","canonical-mode.cfg","+map_rotate"]}}]\n' "$artifact_id" "${homolog_path:-/opt/cod4-artifact/cod4x18_dedrun}" "$revision" "$config_revision" "${homolog_hash_override:-$config_hash}"
            elif [[ "$apply_count" -ge 2 ]]; then printf '%s\n' "$old_id"
            else printf '%s\n' "$artifact_id"; fi ;;
        'docker image') cat >/dev/null; [[ ${fail_ssh:-0} == 0 ]] ;;
        *) return 1 ;;
    esac
}
snapshot_runtime() {
    service=$environment; project="cod4-$environment"; work=/opt/services/cod4
    config='{"services":{"'"$service"'":{"entrypoint":["/home/user/cod4/cod4x18_dedrun"],"command":["+set","fs_game","mods/pml220","+set","fs_homepath","'"${fixture_homepath:-/home/user/.callofduty4}"'"],"volumes":[{"source":"/persist","target":"/home/user/.callofduty4"},{"source":"/main","target":"/home/user/cod4/main"},{"source":"/zone","target":"/home/user/cod4/zone"}]}}}'
    inspection='[{"Image":"'"$old_id"'"}]'
}
apply_runtime() { printf 'apply %s\n' "$container" >> "$test_root/remote.log"; tee "$test_root/last-applied" >> "$test_root/applied"; apply_count=$((apply_count+1)); [[ ${fail_apply:-0} == 0 || "$apply_count" -gt 1 ]]; }
check_health() { [[ ${2:-} != cod4-homolog ]] || return 0; [[ ${fail_rollback:-0} == 0 ]] || return 1; [[ ${fail_health:-0} == 0 || "$apply_count" -ge 2 ]]; }
confirm() { printf 'confirm\n' >> "$test_root/remote.log"; [[ ${decline:-0} == 0 ]]; }
# Unsafe adaptation must fail before image transfer, runtime writes or rollback changes.
printf 'preserved rollback evidence\n' > "$ROOT/.state/rollback-homolog.json"
if (fixture_homepath=/tmp; deploy_image "$artifact_id") > "$test_root/result" 2>&1; then exit 1; fi
grep -q "Unsafe fs_homepath: '/tmp'" "$test_root/result"
[[ $(cat "$ROOT/.state/rollback-homolog.json") == 'preserved rollback evidence' ]]
[[ "$apply_count" == 0 && ! -e "$ROOT/.state/approved" ]]
if grep -Eq 'docker image load|^apply |^confirm$' "$test_root/remote.log"; then exit 1; fi
: > "$test_root/remote.log"
deploy_image "$artifact_id" >/dev/null
read -r approved approved_revision approved_assets approved_bots approved_config approved_mode approved_hash < "$ROOT/.state/approved"
[[ "$approved" == "$artifact_id" && "$approved_revision" == "$expected" && "$approved_assets" == "$asset_ref" && "$approved_bots" == "$bot_revision" && "$approved_config" == "$expected_config" && "$approved_mode" == promod && "$approved_hash" == "$config_hash" ]]
grep -q 'canonical-shared.cfg' "$test_root/applied"
grep -q '/opt/cod4-artifact/cod4x18_dedrun' "$test_root/applied"
grep -q '"source": "/persist"' "$test_root/applied"
if grep -Eq 'production|bard' "$test_root/remote.log"; then exit 1; else [[ $? == 1 ]]; fi
[[ -f "$ROOT/.state/rollback-homolog.json" ]]
select_environment production
: > "$test_root/remote.log"
apply_count=0
deploy_image "$artifact_id" > "$test_root/plan"
[[ "$apply_count" == 1 ]]
grep -q 'container=cod4-production.*UDP=28960 mode=promod' "$test_root/plan"
grep -q "Approved image: $artifact_id" "$test_root/plan"
confirmation_line=$(grep -n '^confirm$' "$test_root/remote.log" | cut -d: -f1)
transfer_line=$(grep -n '^docker image load$' "$test_root/remote.log" | cut -d: -f1)
apply_line=$(grep -n '^apply cod4-production$' "$test_root/remote.log" | cut -d: -f1)
[[ "$confirmation_line" -lt "$transfer_line" && "$transfer_line" -lt "$apply_line" ]]
if grep -Eq '(start|stop|up).*cod4-homolog|bard' "$test_root/remote.log"; then exit 1; else [[ $? == 1 ]]; fi
apply_count=0; fail_health=1
if deploy_image "$artifact_id" > "$test_root/result" 2>&1; then exit 1; fi
[[ "$apply_count" == 2 ]]; grep -q 'Rollback healthy' "$test_root/result"
# Rollback records and reapplied commands retain the explicit persistent home.
cmp "$ROOT/.state/rollback-production.json" "$test_root/last-applied"
python3 -c 'import json,sys; c=json.load(open(sys.argv[1])); expected=json.load(sys.stdin); expected["services"]["production"]["image"]=sys.argv[2]; assert c==expected; a=c["services"]["production"]["command"]; assert a[a.index("fs_homepath")+1]=="/home/user/.callofduty4"' "$ROOT/.state/rollback-production.json" "$old_id" <<< "$config"
fail_health=0; fail_apply=1; apply_count=0
if deploy_image "$artifact_id" > "$test_root/result" 2>&1; then exit 1; fi
[[ "$apply_count" == 2 ]]; grep -q 'Rollback healthy' "$test_root/result"
fail_apply=0; apply_count=0
if (fail_rollback=1; deploy_image "$artifact_id") > "$test_root/result" 2>&1; then exit 1; fi
grep -q 'ROLLBACK FAILED' "$test_root/result"
if (homolog_path=/home/user/cod4/cod4x18_dedrun; deploy_image "$artifact_id") >/dev/null 2>&1; then exit 1; fi
for failure in fail_ssh fail_save decline missing_image; do
    if (export "$failure=1"; deploy_image "$artifact_id") >/dev/null 2>&1; then exit 1; fi
done
if (deploy_image "$old_id") >/dev/null 2>&1; then exit 1; fi
if (homolog_id=$old_id; deploy_image "$artifact_id") >/dev/null 2>&1; then exit 1; fi
if (image_revision_override=invalid; deploy_image "$artifact_id") >/dev/null 2>&1; then exit 1; fi
if (asset_ref_override=invalid; deploy_image "$artifact_id") >/dev/null 2>&1; then exit 1; fi
if (config_hash_override=invalid; deploy_image "$artifact_id") >/dev/null 2>&1; then exit 1; fi
if (homolog_hash_override=invalid; deploy_image "$artifact_id") >/dev/null 2>&1; then exit 1; fi
printf 'PASS: homolog provenance/approval, promotion confirmation, identities, transfer failures, mount preservation, rollback success/failure\n'

build_selected_mode() { printf forbidden > "$test_root/rebuilt"; return 1; }
deploy_image() { printf '%s\n' "$1" > "$test_root/promoted"; }
deploy promod >/dev/null
[[ $(cat "$test_root/promoted") == "$artifact_id" && ! -e "$test_root/rebuilt" ]]
printf newer > "$test_root/source/newer"
command git -C "$test_root/source" add newer
command git -C "$test_root/source" -c user.name=Test -c user.email=test@example.invalid commit -qm 'test: newer master'
resolve_master() { printf forbidden > "$test_root/fetched"; return 1; }
mv "$test_root/config-source/modes/promod" "$test_root/config-source/removed-mode"
deploy promod > "$test_root/result" 2>&1
[[ $(cat "$test_root/promoted") == "$artifact_id" && ! -e "$test_root/fetched" ]]
if deploy fixture > "$test_root/result" 2>&1; then exit 1; fi
grep -q 'Requested mode differs' "$test_root/result"
printf 'unapproved image\n' > "$ROOT/.state/approved"
if deploy promod > "$test_root/result" 2>&1; then exit 1; fi
grep -q 'Malformed approval record' "$test_root/result"
rm "$ROOT/.state/approved"
if deploy promod > "$test_root/result" 2>&1; then exit 1; fi
grep -q 'No approved homolog artifact' "$test_root/result"
printf 'PASS: exact production promotion without rebuild, promotion despite newer master/removed catalog mode and untested-artifact rejection\n'

# The same production path accepts the explicit absence of Bot Warfare for BTD.
mode_id=zombies; bot_revision=none
write_artifact_record "$artifact_id" > "$ROOT/.state/approved"
deploy zombies > "$test_root/result" 2>&1
[[ $(cat "$test_root/promoted") == "$artifact_id" && ! -e "$test_root/fetched" && ! -e "$test_root/rebuilt" ]]
if deploy promod > "$test_root/result" 2>&1; then exit 1; fi
grep -q 'Requested mode differs' "$test_root/result"
printf 'PASS: exact Zombies promotion, explicit no-Bot-Warfare provenance and cross-mode approval rejection\n'
