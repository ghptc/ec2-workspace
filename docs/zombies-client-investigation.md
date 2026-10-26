# Zombies client investigation — 2026-10-26

The mission remains open. No reliable-command correction or successful graphical
gameplay is established by the results below. No homolog or production deployment
was performed. RCON activation remains disabled; see the independent
[mode-switch review](zombies-mode-review.md) and [requirements matrix](zombies-mission.md).

## Payload and transport baseline

Measured the original prepared server payload against the previously installed
client payload. All four SHA-256 hashes match the original locked assets:

| File | Bytes |
| --- | ---: |
| `mod.ff` | 12,033,844 |
| `btd_weapons.iwd` | 307,567 |
| `btd_music.iwd` | 17,789,555 |
| `btd_images.iwd` | 3,070,864 |
| Total | 33,201,830 |

Canonical shared configuration enables downloads and disables HTTP redirects
(`sv_allowDownload=1`, `sv_wwwDownload=0`). This is configuration evidence, not a
capture of the transport used in the reported remote incident. The music package
accounts for more than half the payload. Neither fact establishes a causal link
between download duration and reliable-command cycling. Actual elapsed clean-client
transfer time and throughput remain unmeasured.

Private audit: `.state/zombies-payload-audit.json`. Previously installed matching
client assets do not prove that a clean download works. Original files were not
modified, decompiled or published.

## Fresh local behavioral baseline

| Check | Result | Qualification limit |
| --- | --- | --- |
| Workspace operations | 22 Python tests plus complete shell deployment mocks passed | Exact-image promotion, mode identity, mount retention and ordinary rollback are mocked; no live transition or crash recovery proof. |
| BTD disposable native process | 53/53 checks passed, including 15 supported maps, restart, canonical precedence, purity and eight headers | Startup and administrative behavior; no zombie combat or graphical connection proof. |
| Promod disposable native process | 53/53 checks passed, including 21 maps, admission, Ready Up, voting, rotation and restart | Uses test-only plugin/synthetic fixtures; no graphical match proof. |
| Native `change_mode` preflight harness | One test passed | Mock command context; no authenticated host bridge or live transition. |

Private native logs/results are under `.state/zombies-mission-qualification/`.
The executed engine binary SHA-256 is
`7246c1b8d26bcd509160eaf12627e6299072af1655af16005710272b6a0df8e3`.
The sibling engine checkout is feature revision
`57f65e5fb38762c5a6b0d647107c16dc0cdc87b4`, and the configuration checkout is
`a7a13e822074fcb789b4df78cd961199a3995d47` at inspection. These baseline tests do **not** certify a final
protected-master-derived image. Preparation manifests carry different historical
binary hashes; the hash above identifies the binary actually executed.

No coverage percentage was measured. Critical paths still uncovered include
clean-client download/reconnect, reliable-command retention through loading,
real combat/waves/multiplayer/completion, authenticated switching, actual
cross-mode rollback and crash recovery.

## Real-client reproduction suspended by operator

Steam AppId 7940 and Proton Experimental are available on the Arch Linux host.
Created an isolated game/profile/Proton prefix and disposable loopback Zombies
server on port 28979 under `.state/client-p0/`; the existing user profile and
running services are not test targets. Installed CoD4x patches identify client
21.1, with a 21.2 update notice; no update was applied. This version difference is
an observation, not a compatibility diagnosis.

The isolated client initialized but exited before a verified connection attempt;
the reliable-command error was not reproduced. Startup UI/rendering and input
targeting remain unresolved. A black window capture or a live Proton process is
insufficient connection evidence. The operator subsequently instructed the agents
to stop opening CoD4 MP and continue other work. No further graphical launches or
inputs are authorized by this investigation. Preserve the baseline and obtain
real reproduction evidence before any protocol correction.
