# Zombies ammo recurrence finalization — 2026-10-28

The preserved incident is `.state/incidents/ammo-recurrence-20261028/` in
`ec2-workspace`. Its patches are the source of this change; original evidence
and candidate archives remain untouched. Final Principal Reviewer is the owner.
Historical review is evidence only, not approval of these final PR revisions.

Normal Zombies preparation previously omitted the ammo safety override unless
`--allies` was selected. The existing correction is now generated unconditionally:
initialize undefined first-use eligibility to true, preserve a defined false
cooldown, and cancel both delayed callbacks on disconnect. Vendor grants,
health caps and timings remain unchanged. Allies remain explicitly optional.

The original `mod.ff` remains byte-identical, SHA-256
`50911fdd0273b50e26983723619881acfaed4aa65f4d91a799a341464c2224a6`.
Pinned ammo source SHA-256 is
`545021b1444b643d270db77fad21767368b94c439a560dd739ed6de6d321b7ad`.
Mandatory `btd_general/_ammo_drops.gsx` SHA-256 is
`2b06adeb720eb54320313d0ab85b1e08bfe61baca79da8c413097e93617b2bb0`.
The updated dependency lock SHA-256 is
`dd4b03f81b082e0570f67fb57040cf95a5bfc929e23831ab16ad03f0a5e202f9`.
`src/scr_vm_main.c` tries GSX before GSC. The native ammo regression uses
`--artifact-ammo` to retain packaged override bytes, exercising that precedence.
Companion workspace packaging requires the source and reviewed output hash,
including for non-allied builds, and rejects absent, altered or symlinked code.

Finalization is based on engine master
`b59eb898a9400425d81a61d2db57e1c826b9f6ed` and workspace master `512e1cb`.
Native tests use that preserved engine binary, SHA-256
`65972a1014a76e0e20c7288a50312c8554cb75463674c4ca3f01039e22644390`,
and exact configuration `4296d214070056eed28c5f923b989bbdd6c7ecef` recovered
from packaged files and verified against all three recorded source hashes.
No engine binary source or security policy changes are part of this fix.

Fresh validation:

- Engine suite: 90 tests, one optional public-client source test skipped.
- Workspace suite: 75 tests and complete mocked Operations suite passed.
- Fresh private preparation and packaging pass with and without allies;
  both produce the exact ammo override above and retain eight headers.
- All 25 declared files in the extracted preserved candidate match their hashes.
- Native packaged ammo: 15 assertions, process and UDP remain healthy;
  `/tmp/btd-death-regression-1t3hxcid`.
- Native lifecycle: respawn, zombie spawning, waves, two UDP admissions and map
  transitions pass; `/tmp/btd-death-regression-x91phq4e`.
- Native expression, death and classic camping checks pass;
  `/tmp/btd-death-regression-ety4jf7e`, `/tmp/btd-death-regression-3yaggqzl`,
  `/tmp/btd-death-regression-8aqy2o2k`.
- Killhouse navigation: 12 checks pass; `/tmp/btd-navigation-dwo6jlbg`.
- Allied native gameplay: all 52 checks pass (native fire/hits, melee, waves,
  human admission/reconnect, map transitions and restart);
  `/tmp/btd-five-allies-b4l5cuw8`.
- Full Zombies startup/integration: 73 checks, 16 maps and restart pass;
  `/tmp/cod4-btd-qualified-9optyvv4`.

Native fixtures use synthetic clients, inject disposable startup logic and
shorten fixture cooldowns. They do not qualify real human multiplayer.
Licensed assets, generated derivatives, binaries and full logs stay outside Git.

Require final owner Principal review of both exact PR heads, mandatory green CI
and operator-approved manual merges. Only after both merges prepare a **new**
immutable local homologation image from exact approved engine/workspace/config
revisions, record all identities/hashes and obtain fresh artifact review. Do not
reuse any old image or approval record. Do not deploy automatically.

A separately authorized homologation session must first capture its current
image/config/mounts and select an independently healthy rollback artifact. With
at least two human graphical clients validate concurrent real vendor-drop
pickups, repeated/cross-drop pickups, full/depleted ammo, death before first
pickup, respawn, disconnect/reconnect during cooldown, waves and map changes.
Record actual ammo/health changes, effective GSX hash/precedence, clean script
logs and sustained UDP health. Production promotion requires separate approval
of that exact image and gameplay evidence. The vulnerable Zombies image is
never an acceptable rollback target; reverting source reintroduces the defect.
