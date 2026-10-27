# Zombies incident correction and restricted mode switching

Production remains on known-good Promod image
`sha256:ed51e1a28884e49a0f9a73f51787797e61e931d6466e407be9137a60747ad16d`.
Do not replace `.state/approved` to select a different mode. Do not promote
`sha256:94d234bf5e4c59e1f535082f655e662e0aa4df9a4b2f48dee6badac165e79260`.
No production installation or activation is part of these changes.

## Evidence and cause

Preserved incident `zombies-production-failure.log`, UTC 2026-10-27 02:43:56:
`callbackPlayerKilled` in `_callbacksetup.gsc:69` invokes the original BTD
`_globallogic.gsc:5184`. An existing inflictor has no defined `targetname`;
comparing that undefined field with `"zom"` raises a script type error. The
subsequent `Server disconnected` game shutdown explains a running process
that no longer answers game queries. The log does not identify the damage
source. Death is established by the callback stack, not temporal correlation.
There is no evidence that respawn, wave advancement, or a map transition
triggered the production exception.

A disposable synthetic-player suicide reproduced the exact callback stack,
undefined/string comparison and game shutdown. This establishes one concrete
trigger; it does not prove that the production player committed suicide.
The captured private `server.cfg` sets `developer=1`. With `developer=0`, the
VM can conceal script errors; qualification explicitly enables reporting.
Credentials and that private setting are preserved, not changed as a workaround.

After the death guard, a separate accelerated wave test exposed undefined
spawn angles: `k3/_zombie.gsc:125` assigns `level.zomspawns[num].angles` to a
native vector. The original spawn-point builder initializes only `origin`.
The additional correction initializes each generated spawn struct's angles to
`(0, 0, 0)`. This is a separately reproduced defect, not the incident cause.

The engine preparation recipe verifies the original package and pinned
plaintext raw-source hashes, then writes two private GSX overlays. It does not
modify/rebuild the original fastfile, decompile bytecode, change VM semantics,
or change Promod. Original or derived third-party scripts and full logs must
not be committed. The workspace rejects missing/tampered overlays at packaging.

## Qualification and promotion gates

1. Reproduce the original and secondary failures in disposable loopback runtimes.
2. Review the focused engine/workspace PRs independently; require existing GitHub
   checks and operator-approved merges to master. No automatic merge.
3. After merge approval, build/deploy only Zombies homologation through
   `./scripts/deploy-homolog.sh zombies`. Never run this against production.
4. An operator plays on UDP 28962: join, multiple deaths (zombie melee and other
   damage), respawn, multiple waves, disconnect/reconnect, and map transitions.
   Record exact image, UTC interval, operator, maps and script-error-free logs.
   Synthetic fixtures, admission handshakes and startup are not client gameplay.
5. Approve that exact image only after the supervised session. Keep Promod's
   recovered image and exact original runtime snapshot independently registered.
6. Validate real Compose switching and forced rollback in an isolated qualification
   environment; record authorization and rollback evidence. No production round
   trip is authorized by this runbook.
7. Request explicit production authorization with both immutable images, evidence,
   transition/rollback commands and external observer ready.

No config-server change is needed for these defects: the source errors belong
to the original BTD preparation recipe. Do not alter wave defaults or developer
settings to hide errors.

## Restricted host CLI

`scripts/mode-controller.py` runs on the Docker host as root. It delegates to
existing `common.sh` `snapshot_runtime` / `apply_runtime`, and `runtime.py adapt`.
The single accepted target is `cod4-production`, Compose project
`cod4-production`, service `cod4`, directory `/opt/services/cod4`, UDP 28960.
There are no RCON, HTTP, writable-home request-file or game-container endpoints.
The CLI never builds, downloads, pulls or loads images.

The operator must install reviewed copies of `mode-controller.py`, `common.sh`
and `runtime.py` together in a root-owned directory with no writable ancestors.
Create `/opt/services/cod4/.mode-controller` as root, mode 0700, and
`/etc/cod4-modes/qualified.json` as root, mode 0600. These are deployment changes
requiring separate production authorization; they have not been performed.
The normal user-owned checkout intentionally fails root trust checks.

The registry must contain `enabled: true` only after independent review and all
gates pass. Its `authorization_tests` and `rollback_tests` fields each identify a
root-owned evidence file by `path` and `sha256`. `modes` contains exactly `promod`
and `zombies`, each with `qualified: true`, immutable Docker `image` ID and
`labels` copied from the independently qualified image. Required labels include
engine/source, asset lock, bot dependency, config revision/hash, mode, fs_game,
startup map, qualified maps and maxclients.

Each mode's `evidence` requires `independent_review`, `mandatory_ci`,
`operator_approval`, and `gameplay`. Every item contains `path`, `sha256` and the
same `image`. `gameplay` additionally requires `actual_client_session: true`.
These are host-owner attestations backed by preserved evidence, not automatic
certification. The failed image must never receive a qualification record.

Before applying, the controller verifies the current mode is also independently
qualified and healthy, snapshots exact prior/target Compose JSON, and archives
private production home bytes under restrictive permissions. It preserves all
mounts, private environment, network and ports; verifies a read-only rootfs; and
uses a nonblocking host-local transaction lock. A journal records operation ID,
operator UID, phase timestamps, images and failures. Private apply/probe diagnostics are saved alongside the snapshots. Private values stay out of
stdout/journal; private snapshots remain root-readable only.

After recreation, Docker image/startup/private configuration checks, local UDP
readiness, and an independent external UDP check must all pass before success.
Ordinary failure recreates the exact prior configuration once and verifies it.
A failed rollback or interrupted nonterminal transaction blocks further switches
for operator recovery. No silent resumption or repeated recreation is attempted.
Do not run legacy deploy commands concurrently; their workstation locks are not
this controller's host transaction lock.

## External observer

Install `scripts/udp-mode-probe.py` on an independent machine. It accepts only a
literal IPv4 address and operation ID, queries UDP 28960 once and returns selected
status values. The controller requires the root-owned fixed executable
`/etc/cod4-modes/external-verify`, invoked with only that operation ID. Its reviewed
implementation must use an existing authenticated SSH connection to run the
probe on the independent observer, forwarding the operation ID unchanged. Pin
host keys, require batch authentication, bound connection time and stdout to probe
JSON. Use existing credentials; this task does not provision or modify them.
A probe on the EC2 host, including its public-IP hairpin path, is not external
verification and must not be installed as the verifier.

Example observer invocation (read-only):

```sh
python3 /opt/cod4/udp-mode-probe.py 54.207.64.127 preflight
```

If the observer connection is unavailable, activation is rejected before any
production mutation. If it fails after recreation, rollback is attempted.

## Exact operator commands after authorized installation and qualification

Assuming the reviewed scripts were installed at `/opt/cod4-operations/scripts`:

```sh
sudo python3 /opt/cod4-operations/scripts/mode-controller.py status
sudo python3 /opt/cod4-operations/scripts/mode-controller.py switch zombies
sudo python3 /opt/cod4-operations/scripts/mode-controller.py switch promod
```

The last command is the normal verified return to the recorded Promod image.
On `recovery_required`, stop. Preserve the journal, snapshots, private archive,
Docker inspection and logs. Display a fresh incident recovery plan using the
recorded `OPERATION-previous.json` with existing `apply_runtime`, then obtain
explicit operator approval; do not delete `active.json` to bypass the guard.
The preserved one-time October 27 recovery script has already executed and must
not be reused.

## RCON blocker

`/rcon change_mode zombies` and `/rcon change_mode promod` remain unavailable.
The existing engine handler reports this accurately. Its power check cannot
prove authenticated RCON origin: legacy UDP RCON, local console and GSC calls
share invoker context. Enabling a host bridge requires nonforgeable authenticated
ingress provenance, a narrowly authenticated transport and operation-status
reporting that survives recreation. No privileged plugin, Docker socket, generic
shell executor or second password is added. Until those boundaries and their
negative authorization tests pass, use only the root-authorized host CLI.
