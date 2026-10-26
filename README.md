# CoD4 remote operations

See [master deployment and Zombies readiness](docs/zombies-readiness.md) for
required GitHub checks, local evidence and real-client qualification blockers.
The current [mission matrix](docs/zombies-mission.md),
[client investigation](docs/zombies-client-investigation.md) and independent
[mode-switch review](docs/zombies-mode-review.md) track outstanding delivery work.

```bash
./scripts/deploy-homolog.sh promod
./scripts/deploy-production.sh promod
./scripts/production.sh on
./scripts/production.sh off
./scripts/production.sh status
./scripts/homolog.sh on
./scripts/homolog.sh off
./scripts/homolog.sh status
./scripts/game-mode.sh homolog promod
./scripts/game-mode.sh production promod
```

Promod and the private Before the Dawn Zombies candidate use the same deployment path. Zombies gameplay still requires a real client qualification. Local prerequisites: Bash, Git, Docker, Python 3.11+
and GNU coreutils/flock. SSH uses `~/.ssh/config`, alias `aws-prod`, batch mode
and strict host-key verification. Trust the host key before running commands.
System SSH includes are bypassed without changing them.

Homolog fetches `origin/master` from both canonical repositories,
[engine](https://github.com/ghptc/cod4x-server) and
[configuration](https://github.com/ghptc/cod4-config-server), into clean detached
checkouts under ignored `.state/`. Engine and configuration SHAs, pinned Bot Warfare
revision and dependency lock are recorded with the immutable image identity.
Python 3.11+ and GCC run integrity validation on the local host; the pinned builder
needs no Python. Compilation and C policy checks remain in the builder.

Provide explicit authorized inputs; there are no historical workspace defaults:

```bash
export COD4_PROMOD_ASSETS=/private/authorized/pml220
export COD4_INTEGRITY_HEADERS=/private/authorized/addiwdheaders
export COD4_OAT=/private/oat-v0.34.0
COD4_PREPARE_ONLY=1 ./scripts/deploy-homolog.sh promod
```

This command builds and validates locally, records `.state/prepared`, and never
contacts EC2. It does not approve production. Without `COD4_PREPARE_ONLY=1`, the
existing homolog deployment and approval mechanism runs after local preparation.
The pinned builder/runtime image IDs in `scripts/common.sh` must exist locally.
Missing inputs fail closed before compilation. Assets and headers are verified
against the engine dependency lock; Bot Warfare is fetched at its locked SHA.
The upstream FPS tool verifies official OpenAssetTools v0.34.0 hashes, rebuilds
and reparses the 40–333 menu, and records the derived fastfile hash. Its manifest
and editable menu sources accompany the private runtime. No proprietary assets
or generated files belong in Git or public registries. Graphical client FPS and
movement qualification remains required before approval.

The configuration checkout is a clean, detached exact SHA from canonical master.
`scripts/modes.py` validates every `modes/<id>/` directory, its two required CFGs,
and `shared/server.cfg`. IDs are literal, case-sensitive directory names; there
are no aliases or fallback modes. Missing files, symlinks, unsafe CFG syntax,
credentials, duplicate keys, undocumented shared overrides, invalid rotations,
and purity other than `1` fail before runtime mutation. Only the selected mode
is packaged; discovery does not require other modes' assets.

`mode.cfg` supplies startup-only `fs_game`, parsed as data. Runtime argv selects
filesystem paths and mode-owned capacity first, executes `canonical-shared.cfg`,
then inherited private CFGs in their existing relative order, and finally
`canonical-mode.cfg` followed by native `+map_rotate`. Native exec completes
nested private CFGs before returning to the final canonical mode CFG. Thus
obsolete private rotation/voting/gameplay values cannot replace mode rules;
private credentials and environment settings remain available. Early `+set`
arguments do not override the final mode CFG. A conflicting private capacity is
rejected rather than silently overriding initialization-only slot allocation.
Legacy explicit startup maps are checked against qualified assets, then replaced
by native rotation; the engine owns randomized selection and no-repeat behavior.
Unsupported startup commands, duplicate filesystem arguments, purity other than
1 and artifact-shadowing mounts remain rejected. Private files are not rewritten.

Promod preparation now requires the existing `--allow-map-voting` overlay and
bot Ready Up correction. The canonical mode owns native vote settings; no
workspace map list or duplicate voting logic is maintained. All selected rotation
maps must be qualified by the prepared asset manifest. The original human Ready
Up and recording controls remain enabled. See the companion engine validation
record for real local runtime evidence and graphical-client limits.

Mode switching uses the same locked deployment path as deploy-homolog/production,
including container recreation, homolog approval and rollback. It never decides
that a matching `fs_game` alone means the requested mode is already active.
Removing a mode from a later catalog has no effect on immutable running or
approved artifacts; production never fetches the current catalog.

The only qualified asset preparation recipe remains the engine's `mods/pml220`
Promod pipeline. It retains FPS 333 rebuilding, Bot Warfare and all eight IWD
headers. A different `fs_game` is discovered but rejected for build until its
asset preparation is reviewed; no Promod transforms are reused for other mods.
No Zombies or Hardcore configuration/assets are supplied by this change.
The canonical policy is `match_mr12_pb`, with pure enabled. The merged optional
PunkBuster warning overlay is deliberately not enabled: missing native PB retains
its warning and requires operator qualification, not an anticheat bypass.
`inputs.json` records binary, mode ID, startup selection, all three CFG hashes,
engine/config/bot revisions, dependencies and FPS provenance. Image labels bind
mode, aggregate CFG hash, source revisions, startup map and qualified rotation
maps to the immutable image. Prepared/approved records contain seven fields:
image ID, engine SHA, asset lock hash, bot SHA, config SHA, mode ID, CFG hash.
The aggregate hash is SHA-256 of the shared, metadata and mode-server SHA-256
hex digests, each followed by a newline, in that order. Production verifies the
record against image labels and the actual homolog command before promotion.
Production reuses that identity without fetching or rebuilding.

Legacy five-field approvals lack mode/hash identity and are rejected with a
fresh-homolog-qualification message. Existing containers, private state and
rollback configuration remain untouched; do not discard historical images or
approvals. Requalify a new artifact explicitly before promoting with this branch.

Tests use local Git fixtures and mocked Docker/SSH only. Run:

```bash
for file in scripts/*.sh tests/*.sh; do bash -n "$file" || exit 1; done
shellcheck -x scripts/*.sh tests/*.sh
bash tests/operations.sh
git diff --check
```

Promod preparation enables the existing `--allow-no-punkbuster` option. The
private runtime contains `mods/pml220/promod/servercheck.gsx`, and its manifest
records `punkbuster_warning_policy_overlay: true`. Packaging appends
`set promod_allow_no_punkbuster "1"` to `canonical-shared.cfg` only for an enabled
Promod overlay. The source catalog CFGs and their provenance hashes remain
unchanged; this generated runtime setting executes before map initialization.
Private startup CFGs retain precedence and may set the policy to `0`.

To restore the original PB warning through authenticated RCON, send
`set promod_allow_no_punkbuster 0`; use `1` to suppress it again. This controls
only Promod's warning predicate. It does not supply, enable or disable native
PunkBuster authentication. `sv_pure=1`, all eight administrative IWD integrity
headers, and other Promod checks remain required. No `sv_punkbuster=1` workaround
or engine modification is involved.

Local verification generated the real overlay from hash-verified private inputs,
confirmed that removing its single added predicate reproduces the original
servercheck script exactly, and verified the overlay, enabled CFG and eight
headers in a local Docker image archive. Existing runtime assets were retained.
The regression suite checks the generator flag, missing-overlay rejection,
packaging, pre-map CFG ordering and private zero override. Graphical HUD on/off
validation remains pending; these checks do not deploy or authorize deployment.

Adoption prerequisite: at review time canonical configuration master was
`fe772fd08a05c66d1150882aefdcadedf66ea2db` (PR #1), which still has the old layout.
Engine master resolves to `8bc5f3ed2c750b199bb084de350ef1cf2687eb9d`.
The proposed catalog at configuration PR #2 commit
`b7b29be6f0d2930a1237de37954f5f591fa3f712` passes local consumer validation
(Promod, 12 slots, Crash/Strike/Crossfire/Backlot). Configuration PR #2 must be
merged before a new homolog build can resolve the
modular catalog from master. This consumer fails closed while it is absent;
it never substitutes a local feature branch or the historical monolithic CFG.
The existing builder compiles in a disposable checkout and has no separately
verified reusable engine artifact. Compilation therefore remains local on each
homolog preparation; this integration adds no cache or service. Production
continues to promote the exact approved image without compilation.

After startup and UDP 28962 checks, homolog requests interactive approval and
records the exact image ID/references in private `.state/approved`. Production
reads that approval without fetching master or rebuilding. It checks local image
labels, source/dependency revisions, platform, and that homolog still runs that
exact packaged image without mounts shadowing its artifact. A newer master does
not invalidate an approved artifact. It checks homolog UDP/Promod health, displays
the production plan and requires interactive `yes` before transferring the image
and recreating production. Retain the local image and protect `.state/`; approval
is a trusted local operator record, not a signed attestation.

Live Compose discovery rejects unsupported layouts and configuration hash drift.
A running baseline is required. Existing mounts remain; packaged code runs from
`/opt/cod4-artifact`, linked to existing game-data/plugin/usermap mounts. Persistent
home/config data stays in place. Only the selected service is recreated with
`--no-deps`; production uses UDP 28960. Bard is independent.
EC2 needs writable `/opt/services/cod4`, Compose v2, Bash, timeout, dd and grep.
Host-loopback UDP checks allow several minutes for inherited startup delays and
verify `fs_game=mods/pml220`; rollback checks the previous game mode.

Production lifecycle commands target only the existing `cod4-production` container.
`on` starts it without building or recreating; `off` requires interactive `yes`
when running because it disconnects players. Repeated calls leave the requested
state unchanged. `status` reports state, immutable image ID and configured image.
Lifecycle changes share the checkout deployment lock. They never delete volumes.

Private `.state/rollback-<environment>.json` retains previous configuration and
image identity. Failed rollouts attempt restoration and report its health.
Remote `.operations-<environment>.json` holds active Compose configuration;
original files remain. SSH loss, interruption or concurrent manual changes may
require manual recovery. Compose hashes cannot detect manual `docker update`.

Run `bash tests/operations.sh` for local-only mocked tests. Run `bash -n` on each
shell file and `shellcheck -x scripts/*.sh tests/*.sh` when ShellCheck is available.
Never commit `.state/`, credentials, environment files or private runtime data.

## Read-only qualification (2026-10-25)

Verified over SSH alias `aws-prod`, without changing runtime resources:

| Item | Production | Homolog |
| --- | --- | --- |
| Container | `cod4-production` (running) | `cod4-homolog` (running) |
| Compose project / service | `cod4-production` / `cod4` | `cod4-homolog` / `homolog` |
| Compose file | `/opt/services/cod4/compose.prod.yaml` | `/opt/services/cod4/homolog/compose.yaml` |
| Project directory | `/opt/services/cod4` | `/opt/services/cod4/homolog` |
| Published UDP → container UDP | `28960 → 28960` (IPv4/IPv6) | `28962 → 28960` (IPv4/IPv6) |
| Image ID | `sha256:7050ddb6927fdf0b6703d605f23ebcf2bfb14553c1db01173ec0035294995770` | same base image |

Production's live Compose hash matches its container. Local adaptation of that
resolved configuration retains all eight mounts and UDP mapping. Production
mounts shared `main`, `zone`, `plugins`; writable `production/home` and
`production/usermaps`; read-only `experimental/mods`, `experimental/integrity`
and `production/bin/cod4x18_dedrun-jcod4x`. All paths are under
`/opt/services/cod4`. The UDP response reports `fs_game=mods/pml220`, engine
revision `ddd65fce1a1093017bad2dbb6840d75d11c0d56f` (build 1229).

Homolog uses bind-mounted release `20261025-9056f3c`. Its `manifest.json`,
release `runtime/inputs.json` and `evidence/build-record.json` record source
`9056f3cfc5c74a49e23600406c2cd0e7ab94bfa8` and binary SHA-256
`8e9b03978335721c4323f239c75800905bf34eb5cc31dc408b498a5e67deb0f0`.
The shared base image lacks source/dependency provenance labels. This legacy
layout is **not qualified for image promotion**: promoting its base image would
omit the tested binary/mods. No local `.state/approved` was present. The production
script rejects it; do not manufacture an approval from the base image ID.

Before the first production deployment, separately authorize qualification of a
packaged homolog artifact through the existing local build/test/approval workflow.
That changes homolog and was not performed in this task. Retain its approved local
image and `.state/approved`. After that prerequisite and explicit production
authorization, run from this checkout in an interactive terminal:

```bash
cd ~/Projects/ec2-workspace
./scripts/production.sh status
./scripts/deploy-production.sh promod
# Review the displayed image/revision/target, then type yes at the prompt.
./scripts/production.sh status
```

Do not run `off` first: deployment requires a running rollback baseline.
There is no deployment on PR merge. The owner supervises the first rollout.

## Local image qualification (2026-10-25)

Built from clean isolated canonical checkouts, with the pinned Bot Warfare source:

| Input | Revision / SHA-256 |
| --- | --- |
| Engine master | `8bc5f3ed2c750b199bb084de350ef1cf2687eb9d` |
| Promod configuration master | `190c715a449fa4354ecf1c49bc8d51e0a0cfa1a0` |
| Bot Warfare | `7b52b462e40fa68287b9e54602e52da83b17766c` |
| Compiled ELF32/i386 engine | `d10a3c56691bd662fcbd443a4ccc3d51e1abc61d2c33538758ec5112522e0b7c` |
| Canonical configuration content | `21344b5d93b1ea246d20513d35351f152af97e68153500bb42b5b9e5cfb09b56` |
| Rebuilt 333 FPS fastfile | `f9c19687061403fbaaf44d4c90d8832392a3bc32f51211e6a1408c90c9ce80c2` |

Local private runtime image:
`sha256:ecf0dcb5a4152a4f9fba4e33f244fc459ba5ec282b12e4c49457b14f5bddf30a`.
Docker 29.9.2 built and inspected this identity. Extraction verified its revision
labels, binary/configuration hashes, two unchanged Promod IWDs, all eight integrity
headers and FPS manifest. Official OAT v0.34.0 executable hashes matched the
upstream tool's pins; its reparsing/inventory checks compared 141 extracted assets,
changing only the two FPS menus and adding their required menu-list containers.

Authorized Promod assets/headers came from the explicitly supplied sibling paths;
game data came from the owner's Steam installation. All 21 Steam IWD archives
passed CRC validation. The packaged entrypoint loaded Crash and the canonical
`match_mr12_pb` configuration, reported `sv_pure=1`, loaded eight administrative
checksums and exited cleanly. Game data was mounted read-only in disposable,
network-isolated containers, outside the image. No obsolete PoC directory was
used. Existing remote game-data mounts remain required.

The Bash syntax, ShellCheck, operations suite, integrity loader tests (6), FPS
policy tests (3), PunkBuster warning-policy tests (3) and native bot-policy tests
passed. Runtime scenarios passed: administration/controls (117 s), gameplay
(45 s), admission policy (75 s), active rotation (135 s), six-client burst (30 s),
legacy admission (30 s), missing waypoints (30 s), and all 21 map wrappers with
zero bots (240 s). Runtime checks retained pure and all eight headers. Private
build logs, manifests and per-scenario acceptance evidence remain under ignored
`.state/qualification.Sq8SSr/`; `.state/prepared` records the candidate identity.
No homolog approval was created.

Remaining qualification: graphical FPS/movement and real-client pure/download,
reconnect and authentication behavior. The tested build exposes no
`sv_punkbuster` cvar; native PB protection is unavailable in this build, while the
canonical PB mode and unsuppressed Promod warning policy remain. A PB-required
rollout needs that prerequisite resolved. The offline runtime also reports missing
`steam_api.so`; Steam authentication is unqualified. Existing mbedTLS compiler
warnings and PIE/text-relocation linker warnings remain. These local checks do not
authorize deployment. No EC2 access, production/homolog changes, registry upload
or PR merge occurred.

## Immutable engine startup

Managed startup argv now includes `+set sv_autoupdate 0`. This requires an engine
artifact built from `ghptc/cod4x-server` commit
`65f1f87` ([engine PR #11](https://github.com/ghptc/cod4x-server/pull/11)), or a later
revision containing that change. Older binaries accept an unknown cvar without
disabling the updater, so changing argv alone is insufficient. Build and qualify
a new immutable artifact through the existing reviewed workflow before use.

The native startup-only option skips server self-updating, preserving crypto,
authentication, pure verification, game and bot startup. It does not control the
separate client-update backend. Keep `read_only: true` / `ReadonlyRootfs=true`;
no writable mount for the updater is needed. Managed argv rejects enabling the
updater and retains private CFG ordering, canonical mode selection, existing
mounts, image identity and rollback records.

Local verification: 21 Python fixtures and `bash tests/operations.sh` pass. The
operations suite uses mocked Docker/SSH and never contacts EC2. Companion engine
fixtures reproduce EROFS and the lock wait in read-only Docker, then start Promod
on `mp_crash` with eight integrity headers, `sv_pure=1`, and 12 AI-ready bots when
disabled. See the engine's `docs/autoupdate.md` for exact evidence and limitations.

Rollback retains the prior image/configuration identity through the existing
rollback flow; it never edits engine binaries in a running container. A prior
engine may retain the original read-only updater delay. These changes do not
authorize deployment or any production/homolog/Bard service action.

## Before the Dawn packaging and RCON switching design

Status: private original-file packaging and master-based image preparation are supported; RCON activation remains disabled. A catalog entry is not an approved artifact.
The companion engine command is an administrative **preflight only** and reports
unavailable without submitting or executing a deployment request.

The companion config catalog owns `modes/zombies/mode.cfg` and `server.cfg`.
Engine `tools/btd/prepare.py` verifies the owner's original Alpha 001 package,
preserves `mod.ff`/three IWDs and notices without decompiling, and records hashes.
`modes.py package` recognizes this explicit recipe, checks required assets and the
binary, and does not run Promod FPS or Bot Warfare transformations. No third-party
asset is added to a public repository or published image by this change.

Zombies uses `COD4_BTD_ASSETS` (the directory containing `btd_alpha_001/`
and `readme.txt`) and `COD4_INTEGRITY_HEADERS`. It never applies Promod FPS or
Bot Warfare transformations. Its provenance records the original BTD lock hash
and `none` for the inapplicable Bot Warfare revision. Production still promotes
only the exact image approved and currently healthy in homolog, without fetching
or rebuilding. A selectable mode is not gameplay certification.

```bash
COD4_PREPARE_ONLY=1 ./scripts/deploy-homolog.sh zombies  # local build only
# After real-client qualification, under supervision:
./scripts/deploy-homolog.sh zombies
```

The unused GitHub Release path is retired in `docs/releases/retired/`; its source,
workflow and tests remain historical evidence. Version arguments are rejected.
No GitHub App, release, runner, registry or additional deployment framework is used.
Existing `.state` approvals, rollback records and deployed services are untouched.

The original vendor defaults are hash checked and appended as fixed execs to the
shared phase. Their names must be simple BTD CFG basenames present in the asset
manifest. Shared/vendor defaults → private CFGs (including nested execs) → final
canonical mode → native rotation remain ordered. Original sample `server.cfg`
with sample passwords/missing trade exec is excluded. Private admin identities,
credentials, persistent storage and unrelated runtime fields remain private.

### Existing limits verified in source

- `runtime.py adapt` selects startup `fs_game`, capacity and canonical CFGs;
  it preserves read-only root configuration, mounts, environment and credentials.
  It does not itself validate that every incoming service is read-only.
- Engine `fs_game` is initialization protected, and each artifact packages one
  selected mode. A map or CFG reload cannot change immutable image identity.
  Use recreation of the single target container and require client reconnect.
- `game-mode.sh` delegates to the existing environment-scoped deployment path.
  Production selects an approved exact image without rebuilding; homolog builds
  separately. Existing `--no-deps --pull never --force-recreate` preserves the
  boundary against unrelated services and implicit pulls.
- Approval currently stores **one** image and production additionally verifies
  that same image is currently running in homolog. There is no multi-mode
  qualification registry. Do not silently relax this approval rule to make an
  automatic round trip possible.
- The current nonblocking deployment lock is per workstation checkout. It does
  not serialize two different checkouts or an eventual host-local RCON worker.
- Existing rollback saves the previous configuration and checks its health on
  ordinary failures. It has no completed durable recovery protocol for a crash
  after recreation starts. A saved file alone is not crash-safe activation.
- These scripts operate from an interactive workstation via SSH and include image
  transfer/build paths. Calling them directly from game input would violate the
  intended trust and no-build boundary.

### Proposed transaction before enabling activation

The minimum viable bridge is a narrow host-owned execution path reusing the
existing deployment functions, with a typed mode-ID request and environment fixed
by the operator. It must not give the container a Docker socket, shell, SSH key,
build capability or a general-purpose remote command API. No bridge is added now.
A host-local bounded Unix socket is a candidate transport; an unauthenticated
writable-home request file is not. Transport endpoint identity, peer/container
identity and permissions require local validation before adoption.

Engine power 100 is necessary but insufficient for host authorization: original
GSC can execute console commands, and system/GSC and legacy UDP RCON share default
invoker context. Add nonforgeable authenticated ingress context for a future
activation handler and clear it on every exit. A plain power check, configurable
cvar or writable request file cannot stand in for authenticated RCON origin.
Existing password/Source RCON authentication remains the ingress authority; no
second remote password or privilege role is proposed.

After that boundary is validated, the host path must:

1. Take a single host-owned nonblocking lock for the pinned environment/container.
   Return busy for concurrent requests; do not mutate or start a second operation.
2. Resolve only exact registered IDs (`zombies`, `promod`, and `hardcore` only after
   separate qualification) from an owner-controlled, per-environment artifact
   allowlist. Reject absent/unqualified IDs with a reason before runtime writes.
   No paths, shell text, URLs, tags, argv or environment names come from RCON.
3. Verify the selected immutable image is already local, its source/config/asset
   identities and valid homolog evidence. No fetch, download, image load, build
   or image publishing is permitted on this request path. Multiple approved modes
   require an explicitly reviewed extension to today's single-live-homolog rule;
   the current rule remains authoritative until then.
4. Snapshot exact prior image/config/private mounts, rootfs policy and credentials.
   Validate `read_only=true` and no shadowing mounts for both candidate and prior
   runtime. Retain private bytes and volume identities rather than generating
   replacements from public configuration.
5. Persist a restrictive transaction record with previous/target image and phase
   before applying any change; atomically replace and durably flush it. A retry
   or worker restart must recover the same transaction before accepting another.
6. Recreate only the pinned service using the existing no-dependency/no-pull path.
   Rootfs stays read-only, writable persistent volumes stay mounted, and no
   homolog/production/Bard or unrelated service is touched as a side effect.
7. Verify exact container image/provenance, `ReadonlyRootfs=true`, retained mounts,
   running state, protocol status, target `fs_game`/mode/gametype and map readiness.
   BTD artifact qualification must already include real native zombie combat;
   `getstatus`, `CS_ACTIVE` and an idle map are insufficient gameplay evidence.
8. Commit the target as active only after health passes. Otherwise recreate the
   exact previous runtime, verify rollback health and report failure. If rollback
   fails, retain the transaction and reject further requests for operator recovery.

The response must distinguish denied/unavailable, accepted pending, busy, healthy
active, rolled back and recovery required. The initiating UDP RCON connection
cannot survive container recreation. Return an operation ID before disconnection;
a later authenticated status query reports the persisted result. Never print
“switched” on request receipt or before target health checks.

### Qualification and remaining work

Local tests cover catalog selection, BTD original-file packaging, tampered/missing
assets, invalid default paths, handler powers and malformed/unavailable requests.
Real loopback processes cover all 15 original maps, private conflicts, credentials,
purity, eight headers and process restart. Generated `read_only` preservation is
checked; an actual Docker rootfs or reconnect transition is not claimed.
Existing operations mocks cover rollback success/failure, exact-image promotion,
mount retention and unrelated-service isolation; no SSH or Docker daemon is used.

Before activation: qualify native BTD waves/navigation/damage/win/loss with a real
client; qualify its separate image recipe and dependency labels; review multi-mode
homolog approval; validate authenticated request transport, host-wide locking,
crash recovery, container restart/reconnect and failure rollback. Promod→Zombies
and Zombies→Promod are not implemented or certified. Hardcore is not registered.
No EC2 access, live service changes, deployment, approval changes or merge occurred.

Rollback of this staged change is ordinary commit reverts. Existing Promod
artifacts and approval records remain intact, and no private game asset is deleted.

Evidence: BTD local runtime passed 53 startup/map/preflight checks in
`/tmp/cod4-btd-qualified-biebk8zp/results.json`; Promod passed 53 regression checks
in `/tmp/cod4x-promod-integration-9aouxfu4/results.json`. Workspace tests passed
22 Python tests and the existing complete operations mock suite. The candidate
catalog and engine changes were tested together; these results do not approve an
image or validate an active RCON bridge. Full private logs/assets remain outside Git.
