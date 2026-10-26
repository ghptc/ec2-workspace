# Independent review: mode-switch activation boundary

Reviewed 2026-10-26 against the current operator mission. Reviewer authored no
engine/configuration/deployment implementation. This assessment covers existing
source, not approval of a future switch implementation or certification of live
services. No deployment, credential access or service mutation was performed.

Source references below are pinned to workspace
`e827fe75a82254fbb11eaa977709df4a4d246705` at
`/home/gabriel/Projects/ec2-workspace` and engine
`57f65e5fb38762c5a6b0d647107c16dc0cdc87b4` at
`/home/gabriel/Projects/cod4x-server`. The inspected implementation files had no
working-tree changes. These are inspected source identities, not a claim that
the sibling engine feature checkout is the current protected master. Line
references apply to these exact sources.

The current engine `change_mode` command is safely inert. In
`cod4x-server/src/sv_cmds.c:2378–2417`, status reads only `fs_game`; every valid
requested identifier returns `unavailable` and `Runtime unchanged`. It invokes no
IPC, shell, filesystem writer or deployment action. Registration at line 2428 and
the handler's own power check at line 2386 require power 100. Input validation
bounds identifiers to 32 lowercase alphanumeric/hyphen characters beginning with
a letter. No exploitable critical finding was identified in this nonmutating
handler. Activation must remain disabled.

## Blockers before activation

| Finding | Evidence | Required resolution |
| --- | --- | --- |
| Critical: power 100 alone does not prove authenticated ingress | Engine `src/cmd.c:1389–1394` resets the default identity to power 100, `System/Rcon`; UDP RCON calls the generic executor at `src/sv_main.c:1544`. GSC `execex` invokes that executor at `src/scr_vm_functions.c:1640`; `exec` queues console text at line 1659. | A nonforgeable authenticated-origin scope, independent of numeric power, must guard submission and be cleared/restored on all exits. Exercise unauthenticated, insufficient-power, system and GSC paths behaviorally. |
| Critical: existing approval cannot authorize a two-mode round trip | Workspace `scripts/common.sh:318–324` reads one `.state/approved` record and rejects another mode; lines 154–156 additionally require that exact image currently running in homolog. Homolog approval overwrites that single record at lines 182–186. | A reviewed qualification extension is needed for both immutable artifacts. Preserve the present production authorization rule until that extension is approved and tested; do not copy/rename approvals to bypass it. |
| Critical: direct reuse of interactive deployment entrypoint violates request constraints | `scripts/common.sh:336–341` fetches/builds for homolog; line 170 saves/loads images; lines 164 and 183 prompt interactively. `scripts/game-mode.sh:8` delegates directly to `deploy`. | Reuse validated transaction operations through a host-owned, fixed-environment path restricted to already-local qualified exact images. No fetch, build, download, image transfer or general shell API on RCON requests. |
| Critical: serialization and crash recovery do not cover a host controller | Lock at `scripts/common.sh:334–335` is rooted in one checkout. Rollback JSON at line 168 and immediate rollback at lines 173–180 have no durable phase journal/recovery protocol. | Host-wide locking; durable restricted operation records before mutation; interrupted-operation recovery; deny further activation when recovery fails. Test across callers/process restart. |
| High: current health is narrower than switch acceptance | `scripts/common.sh:84–103` checks running/healthy state, UDP status, filesystem mode, gametype and purity; line 171 checks image identity. It does not certify retained mounts, actual read-only root, map readiness or real gameplay. | Verify runtime isolation and target readiness for each transition; prequalify combat separately. Report pending until verified, and verify exact prior image/configuration health on rollback. |
| Critical qualification gate: target gameplay and reconnect lack evidence | Existing readiness report explicitly excludes clean-client pure/download compatibility, zombie combat/waves and real cross-mode rollback. | Complete P0/P1 real-client evidence and transition/reconnect/rollback tests before activation. A catalog entry or successful getstatus is insufficient. |

The deployment system can support further local engineering and isolated tests,
but **cannot safely activate automatic switching with its current single-live-
homolog approval semantics**. A bounded host Unix socket remains a proposal;
this review does not prescribe new deployment infrastructure or grant approval
to install a host controller. Preserve Promod production and keep the current
unavailable response until the blockers are resolved.

## Test and evidence limits

Executed the existing production-handler harness via
`python3 -m unittest discover -s ../cod4x-server/tests -p test_change_mode.py`:
one test passed, covering elevated permission, status, malformed input and
unavailable targets. Its initial sandbox execution was blocked with `SIGSYS`;
the approved run outside the sandbox passed. This is a native 32-bit handler
test with mocked command context, not proof of ingress authentication, a running
host bridge, container transition or gameplay. No coverage percentage is claimed.

Documentation reconciliation checked PR merge metadata against GitHub and source
ownership against code. Historical readiness test results were not rerun for
this review. Live master protection/rulesets were **not reverified** here; the
readiness report's required-check tables describe its earlier audit. The mission
matrix is context tracking authored by this reviewer and is not presented as an
independent approval of that document.
