# Zombies P0 test and delivery report

## Recorded causes

The preserved production log at 2026-10-27 02:43:56 UTC identifies an undefined
`targetname` comparison inside the original BTD player-killed callback. A native
synthetic-player suicide reproduces the same callback stack and game shutdown.
The production damage source remains unknown. There is no evidence that a map
transition or wave progression triggered that recorded exception.

After correcting the death guard, a separate native first-wave test reproduced
an undefined-vector assignment: original spawn structs lack angles. The second
focused correction initializes spawn angles. Neither correction changes Promod,
VM semantics or the original package bytes. Both generated private overlays are
hash-bound to the verified original plaintext source members.

## Local results

| Suite | Result | Scope |
|---|---|---|
| Engine unit tests | 44 run, one optional client-source test skipped | Includes seven BTD preparation/identity tests; existing native protocol fixtures |
| Workspace operations | 50 Python tests plus shell scenarios pass | Includes 19 host-controller tests; existing promotion, failure and isolation fixtures |
| Original death expression | Expected undefined/string runtime failure reproduced | Native VM, developer error reporting enabled |
| Original player-killed callback | Exact error and `Server disconnected` reproduced | Native synthetic-player spawn/suicide, original callback/setup |
| Guarded player-killed callback | Pass | Original callback completes and player respawns |
| Original wave spawn, death guard only | Expected undefined-vector runtime failure reproduced | Vendor wave loop and zombie constructor |
| Corrected lifecycle E2E | Pass, no script errors | Native death/respawn, vendor zombie spawn/death, wave two, two UDP admission handshakes, mp_strike/mp_crash transitions |
| Fresh preparation and packaging | Pass | Pinned original package retained, both source overlay hashes validated |
| Existing BTD integration | 53 checks pass | All 15 installed maps, fresh process restart, private precedence, purity, headers, denied mode activation; developer reporting enabled |
| Existing Promod integration | 53 checks pass | Existing gameplay/administration/map fixture suite |
| Controller round trip | Mocked Promod→Zombies→Promod passes | Exact snapshot rollback, failed rollback blocking, locking, authorization, Docker/private/UDP guards |
| Real Compose mode-controller transition | Pending | Requires reviewed installation and independently qualified images |
| Operator-supervised real client gameplay | Pending | Mandatory before gameplay qualification or promotion |
| Independent code review and approved merges | Pending | Operator gate; no automatic merge |

The native incident reproductions use preserved binary SHA-256
`87df02a8288db1e038a8fd3c62afd9db7cd4c88124f44d6b6892c7dff13986c0`
(recorded engine source `695441bd1fb7b6832f4945aaa057462261ccbc93`). This is a
disposable runtime reproduction of the exact script failure, not a claim that the
failed production Docker image was redeployed. The existing BTD/Promod integration
runs use local binary SHA-256
`7246c1b8d26bcd509160eaf12627e6299072af1655af16005710272b6a0df8e3`.

Private evidence is preserved under
`.state/incidents/zombies-p0-qualification/`, with per-run console/results and a
SHA-256 manifest. Additional logs are `.state/incidents/zombies-p0-*.log`.
Original incident/recovery evidence is retained. No private source, game assets,
full runtime logs or credentials are published in the PRs.

## Review and CI

- [Engine correction PR #20](https://github.com/ghptc/cod4x-server/pull/20)
  and [existing Linux/Windows CI run](https://github.com/ghptc/cod4x-server/actions/runs/40445229802).
- [Draft workspace controller/packaging PR #15](https://github.com/ghptc/ec2-workspace/pull/15).
  Its existing Operations check runs all workspace Python/shell tests.
- No configuration-repository change is needed: the evidence identifies original
  BTD script defects and an operations trust boundary, not canonical CFG defects.

No CI runners, release artifacts, GitHub Releases or deployment framework were
added. Both PRs target master and use Conventional Commits. Keep the workspace
PR dependent on the engine correction before enabling overlay-required packaging.

## Production preservation and next gate

Final read-only Docker inspection confirms the same production and homologation
container IDs, images, configuration, mounts and networks as the recovery baseline.
Docker returns mount arrays in varying order; comparison normalizes by destination
while checking every mount property. This ordering behavior also has a controller
regression test.

External UDP 28960 responds with `fs_game=mods/pml220`, `g_gametype=sd`,
`sv_pure=1`; final observed map was `mp_showdown`. Production remains on
`sha256:ed51e1a28884e49a0f9a73f51787797e61e931d6466e407be9137a60747ad16d`.
Zombies homologation remains the same container/image on UDP 28962.
The protected `.state/approved`, rollback snapshot and `common.sh` hashes match
the pre-recovery capture. No remote service mutation occurred during this mission.

Next: independent PR review, passing mandatory CI and operator-approved merges.
Only then deploy from master to homologation and conduct supervised client gameplay.
Host-controller installation, real Compose transition/rollback qualification and
production promotion each remain gated. The root CLI and RCON host activation
are not installed/enabled on production.

See [the operator runbook](zombies-recovery-and-modes.md) for exact commands and
remaining RCON authentication/transport blockers.
