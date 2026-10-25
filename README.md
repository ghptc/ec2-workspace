# CoD4 remote operations

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

Only Promod is supported. Local prerequisites: Bash, Git, Docker, Python 3.11+
and GNU coreutils/flock. SSH uses `~/.ssh/config`, alias `aws-prod`, batch mode
and strict host-key verification. Trust the host key before running commands.
System SSH includes are bypassed without changing them.

Homolog fetches `origin/master` from both canonical repositories,
[engine](https://github.com/ghptc/cod4x-server) and
[configuration](https://github.com/ghptc/cod4-promod-server), into clean detached
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

Canonical `config/promod.cfg` is packaged as `canonical-promod.cfg` within the
mod VFS and executed before inherited runtime arguments/private configuration.
Private settings retain precedence; no private configuration file is overwritten.
The canonical policy is `match_mr12_pb`, with pure enabled. The merged optional
PunkBuster warning overlay is deliberately not enabled: missing native PB retains
its warning and requires operator qualification, not an anticheat bypass.
`inputs.json` records binary, configuration, dependency and FPS provenance; image
labels and the approval record include both source revisions. Production reuses
that identity without fetching or rebuilding.

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
