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

Homolog fetches `origin/master` from [ghptc/cod4x-server](https://github.com/ghptc/cod4x-server)
into a clean isolated checkout under ignored `.state/`. It compiles locally,
runs the engine integrity/policy tests, and packages a Docker image. The pinned
builder and runtime base image IDs in `scripts/common.sh` must already exist
locally. Nothing is compiled or installed on EC2.

Promod LIVE 2.20 assets and integrity headers are hash-verified against that
commit's `bots/dependencies.json`. Defaults are the existing sibling installation:
`../cod4-promod-server/game/mods/pml220` and
`../cod4-promod-server/artifacts/integrity/addiwdheaders`. Override with
`COD4_PROMOD_ASSETS` and `COD4_INTEGRITY_HEADERS`; use assets you are entitled to host.
[Bot Warfare](https://github.com/ineedbots/iw3_bot_warfare) is fetched at its
separately locked commit. Image labels record source revisions and the dependency
lock hash; `/opt/cod4-artifact/inputs.json` records verified asset/binary hashes.

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
