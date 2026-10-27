# Authenticated RCON production mode bridge

Protected baselines: engine `701a7c5df46c5723705dad0408afa44fb89b0ad9`,
workspace `b77684d` (merged PR #17), configuration `9f0fa1a`. Workspace PR #15
introduced the root host CLI. This change adds an **uninstalled, disabled-by-default**
RCON bridge and strengthens its shared locking, private-byte rollback and recovery.
No production/homologation service, approval record, credential or running image
was inspected remotely or changed.

## Boundary and threat model

Trusted components are the qualified native engine, plugins, installed GSC,
private authentication/configuration, Docker daemon, host root, reviewed scripts,
protected qualification records and external verifier. Credential/command-policy
administrators are authentication authorities. Operators must retire old unlocked
deployment entrypoints when installing the shared host lock.

Attackers may send arbitrary unauthenticated game/RCON traffic, use low-permission
accounts, invoke generic GSC/console commands, forge logs/usernames/IP claims,
create another same-UID process, send malformed/replayed IPC, or disconnect the
requesting game process. None is accepted merely because its name, source address,
UID, numeric power claim, log line or writable-home file resembles an administrator.

The native engine dispatches only an authenticated raw `change_mode` command with
power 100. Generic console/GSC dispatch never submits. The host checks kernel
`SO_PEERCRED` PID, current production container ID/running state/direct executable,
executable inode inside that container, cgroup membership, protocol label and an
exact read-only bridge-directory bind. The engine independently requires a UID-zero
host peer. No game credential or host signing key is shared over this channel.

A compromised native process or malicious installed mod that steals/changes the
existing credential is an authentication-authority compromise, outside this
boundary. Host authority remains limited to two independently approved immutable
images. Classic UDP RCON is plaintext and has no cryptographic network-packet
anti-replay: host operation deduplication does not fix captured credentials or
replayed UDP commands. Protected administrative transport is an activation gate.

## Protocol and asynchronous execution

Fixed endpoint: `/run/cod4-mode-bridge/control.sock`, Linux `SOCK_SEQPACKET`.
Accepted packets are exactly:

```text
C4M1 switch <32 lowercase random hex digits> promod
C4M1 switch <32 lowercase random hex digits> zombies
C4M1 status
```

No paths, image references, container names, ports, shell text, argv, URLs, account
names or environment settings are accepted. Oversized/truncated packets, extra
fields, NUL/control suffixes and other targets fail closed. Replies contain only
fixed codes, operation IDs, modes and phases. The native parser rejects malformed
or mismatched replies, and redacts mode request arguments in game logs.

The engine submits without waiting for host preflight. The host daemon owns a
separate detached worker and durable request/transaction journals. Accepted IDs
cannot be reused. Lock contention returns busy. Already-active mode is a verified
no-op; it never recreates a container. Initial `submitted` is not acceptance.

Under the host lease, the worker checks qualification, both image identities,
exact current baseline, startup/health/local and independent external UDP status,
and a recoverable private-home archive. It records pending before acceptance.
The engine queues a fixed player notice and acknowledges on the next game frame.
An alive engine that cannot acknowledge causes denial before mutation; a stopped
engine cannot cancel an already accepted durable job.

The worker reuses `mode-controller.py`, `runtime.py adapt`, and the existing
`common.sh apply_runtime`. It recreates only production with `--pull never`, from
an already-local immutable Docker image content ID. No build, fetch, checkout,
load, download or homolog action is part of switching. Published UDP 28960,
private mounts/environment and network membership remain unchanged.

Success follows Docker identity/startup/read-only/mount/environment/network/port
checks, correct fs_game/gametype/pure status, local UDP and the root-owned external
verifier. The verifier must query from a different machine and bind its result to
the operation. A same-host hairpin is not production external qualification.

## Locking, rollback and failure

`/opt/services/cod4/.production-transition.lock` is the shared host lease. Normal
production deployment keeps it via a fixed SSH coprocess. Before announcing the
lease, that process creates a restrictive host-only deployment marker. EOF,
workstation death, failed rollback or an uncertain exit leaves the marker;
controller/bridge refuse new work even if the advisory lock has become free.
Only explicit completion after a known-healthy target/rollback clears it. A failed
preflight that exits abruptly can conservatively leave the marker too.

The bridge worker inherits the lock, and passes it to in-flight subprocesses.
Worker death cannot let another transition race a still-running apply. Once the
lease is free, daemon recovery restores only the saved previous image/config;
it never retries the target. Revoking the target or bridge activation cannot force
the target live or block an otherwise independently approved prior-image rollback.
Missing/revoked previous evidence/image, corrupt snapshots or rollback failure
records `recovery_required` and blocks follow-up. There is no automatic retry loop
for that state.

Before mutation, private-home backup validates protected ancestry, a nonsymlink
home, same-filesystem restore, archive paths/links and absence of special files.
Only the home may be a writable persistent mount. Rollback stops only production,
restores archived home bytes through a validated staging directory and atomic
renames, preserves the failed home privately, recreates the previous exact Compose
configuration/image once, and verifies it locally/externally. This preserves
private configuration bytes as well as Compose mount descriptions.

Host state remains root-only under `/opt/services/cod4/.mode-controller`.
Private snapshots, backups and child diagnostics stay out of public status.
Qualification/approval records are read, never rewritten by a request. Required
rollback and homolog approval writes now fail explicitly before progressing, even
when Bash caller conditionals suppress errexit.

## Operator interface

```text
/rcon change_mode zombies
/rcon change_mode promod
/rcon change_mode
```

The last command reports safe cached host status and refreshes it. After process
replacement, reconnect and poll again. UDP can receive an asynchronous response;
Source clients use status polling. Codes distinguish submitted, accepted, busy,
unsupported/invalid, denied, disabled, not_qualified, already_active, success,
rolled_back and recovery_required. No accepted/pending response claims completion.
Old cached status is explicitly labeled when the host is unavailable.

The existing root CLI remains available for exceptional host operations:

```sh
sudo python3 -I /opt/cod4-operations/scripts/mode-controller.py status
sudo python3 -I /opt/cod4-operations/scripts/mode-controller.py switch zombies
sudo python3 -I /opt/cod4-operations/scripts/mode-controller.py recover
```

An interrupted normal deployment marker requires operator reconciliation, not a
blind delete/retry. Preserve it and all journals, identify outstanding deployment
children, verify the exact current image/config/private state externally, then
archive the marker only with operator approval. Never change approval records to
make a denied transition pass.

## Installation and activation gates — not performed

1. Owner manually merges the engine/workspace PRs after mandatory CI and review.
   Install reviewed scripts together in root-owned, nonwritable-ancestor paths.
   Workers use isolated Python and compile verified private module source, avoiding
   writable sibling bytecode-cache imports. Do not run a user-writable checkout
   as root.
2. Prepare both actual mode images once through the existing reviewed workflow.
   Both need the new engine and `io.cod4.rcon-mode-bridge=C4M1`. Older engines are
   labeled disabled by preparation and cannot qualify for this bridge.
3. Independently qualify each exact image, including actual-client gameplay,
   supervised Promod→Zombies→Promod, notification/reconnection, shared credential
   and account continuity, private CFG search precedence, waves/bots/purity and
   rollback. Establish real external UDP 28960 verification. The local fixture
   tests below are not those approvals.
4. With explicit installation authorization, create the protected state (0700),
   root-owned lock (0644), and `/run/cod4-mode-bridge` (root-owned 0755). Bind only
   that directory read-only at the identical path in production. Do not mount the
   Docker socket, host scripts, qualification records or credentials in the game.
   Do not add the endpoint to homologation. Both runtime images remain read-only;
   review container privileges and all credential-changing administrative roles.
5. Keep the existing registry `enabled`/mode evidence gates. Separately require
   `rcon_bridge_enabled: true` only after explicit activation approval. Add
   `rcon_security_review` and `rcon_activation_approval`, each with trusted `path`,
   `sha256` and `images: {promod: EXACT_ID, zombies: EXACT_ID}`. Both mode records
   must retain actual-client gameplay, independent review, CI and operator
   approval tied to those exact image IDs. No template/evidence is auto-approved.
6. Start the reviewed host daemon with the existing operator process-management
   approach: `python3 -I /opt/cod4-operations/scripts/mode-bridge.py serve`.
   This repository neither installs/enables it nor introduces a service stack.
   Routine authorized switching then requires only authenticated RCON.

Production remains on its known-good mode throughout code review and qualification.
No merge, rollout or bridge activation is automatic. Rollback of the feature is a
reviewed code revert plus an authorized bridge stop/socket-mount removal; retain
host CLI recovery and authentication repairs. Runtime rollback needs the exact
previous approved artifact and operator authorization.

## Reproducible local checks and limits

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
bash tests/operations.sh
python3 tests/run_mode_compose.py
```

The Compose runner verifies local Unix Docker context, refuses endpoint overrides,
checks ports are unused, and creates unique owned container/project/image names.
It uses authored static UDP responders and local cached base images, with no
networked build steps; builds occur only before transitions. The actual apply
primitive, escaping, recreation, Docker identity, separate-network published UDP,
private-byte rollback and untouched owned homolog sentinel are exercised.
A real Unix credential probe binds the sender PID to Docker and verifies executable
inode/cgroup identity. Cleanup checks ownership labels and removes only resources
created by that run. Existing local containers remain untouched.

These fixture images are explicitly not games. Qualification/ownership policy is
substituted only inside the test namespace; no real approval record is created.
This is layered controller/IPC proof, not a complete live-game authenticated
RCON→root-daemon→qualified-image transition. Production activation remains blocked
on the actual-image/operator steps above.

Local evidence (2026-10-27): 67 Python tests and existing mocked operations
suite passed. Disposable Compose fixture 12/12 checks passed; private local
summary `/tmp/c4-mode-test-56f39bbe23-ces3j3ij/results.json`. Fixture base image
was the locally cached `python:3.12-slim` image ID
`sha256:23b5dc88c7dd47fec3f960b51dc30d19df9875cfbfc60f3b62d3e5b88cbccf62`.
This image ID records a test dependency, not a qualified deployment artifact.
Protected workspace baseline: `b77684d`; engine baseline:
`701a7c5df46c5723705dad0408afa44fb89b0ad9`. No configuration repository changes.
