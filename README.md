# CoD4 remote operations

```bash
./scripts/deploy-homolog.sh promod
./scripts/deploy-production.sh promod
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
fetches master again and rejects a changed revision or unapproved artifact. It
requires that image still running in homolog and interactive confirmation, then
promotes it without rebuilding. Retain the local image and protect `.state/`.

Live Compose discovery rejects unsupported layouts and configuration hash drift.
A running baseline is required. Existing mounts remain; packaged code runs from
`/opt/cod4-artifact`, linked to existing game-data/plugin/usermap mounts. Persistent
home/config data stays in place. Only the selected service is recreated with
`--no-deps`; production uses UDP 28960. Bard is independent.
EC2 needs writable `/opt/services/cod4`, Compose v2, Bash, timeout, dd and grep.
Host-loopback UDP checks allow several minutes for inherited startup delays.

Private `.state/rollback-<environment>.json` retains previous configuration and
image identity. Failed rollouts attempt restoration and report its health.
Remote `.operations-<environment>.json` holds active Compose configuration;
original files remain. SSH loss, interruption or concurrent manual changes may
require manual recovery. Compose hashes cannot detect manual `docker update`.

Run `bash tests/operations.sh` for local-only mocked tests. Run `bash -n` on each
shell file and `shellcheck -x scripts/*.sh tests/*.sh` when ShellCheck is available.
Never commit `.state/`, credentials, environment files or private runtime data.
