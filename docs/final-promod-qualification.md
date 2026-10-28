# Final Promod feature qualification and freeze

Candidate only. No homologation/production deployment or RCON mode bridge
activation is authorized by preparing this change. Preserve Promod and Zombies.

The catalog owns military `botnames.txt`; packaging validates safe unique ASCII
names, fingerprints it and copies it to root `scriptdata/botnames.txt`, matching
the existing Bot Warfare convention. The engine reads persistent home first and
artifact basepath second, as that convention already does. Qualification must
record the effective pool and identify any stale private-home pool before any
operator-approved deployment; packaging never edits persistent environments. Engine creation assigns names; packaging
never renames players. Objective activation requires the engine manifest's S&D
flag and matching hashes for both the derived AI and native defuse-reference
overlay. Native ownership, interaction timers and outcome callbacks stay intact.

Before merge: independent Principal architecture/security approval, required CI
on exact PR heads, native pickup/plant/defuse/state/timer/interruption evidence,
death/drop/round resets, names across rounds and admissions, bot administration,
Promod/Zombies/security regressions, supported S&D map matrix. Engine fixture
positioning is interaction evidence only. Unopposed AI navigation is not combat
or real-client certification. The historical map loading/waypoint coverage does
not establish bomb-objective reachability on all maps.

After approved manual merges, prepare exactly one focused homologation artifact
from pinned engine/config/workspace revisions using the existing preparation
path. Preserve the prior artifact/configuration and record exact dependency,
binary, overlay, name-pool and eight-header identities. Obtain explicit operator
approval before deploying to homologation. Supervise a real client through human
bomb ownership, pickup/drop, native uninterrupted and interrupted plant/defuse,
bot death, round transitions, every supported map, administrative commands and
Zombies regression. Record elapsed timers, native states and gameplay/demo
observations without publishing proprietary assets or full runtime logs.

Qualify exact-artifact rollback using existing protections. Only after gameplay,
rollback and independent approvals pass propose production promotion. Never
merge, deploy or promote automatically. If any gate fails, retain the candidate
and evidence for correction; do not certify completion. Roll back the three
focused PRs together to the previous reviewed artifact, with no data migration.

This is the final approved feature. Return all three repositories to feature
freeze after focused delivery; operational qualification does not authorize
additional features, framework changes, CI/deployment redesign or bridge use.

Current development status: feature freeze, with only focused qualification and
remediation of this final candidate permitted. This does not authorize merges,
service changes, bridge activation or deployment.
