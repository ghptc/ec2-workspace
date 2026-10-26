# Zombies delivery decisions and acceptance evidence

Reconciled 2026-10-26. This document tracks the current operator mission; older
readiness reports remain historical test evidence. A test result from a previous
artifact does not qualify a new artifact or prove graphical client gameplay.

## Source and ownership

Protected `master` is authoritative in all three repositories. Work uses focused
branches, Conventional Commits, required GitHub checks and independent review.
The operator alone authorizes merge, homolog deployment, production deployment,
credential access and destructive operations. No production or Bard changes are
authorized by the mission.

| Repository | Ownership | Reconciled evidence |
| --- | --- | --- |
| `ghptc/cod4x-server` | Native engine/protocol, original-asset preparation, engine integration tests | [#16](https://github.com/ghptc/cod4x-server/pull/16), [#18](https://github.com/ghptc/cod4x-server/pull/18) |
| `ghptc/cod4-config-server` | Canonical shared/mode CFG contract, supported rotation and policy | [#8](https://github.com/ghptc/cod4-config-server/pull/8), [#9](https://github.com/ghptc/cod4-config-server/pull/9) |
| `ghptc/ec2-workspace` | Local exact-source build, deployment transaction, artifact approval, adaptation, health and rollback | [#9](https://github.com/ghptc/ec2-workspace/pull/9), [#12](https://github.com/ghptc/ec2-workspace/pull/12) |

GitHub PR inspection confirms workspace #12, engine #18 and configuration #9
merged on 2026-10-26 at 20:32:56Z, 20:32:23Z and 20:32:33Z respectively. Their
reported merge commits are `e827fe75a82254fbb11eaa977709df4a4d246705`,
`cb0f0f489d3323de968ea426ea19ba7862c50db8` and
`382f7e5b6430fc01483b37dbd25325f8c88faeb3`. These record merge events; fetch
current masters before implementation/building. The earlier unmerged wording and source
tips in [zombies-readiness.md](zombies-readiness.md) predate those events.
Repository issue searches returned no issues; the linked PRs carry the available
implementation history. Retrieved discussions for workspace #12, engine #16 and
configuration #8 contained no comments, so no separate accepted review suggestion
is inferred from those discussions.

## Decision log

| ID | Status | Decision and source |
| --- | --- | --- |
| D01 | Operator requirement | Preserve master-based deployment, mandatory CI, homolog approval, exact-image production promotion and rollback. No automatic merges or deployments. Current mission and workspace #12. |
| D02 | Rejected architecture | GitHub Releases, dedicated runners, VMs and new deployment infrastructure are excluded. Release architecture/migration documents and `docs/releases/retired/` are historical proposals, never active requirements. Current mission and workspace #12. |
| D03 | Implemented, gameplay unqualified | Preserve original BTD Alpha 001 fastfile, three IWDs and notices with locked integrity checks; no decompilation, replacement AI or Promod/Bot Warfare transformations. Engine #16, workspace #9/#12. |
| D04 | Implemented | Apply canonical shared defaults, private CFGs, then canonical mode rules and native rotation; mode owns purity, gametype, rotation and AI policy. Configuration #9 and workspace #8/#12. |
| D05 | Qualification boundary | Startup, getstatus, loaded maps, synthetic admission and CS_ACTIVE do not establish zombie combat or clean-client compatibility. Current mission and readiness evidence. |
| D06 | Activation disabled pending proof | RCON mode preflight is not a host transition. Existing single-live-homolog approval and per-checkout lock cannot silently become a multi-artifact, host-wide authorization mechanism. README switching design and workspace #9. |
| D07 | Required future behavior | Allow only authenticated, elevated requests for prequalified `promod`/`zombies` exact images; reuse the existing transaction and return pending until health succeeds. No shell input, Docker privileges, runtime build/download or early success. Current mission. |
| D08 | P0 investigation constraint | Reproduce the reliable-command error using the real Arch Steam/Proton client before changing protocol behavior; measure slow downloads separately and establish causality. Buffer enlargement and validation weakening without evidence are excluded. Current mission. |

The bounded host Unix socket in the README is a **proposal**, not an adopted
transport requirement. Host identity, authenticated ingress, crash recovery,
multi-mode qualification and actual cross-mode rollback still require design and
behavioral proof. Preserve the original single-image approval semantics until a
reviewed extension proves the requested guarantees.

## Traceable requirements matrix

Status below is the recovered baseline, not a claim that this mission has passed.
Prior results and artifact identities are in [zombies-readiness.md](zombies-readiness.md).

| ID / priority | Acceptance criterion | Required evidence | Baseline / owner |
| --- | --- | --- | --- |
| C01 / P0 | Reproduce actual `CL_CGameNeedsServerCommand` failure | Clean Arch Steam/Proton client version, server/artifact IDs, client/server logs, command sequence/ack trace and reproduction steps | Operator reports failure; reproduction pending. Engine + quality. |
| C02 / P0 | Diagnose download duration and relation to command loss | Exact requested files/bytes, transport, redirect behavior, elapsed duration and throughput; compare long download and cached reconnect | Payload measured: 33,201,830 bytes; canonical HTTP disabled. Real transfer/timing and causality pending. Engine + quality. |
| C03 / P0 | Smallest verified correction, clean client connects | Behavioral regression reproduces old failure, passes correction; real clean client downloads, loads assets and joins | Pending. Engine + reviewer. |
| G01 / P1 | Original assets and supported maps remain intact | Locked original bytes, eight headers, original notices, 15 supported maps with correct `war`/purity | Fresh 53/53 native baseline checks and matching payload hashes; final image and gameplay unqualified. Gameplay + quality. |
| G02 / P1 | Human can survive, shoot/kill zombies and receive damage | Real-client session with timestamped observations/video/log evidence tied to exact artifact | Unqualified. Gameplay + quality. |
| G03 / P1 | Waves, weapons/ammunition, pickups, respawn, multiplayer, completion and transitions work | Real-client acceptance record for each behavior, including multiple clients and supported-map transitions | Unqualified. Gameplay + quality. |
| T01 / all | Meaningful unit/native/config/container/protocol tests | Executed behavioral regression results; actual measured coverage and explicit uncovered critical paths | Prior engine/config/operations suites exist; no coverage percentage established. Quality. |
| T02 / all | Preserve Promod | Fresh artifact regression for admission, Ready Up, voting, rotation, purity and restart; real-client limits disclosed | Fresh 53/53 native baseline checks over 21 maps; final master-derived image and graphical match not established. Quality. |
| S01 / P2 | Strict allowlist, elevated authenticated ingress and isolation | Tests deny untrusted/GSC/system/unauthorized/malformed requests; no arbitrary shell, Docker socket, credentials or builds in game container | Preflight only; activation disabled. Deployment + engine + reviewer. |
| S02 / P2 | Safe transition and truthful reporting | Host lock, durable operation state, pending ID, disconnect/reconnect, exact image/mount/rootfs validation and target health before active status | Not implemented/qualified. Deployment + quality. |
| S03 / P2 | Rollback/recovery and qualification | Failed health restores exact previous qualified artifact/config and verifies health; interrupted transition recovers; concurrent requests serialize | Ordinary mock rollback exists; actual cross-mode/crash recovery unqualified. Deployment + quality. |
| D01 / delivery | Exact master homolog command and successful homolog Zombies | `./scripts/deploy-homolog.sh zombies`, separately authorized rollout, health and real-client gameplay tied to exact image | Prepare-only command previously passed; live mission homolog not established. Deployment. |
| R01 / delivery | Independent review and mandatory CI | Reviewer distinct from implementer, resolved critical findings, required checks on final PR heads, operator merge approval | Existing required checks documented; new changes require fresh review/CI. Reviewer + all. |
| R02 / delivery | Final report | PRs/commits, exact artifacts, test logs/evidence, uncovered paths and remaining risks without fabricated gameplay | Pending. Context architect. |

Supported BTD map IDs: `mp_convoy`, `mp_bloc`, `mp_bog`, `mp_broadcast`,
`mp_countdown`, `mp_crash`, `mp_creek`, `mp_crossfire`, `mp_farm`, `mp_overgrown`,
`mp_pipeline`, `mp_showdown`, `mp_strike`, `mp_vacant`, `mp_cargoship`. Original
author exclusions for District and Killhouse remain authoritative.

Known regressions retained as context: stale string-latch restoration (engine
`33e62e1`), stale private mode CFG precedence (workspace #8), read-only updater
startup stall (workspace #7 and engine #11), persistent home-path rejection
(workspace #5), reused stale Promod overlay causing Ready Up failure, and short
vote cooldown bounds (engine #15). Do not conflate these corrected historical
defects with the unproven reliable-command root cause.
