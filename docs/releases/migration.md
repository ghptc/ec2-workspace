> Historical, retired proposal. Use the master-based commands in the root README.

# Migration and recovery

## Preserved inventory (2026-10-26)

No EC2 inspection was performed. Remote runtime details in the main README are
historical evidence, not a current environment inventory. A redacted local snapshot
is retained at ignored `.state/release-migration-inventory-20261026.json`; the
inventory command never exports rollback secrets or contacts Docker/SSH.
All four local image IDs below were confirmed present using only the local Docker
Unix socket. No images, containers, volumes or pre-existing evidence were removed.

| Local evidence | Preserved image ID | Record SHA-256 |
| --- | --- | --- |
| `.state/approved` | `sha256:ed51e1a28884e49a0f9a73f51787797e61e931d6466e407be9137a60747ad16d` | `833db42c83eb60cc177df844aea55fe971c2ecdbeabdeb92551374369114d384` |
| `.state/prepared` | `sha256:ecf0dcb5a4152a4f9fba4e33f244fc459ba5ec282b12e4c49457b14f5bddf30a` | `bfadc19d671d757ae3518eb9c8a0ec463a09debe3770ccb0ae0cd35f7e4b18a8` |
| `.state/rollback-homolog.json` | `sha256:3f43a93979f49c0ff864ae4fe0bc19ff19740ac9149d175038b7c312ba86d6cc` | `8575c9f9c0c453e3acd9797e46d40e6af2244aa526f6b565124d3eef1883f42e` |
| `.state/rollback-production.json` | `sha256:6ec41dcd2f65f9d7ecce6d55c5cb152291f369ac852423e8de8729dfccfb3bec` | `8a946a5b763de59f2eea3f113360f90b579cd8a159a1a89a6a33d9c919d8c867` |

Approval records pin engine `591e191450b8b9084cafccf7f92b23790bae44a1`, config
`cee09c9001937170bcd521b75a43d1f610978f1a`, Bot Warfare
`7b52b462e40fa68287b9e54602e52da83b17766c` and Promod CFG content
`abfa2aac67fb5d43f635d021e544b76d56a1377faf817312987e7a8512ace20e`.
The prepared record is an older five-field identity. Neither becomes release
provenance by renaming/copying an approval. Image digest, protected source ancestry,
full gates and signed immutable release evidence must be established anew.

## Staged adoption

1. Review/merge the focused engine and workspace PRs manually. Preserve engine PR
   ancestry or update its pin after squash. Keep existing evidence and legacy
   images. Do not modify the developer's unrelated engine worktree.
2. Establish the repository/environment/private-package/isolated-runner
   prerequisites in `architecture.md` under separate administrator authorization.
   No new cloud service, monitoring system or Kubernetes component is needed.
3. Run local fixture tests. Run a full isolated release qualification with explicit
   licensed inputs. Fix any real compiler/runtime/security/reproducibility failures
   in reviewed PRs; do not waive gates or manufacture a manifest.
4. Only when separately authorized, manually publish the first RC. Exercise
   attestation resolution, digest pulls and rejection paths locally. No branch merge
   automatically publishes or deploys anything.
5. Separately authorize the first explicit-version homolog rollout. Its immutable
   baseline snapshot can restore the old container configuration/image. Qualify
   actual mode, effective bot behavior, authentication and real-client requirements.
   Record a successful GitHub homolog deployment only after health passes.
6. Manually promote that exact RC to stable using its successful deployment ID.
   Confirm the stable and candidate OCI/config digests and artifact fields match.
7. Separately authorize the supervised production rollout. Confirm baseline
   recovery, private CFG/mount/isolation parity and independent environment history.
8. After qualification, retire one-argument usage in a separate reviewed change.
   Retain approvals, rollback records and image blobs as historical evidence. The
   release path must never import `.state/approved` as authorization.

The temporary backward compatibility is explicit: one argument invokes legacy
master/approval behavior; two arguments always invoke release resolution. Lifecycle
`on/off/status` and the existing one-argument mode-switch command stay unchanged.
Invalid release inputs do not trigger a legacy fallback.

## Interrupted publication

All examples below are operator procedures for a future authorized publication;
none was run for this task. Never delete a draft, tag, private blob or build evidence
as an automatic cleanup/retry. Do not create a replacement artifact under a reserved
version. Keep the entire `.state/releases/candidate.*` directory and workflow logs.

1. Hold the singleton writer. Record the workflow/run, reserved version, full source
   commit, registry reference/digest, manifest hash, draft ID, asset IDs and current
   tag object. Use read-only GitHub/registry inspection first. An API/network error
   is not proof that a ref or release is absent.
2. If no private image was uploaded and no draft/tag exists, re-run gates with the
   recalculated unused version. If an orphan private image exists, preserve it and
   its evidence; a new job must not treat it as a qualified release automatically.
3. If a draft exists, verify its exact original commit, image digest, manifest and
   complete successful gate evidence against the retained build. Verify attached
   asset bytes with GitHub's asset SHA-256. Resume uploading only missing identical
   assets; never use `--clobber`. If a tag exists, it must resolve to that exact commit.
4. If all evidence is complete, an authorized release owner may resume that same
   publication through GitHub, preserving the draft/assets and existing tag. This
   resumes the original transaction; it does not move/recreate/reuse the version.
   Missing or conflicting evidence leaves the draft reserved and undeployable;
   qualify a new version. The automated workflow intentionally refuses duplicates.
5. If publication may already have succeeded, inspect it by exact tag and run
   `gh release verify TAG --repo ghptc/ec2-workspace` and
   `gh release verify-asset TAG release-manifest.json --repo ghptc/ec2-workspace`.
   An immutable complete release needs no republish. A mutable/incomplete release
   remains rejected; escalate to the owner without deleting evidence.

The registry push, ref creation and release publication are separate APIs; the
safety boundary is rejection of anything short of a complete attested immutable
release. Restrict writer access and settings changes to preserve this boundary.

## Interrupted deployment

Preserve the transaction directory, baseline image and `.state/` permissions.
The last event distinguishes validation failure, mutation, rollback, healthy runtime
with missing GitHub evidence, and full completion. `validation-failed`, `rolled-back`
and `complete` are resolved states; other states block another rollout in that
environment. Never clear a journal just to bypass the guard.

After separately authorizing recovery, inspect current runtime identity/configuration
against `candidate.json` and `rollback.json`. A third-party change outside these
identities requires manual review. The recovery entrypoint acquires the deployment
lock, requires production confirmation and refuses an unexpected runtime image:

```bash
./scripts/release-recover.sh homolog .state/deployments/homolog/transaction.EXAMPLE rollback
./scripts/release-recover.sh production .state/deployments/production/transaction.EXAMPLE rollback
# For an already healthy candidate whose GitHub evidence write was interrupted:
./scripts/release-recover.sh homolog .state/deployments/homolog/transaction.EXAMPLE complete
```

`rollback` restores the saved service image/command/private configuration and checks
its old game mode and image ID. `complete` requires the original candidate service
configuration, image, environment health/effective cvars, and a reverified immutable
release before recording/reconciling GitHub evidence. A failed GitHub status write
may leave an incomplete GitHub deployment record; preserve it. Recovery can create
another successful record for the same exact artifact without changing runtime.

A stopped/missing baseline, SSH failure or external Compose drift may prevent this
script from safely recovering; inspect with the owner. Do not delete volumes,
rebuild an image, alter secrets or substitute mutable `master` during recovery.

## Validation performed

- Python fixture suite: 48 tests, including 21 existing mode/runtime tests.
- Existing `bash tests/operations.sh`: all mocked operations/build/rollback checks.
- Bash syntax and ShellCheck for all scripts/tests; `git diff --check`.
- Engine companion: all 4 existing updater tests.
- Local-only evidence inventory and read-only image-presence checks.

The release build, private registry upload, signed release publication, real
homolog/production health, and recovery against a real environment remain
unexecuted. Fixtures exercise policy and real shell control flow with fake
Docker/SSH, not a licensed gameplay or production acceptance claim.
