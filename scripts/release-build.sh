#!/usr/bin/env bash
# Build only on the local isolated release runner; never connects to EC2.
set -euo pipefail
# shellcheck source=scripts/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
[[ $# == 2 && "$1" =~ ^[a-z][a-z0-9-]*$ && "$2" =~ ^v[0-9]+\.[0-9]+\.[0-9]+-rc\.[1-9][0-9]*$ ]] || fail 'Usage: release-build.sh mode vMAJOR.MINOR.PATCH-rc.N'
mode_id=$1; release_tag=$2
for tool in git python3 docker gcc trivy flock gh; do need "$tool"; done
[[ -n ${COD4_GAME_DATA:-} ]] || fail 'Explicit authorized COD4_GAME_DATA required'
umask 077
mkdir -p "$ROOT/.state/releases"
exec 9> "$ROOT/.state/release.lock"
flock -n 9 || fail 'Another local release is running'
stage=$(mktemp -d "$ROOT/.state/releases/candidate.XXXXXX")
# Keep interrupted build evidence. Never delete existing qualification artifacts.
export COD4_RELEASE_STAGE="$stage" COD4_RELEASE_TAG="$release_tag" COD4_RELEASE_MODE="$mode_id"
python3 "$OPERATIONS_SCRIPTS/release.py" preflight "$release_tag"
workspace_revision=$(git -C "$ROOT" rev-parse HEAD)
export COD4_RELEASE_WORKSPACE="$workspace_revision"
python3 - "$ROOT" "$workspace_revision" <<'PY'
import sys,os
from pathlib import Path
sys.path.insert(0, sys.argv[1] + '/scripts')
import release
release.protected_history(release.REPO, sys.argv[2], sys.argv[1], tip=True)
release.require(release.expected_version(Path(sys.argv[1])) == os.environ["COD4_RELEASE_TAG"], "Unexpected candidate version")
PY
lock="$ROOT/release/dependencies.json"
mapfile -t pins < <(python3 - "$lock" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
for key in ('engine','config','bot_warfare','engine_dependencies_sha256','builder','runtime_base'): print(p[key])
PY
)
revision=${pins[0]}; config_revision=${pins[1]}; bot_revision=${pins[2]}; asset_ref=${pins[3]}
[[ ${pins[4]} == "$BUILDER" && ${pins[5]} == "$RUNTIME_BASE" ]] || fail 'Build image pins differ from packaging policy'
checkout_pin() {
    [[ "$3" =~ ^[a-f0-9]{40}$ ]] || fail 'Full dependency SHA required'
    git init -q "$2"
    git -C "$2" remote add origin "$1"
    git -C "$2" fetch --no-tags origin "$3"
    git -C "$2" -c advice.detachedHead=false checkout -q --detach "$3"
}
checkout_pin "$ENGINE_REPOSITORY" "$stage/engine" "$revision"
checkout_pin "$CONFIG_REPOSITORY" "$stage/config" "$config_revision"
python3 - "$ROOT" "$stage" "$revision" "$config_revision" "$bot_revision" "$asset_ref" <<'PY'
import json,sys
from pathlib import Path
sys.path.insert(0, sys.argv[1] + '/scripts')
import release
stage=Path(sys.argv[2])
for name, repo, sha in [('engine','ghptc/cod4x-server',sys.argv[3]),('config','ghptc/cod4-config-server',sys.argv[4])]:
    release.protected_history(repo,sha,stage/name)
lock=stage/'engine/bots/dependencies.json'
release.require(release.sha256(lock)==sys.argv[6], 'Engine lock hash mismatch')
release.require(json.loads(lock.read_text())['bot_warfare']['commit']==sys.argv[5], 'Bot pin mismatch')
files=release.run('git','-C',str(stage/'config'),'ls-files').splitlines()
release.require(all(p in ('.gitignore','README.md') or p.startswith(('modes/','shared/')) and p.endswith('.cfg') for p in files), 'Configuration repository contains unrelated tracked files')
PY
# Verify authorized asset hashes BEFORE invoking the compiler.
python3 - "$ROOT" "$stage" <<'PYASSETS'
import importlib.util,json,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]+'/scripts')
import release
stage=Path(sys.argv[2]); lock=json.loads((stage/'engine/bots/dependencies.json').read_text())
for env,entries in [('COD4_PROMOD_ASSETS',lock['promod']['files']),('COD4_INTEGRITY_HEADERS',lock['integrity_headers'])]:
    release.require(os.environ.get(env), 'Explicit authorized asset directory required: '+env)
    for name,expected in entries.items():
        release.require(release.sha256(Path(os.environ[env])/name)==expected, 'Authorized asset hash mismatch: '+name)
spec=importlib.util.spec_from_file_location('pinned_fps333',stage/'engine/tools/promod/fps333.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
release.require(os.environ.get('COD4_OAT'), 'Explicit verified OAT tools required')
for name,expected in module.OAT.items():
    release.require(release.sha256(Path(os.environ['COD4_OAT'])/name)==expected, 'OAT hash mismatch: '+name)
PYASSETS
export SOURCE_DATE_EPOCH
SOURCE_DATE_EPOCH=$(git -C "$stage/engine" show -s --format=%ct HEAD)
select_mode
artifact=
build_selected_mode
# Rebuild without layer cache and reject nondeterministic image metadata/content.
docker build --no-cache --pull=false --network none --build-arg "SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH" \
    --iidfile "$stage/rebuilt-image-id" "$stage"
[[ $(cat "$stage/rebuilt-image-id") == "$artifact" ]] || fail 'Runtime image rebuild is not byte reproducible'
# Independently compile the exact commit again in the same pinned /src toolchain.
git clone --no-hardlinks --no-local "$stage/engine" "$stage/engine-rebuild"
docker run --rm --pull never --network none --user "$(id -u):$(id -g)" \
    --env "SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH" \
    --mount "type=bind,src=$stage/engine-rebuild,dst=/src" --workdir /src "$BUILDER" make -j2
cmp -- "$stage/runtime/cod4x18_dedrun" "$stage/engine-rebuild/bin/cod4x18_dedrun" || fail 'Engine rebuild is not byte reproducible'
# Engine-owned regression tests, executed from the exact pinned source.
python3 -m unittest discover -s "$stage/engine/tests" -p 'test_*.py'
python3 -m unittest discover -s "$ROOT/tests" -p 'test_*.py'
# Preserve a minimal mode-owned startup contract in the packaged release only.
# Already produced by build_promod when COD4_RELEASE_WORKSPACE is present.
for scenario in controls gameplay policy rotation burst legacy no-waypoints empty-rotation; do
    seconds=90
    case "$scenario" in controls) seconds=117 ;; rotation) seconds=135 ;; empty-rotation) seconds=240 ;; esac
    python3 "$stage/engine/tools/bots/run_local.py" --runtime "$stage/runtime" \
        --game "$COD4_GAME_DATA" --image "$BUILDER" --scenario "$scenario" --seconds "$seconds"
done
# shellcheck disable=SC2154 # build_selected_mode sets the immutable image ID.
python3 "$OPERATIONS_SCRIPTS/release-runtime.py" "$artifact" "$COD4_GAME_DATA" "$stage" "$mode_id"
trivy image --exit-code 1 --severity HIGH,CRITICAL --format json --output "$stage/security.json" "$artifact"
# No remote write has occurred above. Recheck policy immediately before upload.
python3 "$OPERATIONS_SCRIPTS/release.py" preflight "$release_tag"
docker image inspect "$artifact" > "$stage/image.json"
python3 - "$ROOT" "$stage" "$artifact" <<'PY'
import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,sys.argv[1]+'/scripts')
import release
stage=Path(sys.argv[2]); lock=json.loads((Path(sys.argv[1])/'release/dependencies.json').read_text())
image=json.loads((stage/'image.json').read_text())[0]
release.require(image['Id']==sys.argv[3], 'Registry upload changed image identity')
# Provisional OCI digest is internal only. All local checks precede the registry write.
reference=release.IMAGE+'@sha256:'+('0'*64)
inputs=json.loads((stage/'runtime/inputs.json').read_text())
assets={}
engine_lock=json.loads((stage/'engine/bots/dependencies.json').read_text())
for group in ('promod','integrity_headers'):
    values=engine_lock[group].get('files',engine_lock[group])
    assets.update({group+'/'+k:v for k,v in values.items()})
assets['binary']=release.sha256(stage/'runtime/cod4x18_dedrun')
assets['fps333']=release.sha256(stage/'runtime/mods/pml220/mod.ff')
game=Path(os.environ['COD4_GAME_DATA']).resolve()
runtime_data={}
for directory in ('main','zone'):
    release.require((game/directory).is_dir(), 'Required game-data directory missing')
    for path in sorted((game/directory).rglob('*')):
        release.require(not path.is_symlink(), 'Game data must not contain symlinks')
        if path.is_file(): runtime_data[str(path.relative_to(game))]=release.sha256(path)
files={str(p.relative_to(stage/'runtime')):release.sha256(p) for p in sorted((stage/'runtime').rglob('*'))
       if p.is_file() and not p.is_symlink() and 'runs' not in p.parts and 'evidence' not in p.parts}
m={'schema':1,'repository':release.REPO,'tag':os.environ['COD4_RELEASE_TAG'],
   'mode':os.environ['COD4_RELEASE_MODE'],'workspace':os.environ['COD4_RELEASE_WORKSPACE'],
   'created_at':datetime.now(timezone.utc).isoformat(),'dependencies':lock,
   'source_date_epoch':int(os.environ['SOURCE_DATE_EPOCH']),
   'image':{'id':image['Id'],'reference':reference,'platform':image['Os']+'/'+image['Architecture']},
   'config_hash':inputs['config_hash'],'assets':assets,'files':files,'runtime_data':runtime_data,
   'startup':{'sv_pure':'1','sv_autoupdate':'0','bot_enable':'1'},
   'gates':{k:True for k in release.GATES},
   'evidence':{'security_sha256':release.sha256(stage/'security.json'),
               'runtime_sha256':release.sha256(stage/'runtime-check.json'),
               'trivy_binary_sha256':release.sha256(release.run('which','trivy'))}}
release.validate_manifest(m,m['tag'],m['mode'],'homolog')
(stage/'candidate-manifest.json').write_text(release.canonical(m))
print('Local gates and provenance validated')
PY
# Every local gate and manifest field has passed; registry upload begins publication.
python3 "$OPERATIONS_SCRIPTS/release.py" preflight "$release_tag"
image_tag="ghcr.io/ghptc/cod4-runtime:build-$workspace_revision-${stage##*.}"
docker tag "$artifact" "$image_tag"
docker push "$image_tag"
docker image inspect "$image_tag" > "$stage/uploaded-image.json"
python3 - "$ROOT" "$stage" <<'PY'
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]+'/scripts')
import release
stage=Path(sys.argv[2]); m=json.loads((stage/'candidate-manifest.json').read_text())
image=json.loads((stage/'uploaded-image.json').read_text())[0]
release.require(image['Id']==m['image']['id'], 'Registry upload changed image identity')
refs=[r for r in image.get('RepoDigests',[]) if r.startswith(release.IMAGE+'@')]
release.require(len(refs)==1, 'Ambiguous registry digest')
release.run('docker','pull',refs[0])
remote=json.loads(release.run('docker','image','inspect',refs[0]))[0]
release.require(remote['Id']==m['image']['id'], 'Registry round-trip image mismatch')
m['image']['reference']=refs[0]
release.validate_manifest(m,m['tag'],m['mode'],'homolog')
(stage/'release-manifest.json').write_text(release.canonical(m))
print('Validated manifest: '+str(stage/'release-manifest.json'))
PY
if [[ -n ${GITHUB_OUTPUT:-} ]]; then printf 'manifest=%s/release-manifest.json\n' "$stage" >> "$GITHUB_OUTPUT"; fi
