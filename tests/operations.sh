#!/usr/bin/env bash
# Local fixtures and mocks only: never contact EC2 or the Docker daemon.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
source scripts/common.sh
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
for script in homolog deploy-homolog deploy-production game-mode; do
    if "scripts/$script.sh" >/dev/null 2>&1; then exit 1; fi
done
for script in deploy-homolog deploy-production; do
    if "scripts/$script.sh" zombies >/dev/null 2>&1; then exit 1; fi
done
if MOCK_SSH_EXIT=255 scripts/homolog.sh status >/dev/null 2>&1; then exit 1; fi
if (confirm 'Production test') </dev/null >/dev/null 2>&1; then exit 1; fi
printf 'PASS: command boundaries, lifecycle repetition/isolation, SSH options/failure, terminal requirement\n'

mkdir "$test_root/scripts"
cp scripts/*.sh "$test_root/scripts/"
cat >> "$test_root/scripts/common.sh" <<'MOCK'
snapshot_runtime() {
    service=$environment
    config='{"services":{"'"$service"'":{"command":["+set","fs_game","'"${MOCK_MODE:-mods/pml220}"'"]}}}'
}
remote() { printf '%s\n' "$*" >> "$MOCK_LOG"; }
apply_runtime() {
    cat >> "$MOCK_LOG"
    if [[ ${MOCK_FAIL_APPLY:-0} == 1 && ! -e "$MOCK_LOG.failed" ]]; then
        touch "$MOCK_LOG.failed"
        return 1
    fi
}
check_health() { [[ ${MOCK_FAIL_HEALTH:-0} == 0 ]]; }
MOCK
: > "$MOCK_LOG"
"$test_root/scripts/game-mode.sh" homolog promod >/dev/null
[[ ! -s "$MOCK_LOG" ]]
MOCK_MODE=mods/other "$test_root/scripts/game-mode.sh" production promod >/dev/null
grep -q 'cod4-production test -d mods/pml220' "$MOCK_LOG"
if grep -Eq 'homolog|bard' "$MOCK_LOG"; then exit 1; else [[ $? == 1 ]]; fi
for args in 'invalid promod' 'homolog zombies'; do
    read -r -a values <<< "$args"
    if "$test_root/scripts/game-mode.sh" "${values[@]}" >/dev/null 2>&1; then exit 1; fi
done
# A failed mode change must restore the original configuration and still fail.
: > "$MOCK_LOG"
if MOCK_MODE=mods/other MOCK_FAIL_APPLY=1 "$test_root/scripts/game-mode.sh" homolog promod > "$test_root/result" 2>&1; then exit 1; fi
[[ $(grep -c '"services"' "$MOCK_LOG") == 2 ]]
grep -q 'restoring previous configuration' "$test_root/result"
if MOCK_MODE=mods/other MOCK_FAIL_HEALTH=1 "$test_root/scripts/game-mode.sh" homolog promod > "$test_root/result" 2>&1; then exit 1; fi
grep -q 'Mode rollback failed' "$test_root/result"
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
printf 'PASS: mode idempotency/isolation, private atomic configuration, interpolation escaping and cleanup\n'

mkdir -p "$test_root/source/bots" "$test_root/source/tools/bots" "$test_root/source/docs" "$test_root/assets" "$test_root/headers"
git init -q -b master "$test_root/source"
printf '{"bot_warfare":{"repository":"https://github.com/ineedbots/iw3_bot_warfare","commit":"%s"}}\n' "$(printf 'c%.0s' {1..40})" > "$test_root/source/bots/dependencies.json"
for file in License.md Copyright.md copying.md docs/third-party-bots.md; do printf notice > "$test_root/source/$file"; done
# Stand-in for the upstream verified-asset preparation tool, not a deployment implementation.
cat > "$test_root/source/tools/bots/prepare.py" <<'PY'
import argparse,pathlib
p=argparse.ArgumentParser()
for key in ('promod','bot-warfare','headers','binary','output'): p.add_argument('--'+key,required=True)
a=p.parse_args(); out=pathlib.Path(a.output); out.mkdir(); (out/'cod4x18_dedrun').write_text('fixture')
PY
git -C "$test_root/source" add bots tools docs License.md Copyright.md copying.md
git -C "$test_root/source" -c user.name=Test -c user.email=test@example.invalid commit -qm 'test: fixture'
expected=$(git -C "$test_root/source" rev-parse HEAD)
printf uncommitted > "$test_root/source/dirty"
ENGINE_REPOSITORY="$test_root/source"
stage="$test_root/resolution"
mkdir "$stage"
resolve_master
[[ "$revision" == "$expected" && ! -e "$stage/engine/dirty" ]]
[[ -z "$(git -C "$stage/engine" status --porcelain)" ]]
[[ $(cat "$test_root/source/dirty") == uncommitted ]]
if bash -c 'source scripts/common.sh; ENGINE_REPOSITORY=$1; stage=$2; mkdir "$stage"; resolve_master' bash "$test_root/missing" "$test_root/failed-fetch" > "$test_root/result" 2>&1; then exit 1; fi
grep -q 'Cannot fetch origin/master' "$test_root/result"
printf 'PASS: real local master fetch, exact SHA, isolated clean checkout, developer changes preserved, fetch failure\n'

COD4_PROMOD_ASSETS="$test_root/assets"
COD4_INTEGRITY_HEADERS="$test_root/headers"
artifact_id="sha256:$(printf 'a%.0s' {1..64})"
old_id="sha256:$(printf 'b%.0s' {1..64})"
git() {
    if [[ "$*" == *'/bots fetch '* ]]; then return 0; fi
    if [[ "$*" == *'/bots -c advice.detachedHead=false checkout '* ]]; then printf notice > "$stage/bots/README.md"; return 0; fi
    command git "$@"
}
docker() {
    printf '%s\n' "$*" >> "$test_root/docker.log"
    case "$1 $2" in
        'image inspect')
            [[ ${missing_image:-0} == 0 ]] || return 1
            printf '[{"Id":"%s","Os":"linux","Architecture":"amd64","Config":{"Labels":{"org.opencontainers.image.revision":"%s","org.opencontainers.image.source":"%s","io.cod4.assets.lock":"%s","io.cod4.bot-warfare.revision":"%s"}}}]\n' "$artifact_id" "${image_revision_override:-$revision}" "$ENGINE_REPOSITORY" "${asset_ref_override:-$asset_ref}" "$bot_revision" ;;
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
grep -q '^COPY runtime/' "$stage/Dockerfile"
grep -q '^engine$' "$stage/.dockerignore"
printf 'PASS: local build orchestration, build failure gate, recorded image identity, runtime-only packaging\n'

ROOT=$test_root
mkdir "$ROOT/.state"
select_environment homolog
apply_count=0
remote() {
    printf '%s\n' "$*" >> "$test_root/remote.log"
    case "$1 $2" in
        'docker version') printf 'linux/amd64\n' ;;
        'docker inspect')
            if [[ "$*" == *'{{.Image}} {{.State.Running}}'* ]]; then printf '%s true\n' "${homolog_id:-$artifact_id}"
            elif [[ "$apply_count" -ge 2 ]]; then printf '%s\n' "$old_id"
            else printf '%s\n' "$artifact_id"; fi ;;
        'docker image') cat >/dev/null; [[ ${fail_ssh:-0} == 0 ]] ;;
        *) return 1 ;;
    esac
}
snapshot_runtime() {
    service=$environment; project="cod4-$environment"; work=/opt/services/cod4
    config='{"services":{"'"$service"'":{"entrypoint":["/home/user/cod4/cod4x18_dedrun"],"command":["+set","fs_game","mods/pml220"],"volumes":[{"source":"/persist","target":"/home/user/.callofduty4"},{"source":"/main","target":"/home/user/cod4/main"},{"source":"/zone","target":"/home/user/cod4/zone"}]}}}'
    inspection='[{"Image":"'"$old_id"'"}]'
}
apply_runtime() { cat >> "$test_root/applied"; apply_count=$((apply_count+1)); [[ ${fail_apply:-0} == 0 || "$apply_count" -gt 1 ]]; }
check_health() { [[ ${fail_rollback:-0} == 0 ]] || return 1; [[ ${fail_health:-0} == 0 || "$apply_count" -ge 2 ]]; }
confirm() { [[ ${decline:-0} == 0 ]]; }
deploy_image "$artifact_id" >/dev/null
read -r approved approved_revision approved_assets approved_bots < "$ROOT/.state/approved"
[[ "$approved" == "$artifact_id" && "$approved_revision" == "$expected" && "$approved_assets" == "$asset_ref" && "$approved_bots" == "$bot_revision" ]]
grep -q '/opt/cod4-artifact/cod4x18_dedrun' "$test_root/applied"
grep -q '"source": "/persist"' "$test_root/applied"
if grep -Eq 'production|bard' "$test_root/remote.log"; then exit 1; else [[ $? == 1 ]]; fi
[[ -f "$ROOT/.state/rollback-homolog.json" ]]
select_environment production
: > "$test_root/remote.log"
apply_count=0
deploy_image "$artifact_id" >/dev/null
[[ "$apply_count" == 1 ]]
if grep -Eq '(start|stop|up).*cod4-homolog|bard' "$test_root/remote.log"; then exit 1; else [[ $? == 1 ]]; fi
apply_count=0; fail_health=1
if deploy_image "$artifact_id" > "$test_root/result" 2>&1; then exit 1; fi
[[ "$apply_count" == 2 ]]; grep -q 'Rollback healthy' "$test_root/result"
fail_health=0; fail_apply=1; apply_count=0
if deploy_image "$artifact_id" > "$test_root/result" 2>&1; then exit 1; fi
[[ "$apply_count" == 2 ]]; grep -q 'Rollback healthy' "$test_root/result"
fail_apply=0; apply_count=0
if (fail_rollback=1; deploy_image "$artifact_id") > "$test_root/result" 2>&1; then exit 1; fi
grep -q 'ROLLBACK FAILED' "$test_root/result"
for failure in fail_ssh fail_save decline missing_image; do
    if (export "$failure=1"; deploy_image "$artifact_id") >/dev/null 2>&1; then exit 1; fi
done
if (deploy_image "$old_id") >/dev/null 2>&1; then exit 1; fi
if (homolog_id=$old_id; deploy_image "$artifact_id") >/dev/null 2>&1; then exit 1; fi
if (image_revision_override=invalid; deploy_image "$artifact_id") >/dev/null 2>&1; then exit 1; fi
if (asset_ref_override=invalid; deploy_image "$artifact_id") >/dev/null 2>&1; then exit 1; fi
printf 'PASS: homolog provenance/approval, promotion confirmation, identities, transfer failures, mount preservation, rollback success/failure\n'

build_promod() { printf forbidden > "$test_root/rebuilt"; return 1; }
deploy_image() { printf '%s\n' "$1" > "$test_root/promoted"; }
deploy promod >/dev/null
[[ $(cat "$test_root/promoted") == "$artifact_id" && ! -e "$test_root/rebuilt" ]]
printf newer > "$test_root/source/newer"
command git -C "$test_root/source" add newer
command git -C "$test_root/source" -c user.name=Test -c user.email=test@example.invalid commit -qm 'test: newer master'
if deploy promod > "$test_root/result" 2>&1; then exit 1; fi
grep -q 'Latest master is' "$test_root/result"
rm "$ROOT/.state/approved"
if deploy promod > "$test_root/result" 2>&1; then exit 1; fi
grep -q 'No approved homolog artifact' "$test_root/result"
printf 'PASS: exact production promotion without rebuild, newer-master rejection and untested-artifact rejection\n'
