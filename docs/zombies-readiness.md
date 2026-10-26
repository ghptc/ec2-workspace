# Master deployment and Zombies readiness — 2026-10-26

The restoration is proposed in [workspace PR #12](https://github.com/ghptc/ec2-workspace/pull/12),
[engine PR #18](https://github.com/ghptc/cod4x-server/pull/18), and
[configuration PR #9](https://github.com/ghptc/cod4-config-server/pull/9).
They require owner review and manual merge. Nothing was deployed or merged.
Production, homolog, Bard, EC2, existing private mounts and approval/rollback
records were not changed.

## Source reconciliation and deployment

Fetched protected master in all three repositories:

| Repository | Master inspected |
| --- | --- |
| ec2-workspace | `37f83f6927c93a10a078fb4748c37e52d42f8e5a` |
| cod4x-server | `695441bd1fb7b6832f4945aaa057462261ccbc93` |
| cod4-config-server | `73b9f68a62ac827f6e91a93b17efaed1578a7307` |

The requested Zombies PRs (workspace #9, engine #16, config #8) were already merged
before this task. New focused follow-up branches start from those masters; no
history rewrite, force-push, or redundant rebase was necessary.

`./scripts/deploy-homolog.sh promod` still fetches exact `origin/master` engine
and configuration commits into isolated detached checkouts and builds locally.
`./scripts/deploy-production.sh promod` still promotes the exact approved image
currently healthy in homolog, without fetching dependencies or rebuilding.
Zombies uses these same functions, image transfer, adaptation, approval, private
mount preservation, health and rollback paths. Its Bot Warfare revision is
explicitly `none`; its asset-lock provenance is the original BTD dependency lock.

The unused release source, workflow and tests were moved byte-for-byte into
`docs/releases/retired/`, preserving evidence. Version arguments are rejected.
The manual workspace release-publication workflow was also disabled on GitHub
while the archival PR awaits review. No releases, Apps, self-hosted runners,
registries, VMs or additional runtime infrastructure were created.

## Required CI and effective protection

Live GitHub ruleset and effective `rules/branches/master` responses were checked,
not inferred from local tests. Initially none required status checks. Existing
protections were preserved and these requirements added:

| Repository | Required GitHub Actions check | Active master ruleset |
| --- | --- | --- |
| ec2-workspace | `Operations tests` | [25840946](https://github.com/ghptc/ec2-workspace/rules/25840946) |
| cod4x-server | `Linux` (build plus engine tests) | [25841756](https://github.com/ghptc/cod4x-server/rules/25841756) |
| cod4-config-server | `Configuration tests` | [25857702](https://github.com/ghptc/cod4-config-server/rules/25857702) |

Each requirement is bound to GitHub Actions app ID 15368, requires an up-to-date
branch, and has no bypass actors. Before/after and effective JSON responses are
retained privately under `.state/protection-audit/`. Hosted configuration validation
uses the existing workspace mode contract at pinned revision `37f83f6`. Engine CI
extends its existing hosted build and removes inherited release publishers.
Workspace CI runs existing deployment mocks on Ubuntu 24.04 with Python 3.12.
No proprietary assets are needed by hosted CI.

The required hosted checks passed:

- [Configuration tests](https://github.com/ghptc/cod4-config-server/actions/runs/40395768389), configuration head `046c4e9`.
- [Operations tests](https://github.com/ghptc/ec2-workspace/actions/runs/40395901691), workspace implementation head `433d5e8`.
- [Linux build and engine tests](https://github.com/ghptc/cod4x-server/actions/runs/40395997029), engine head `a08696f`.

The final hosted engine job uses the existing linked native harness runners and
installs multilib/native NASM without a redundant foreign-architecture index.
Check each PR's latest head before merging; documentation follow-ups rerun CI.

## Actual local evidence

Private evidence and full logs remain ignored; no game assets or private CFGs
were committed or uploaded.

| Validation | Result and limits |
| --- | --- |
| Workspace contract/packaging | 22 Python tests pass; deployment operations mocks pass, including exact production promotion without build/fetch, Zombies `none` provenance, cross-mode approval rejection, retained mounts, health failure and rollback success/failure. Rollback here is mocked, not a live environment exercise. |
| Engine | Full 32-bit compilation passes; 33 Python tests pass with one existing skip; native rotation, voting and bot-policy checks pass. Existing PIE/text-relocation warnings remain. |
| Original BTD assets | Fresh preparation verifies locked original Alpha 001 files and all eight headers. Original `mod.ff` and three IWDs are copied unchanged; original notices retained. Unsafe sample server CFG is excluded. No AI replacement, decompilation, FPS rebuild or Bot Warfare overlay is applied. |
| BTD process integration | 53 checks pass across all 15 supported installed maps, fresh process restart, private credentials, malformed/unavailable administrative commands, `fs_game` protection, `war`, purity, headers and clean shutdown. Conflicting private `sd`, bot enablement and grace time lose to canonical mode rules. Evidence: `/tmp/cod4-btd-qualified-_n75n5il/results.json`. |
| Promod regression | Fresh current-source asset preparation passes 53 real runtime checks across all 21 installed maps, including human-only Ready Up, voting, match rotation, admission, headers and restart. Evidence: `/tmp/cod4x-promod-integration-g_l8d6lv/results.json`. An initial reused local runtime failed Ready Up because it contained an older overlay; it was preserved and replaced with a freshly prepared test runtime. |
| Actual Docker candidate | Local immutable image starts with `ReadonlyRootfs=true`, read-only game/private mounts, private CFG execution, selected `mods/btd_alpha_001`, `war`, purity, eight headers and no script errors. Explicit native `quit` exits zero; disposable container removed. Results: `.state/restoration-container-results.json`. |
| Exact master command | `COD4_PREPARE_ONLY=1 ./scripts/deploy-homolog.sh zombies` succeeds in an isolated clone, fetching the masters above and producing `sha256:ef4e9152905db081b852e897b04440a1d55cd63eb53c85b0cf24a7fdf3a676b1`. It performs no SSH, deployment or production approval. Evidence: `.state/restoration-command-check/.state/prepared` and `/tmp/restoration-master-command.log`. |

The separate PR-policy Docker candidate is
`sha256:c060ca52da295b247a68c62d0450da556c8139748e9248c06d6a7d784cd7e3c4`,
with engine `4c3b902701b39d04e6217865dfe0d10213e05547` (runtime source unchanged)
and configuration `ea8809674ba63f523c79d7d9c130748fc81ff952`.
Neither local image is homolog-approved or production-approved. The eventual
supervised deployment will build from the then-current protected masters.

The BTD supported map IDs are `mp_convoy`, `mp_bloc`, `mp_bog`, `mp_broadcast`,
`mp_countdown`, `mp_crash`, `mp_creek`, `mp_crossfire`, `mp_farm`, `mp_overgrown`,
`mp_pipeline`, `mp_showdown`, `mp_strike`, `mp_vacant` and `mp_cargoship`.
District and Killhouse remain excluded by the original authors; other installed
maps outside this original rotation are not claimed as supported BTD maps.

## Gameplay blocker and supervised next step

**Native Zombies gameplay is not qualified.** A real graphical client session
still needs to prove client asset loading and pure compatibility, zombie spawning,
wave progression, zombie navigation/attacks, player and zombie damage, weapons,
pickups, survivor respawns, and win/loss behavior. Startup, loaded maps, synthetic
UDP admission and `CS_ACTIVE` are insufficient. Prior native test-client survivors
are rejected by the original mod; synthetic admission does not complete real
client asset/message acknowledgments. No workaround changes the original mod.
The original wave AI is preserved, but its combat behavior is not certified.

Before supervised deployment: review and manually merge the three follow-up PRs
with their required checks green; fetch workspace master; supply authorized local
BTD inputs and headers and the existing pinned builder/runtime images. Retain the
existing runtime's private mount/argv contract; conflicting capacity, unsupported
startup maps/commands or artifact-shadowing mounts fail closed and require review,
not private gameplay overrides. There is no automatic RCON activation.

After those prerequisites, the exact supervised homolog command is:

```bash
export COD4_BTD_ASSETS=/private/authorized/Before-the-Dawn-Alpha-001
export COD4_INTEGRITY_HEADERS=/private/authorized/addiwdheaders
./scripts/deploy-homolog.sh zombies
```

`COD4_BTD_ASSETS` must contain `btd_alpha_001/` and `readme.txt`, with the original
locked bytes. This command recreates homolog and disconnects its players, so it
is deliberately not run by this task. Startup health checks mode and purity;
real-client gameplay must be verified before answering yes to production artifact
approval. Existing rollback restores the exact prior image/configuration and
checks its mode. Crash-interrupted SSH recovery and real cross-mode container
rollback are not newly certified by these mocks. No production command is needed
for this qualification step.
