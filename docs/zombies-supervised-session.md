# Supervised P0 session: operator launches the existing client

Status: preparation only. Do not launch CoD4 from an agent, install/update patches,
edit profiles, enable logging, clear caches, run RCON, attach a debugger, restart
containers or deploy. The operator launches the existing Steam/Proton client
manually and chooses when to connect. Collectors read files/process metadata and
existing `cod4-homolog` logs; their only saved output is explicitly redirected
under ignored `.state/`. Normal client operation may itself write downloads/cache;
these tools make no changes to the client or server.

## 1. Prepare a session before connecting

Use a Bash terminal in `/home/gabriel/Projects/ec2-workspace`:

```bash
umask 077
SESSION="$PWD/.state/zombies-supervised-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$SESSION"
printf '%s\n' "$SESSION"
date -u +%Y-%m-%dT%H:%M:%SZ > "$SESSION/since.utc"
python3 scripts/zombies-diagnostics.py clock > "$SESSION/local-clock.jsonl"
```

Keep this terminal open so `SESSION` stays defined. All subsequent commands are
operator-run; none opens the game. Do not use shell tracing (`set -x`). Do not
copy CFGs, environment variables, command lines, registry files, passwords, RCON
traffic or complete raw console logs into the session or a PR.

## 2. Start existing homolog log observation

In the same terminal, start the collector and leave it running:

```bash
python3 scripts/zombies-diagnostics.py server \
  --since "$(cat "$SESSION/since.utc")" --follow > "$SESSION/server.jsonl"
```

This uses the existing `aws-prod` SSH alias with batch authentication and strict
host-key checking. It runs only remote `date`, narrowly formatted `docker inspect
cod4-homolog` and `docker logs cod4-homolog`. It does not request credentials,
execute RCON or inspect production. Authentication failures stop collection;
do not paste credentials into chat. Ctrl-C stops observation, not the container.
The first records contain a server-clock sample bracketed by local UTC readings,
SSH round-trip duration, container ID, immutable image ID and running state.
Raw server lines are filtered in memory and never saved. This requires existing
Docker logging; no logging policy is changed. Docker timestamps are daemon log
timestamps and can lag the game event if output was buffered.

## 3. Operator launches manually; identify this running client

The operator now opens the existing Steam/Proton CoD4 multiplayer client normally.
Do not apply an update prompt for this baseline. In a second Bash terminal:

```bash
cd /home/gabriel/Projects/ec2-workspace
read -r -p 'Paste the session directory printed in step 1: ' SESSION
pgrep -x iw3mp.exe
read -r -p 'PID of the manually launched iw3mp.exe: ' CLIENT_PID
python3 scripts/zombies-diagnostics.py process --pid "$CLIENT_PID" > "$SESSION/client-modules-before.jsonl"
```

If `/proc/PID/maps` access is denied, record that limitation; do not escalate to
ptrace, dump memory or modify Yama. The snapshot hashes mapped executable/library
files and records PID/start ticks to detect PID reuse. This is a **partial host
mapping inventory**, not a complete Windows loader-module list. Hashes describe
the current on-disk backing paths, not mapped memory; a replaced DLL may differ
from the bytes executing. Repeat it after
connection/loading to catch modules loaded later. No process environment or
command line is read. A window title or Steam app ID alone does not establish
which CoD4x DLL is executing.

In the game's console, the operator enters these **one-token queries**, one per
line. Supply no values and do not use `set`, `exec`, `condump` or `writeconfig`:

```text
version
shortversion
legacyProtocol
fs_basepath
fs_homepath
fs_game
logfile
cl_shownet
cl_showServerCommands
cl_wwwDownload
```

An unknown query is a limitation, not a reason to set another variable. Do not
dump all dvars. `version` plus hashes of actually mapped CoD4x modules are the
build evidence; a patch on disk or updater notice alone is insufficient. Do not
query passwords, identities or authentication tokens. Keep path outputs private.

If the existing `logfile` setting already produces a console log, use the path
reported by `fs_homepath` (or its existing native Steam/Proton filesystem mapping)
to identify the existing `console_mp.log` under its current home/game directory
(possibly a `mods/...` directory rather than `main/`). Do not enable or create a client
log. In the second terminal:

```bash
read -r -p 'Existing native console log path (only if already enabled): ' CLIENT_LOG
python3 scripts/zombies-diagnostics.py checkpoint --file "$CLIENT_LOG" > "$SESSION/client-log-checkpoint.json"
```

The checkpoint stores inode/device/byte offset/mtime and a prefix SHA-256, not
content. Rotation, truncation or prefix rewriting invalidates it and must be
reported; a partial-line continuation at the checkpoint is discarded. The version query occurs
before this checkpoint: preserve its selected output using the filtered stdin
command below, or repeat the one-token `version` query after the checkpoint.
If logging is off, skip both file commands; paste only relevant selected console
output directly into this filter, then press Ctrl-D:

```bash
python3 scripts/zombies-diagnostics.py console > "$SESSION/client-selected.jsonl"
```

The filter retains version/build/protocol, fixed diagnostic events, numeric
sequence/index fields and known BTD filenames/progress. Command bodies, ring text,
URLs, names and credential-bearing lines are omitted. Do not paste raw logs into
chat. Import timestamps are explicitly **not** the original event times.

## 4. Establish cache baseline and optional transport metadata

Use the native existing mod directory selected by the client's `fs_game` and
search paths. Do not rename/delete files to force a fresh download:

```bash
read -r -p 'Existing native BTD mod directory used by this client: ' BTD_DIR
python3 scripts/zombies-diagnostics.py payload --directory "$BTD_DIR" > "$SESSION/payload-before.jsonl"
```

Expected original payload: `mod.ff` 12,033,844 bytes, `btd_images.iwd` 3,070,864,
`btd_music.iwd` 17,789,555, `btd_weapons.iwd` 307,567; total **33,201,830** bytes.
These are original full-file sizes, not necessarily bytes transferred by this
attempt. Other home/base search paths may contain cached copies: check the paths
actually reported by the client. Missing files in one directory alone do not
prove a clean client. Preserve partial downloads and note cache ambiguity.

Optionally obtain the existing host address without collecting SSH credentials:

```bash
SERVER_HOST=$(ssh -G -F "$HOME/.ssh/config" aws-prod 2>/dev/null | awk '$1=="hostname" {print $2; exit}')
SERVER_IP=$(getent ahostsv4 "$SERVER_HOST" | awk 'NR==1 {print $1}')
python3 scripts/zombies-diagnostics.py packet-command --server-ip "$SERVER_IP"
```

That command **prints**, but never runs, a bounded tcpdump command. If the operator
chooses to run the printed command, use a separate terminal and redirect its
metadata stdout into `"$SESSION/transport-metadata.txt"`. It needs local capture
permission. It uses numeric addresses, quiet packet summaries and no payload
dump/pcap. Do not add `-A`, `-X`, `-w` or run RCON while capturing. It observes only
UDP 28962 and TCP 80/443 to the chosen address, for at most 300 seconds; repeat
manually for a longer attempt, documenting gaps. A FastDL redirect to a different
host will not be covered. Do not mistake missing TCP packets for proof of no HTTP.
UDP/TCP packet lengths include protocol overhead and retransmissions; they are
not application payload size or reliable-command sequence evidence.

## 5. Operator reproduces once, with separate timing markers

Immediately before manually connecting to the **existing homolog endpoint**, run:

```bash
python3 scripts/zombies-diagnostics.py mark connect_requested >> "$SESSION/markers.jsonl"
```

The operator then connects through the normal client UI/console. Do not script
input. At each observed boundary, run the corresponding command in terminal 2:

```bash
python3 scripts/zombies-diagnostics.py mark download_started >> "$SESSION/markers.jsonl"
python3 scripts/zombies-diagnostics.py mark download_finished >> "$SESSION/markers.jsonl"
python3 scripts/zombies-diagnostics.py mark loading_started >> "$SESSION/markers.jsonl"
```

Run **only** markers that were actually observed; the three lines above are
separate actions at their respective times, not a block to execute together.
If the exact error appears, preserve it on screen and mark it:

```bash
python3 scripts/zombies-diagnostics.py mark ring_error >> "$SESSION/markers.jsonl"
```

Do not emit that marker for another error. Record per-file displayed byte totals
and progress boundaries if available; note operator reaction-time uncertainty.
If already-enabled diagnostics include the ring dump, the filter records slot
numbers only. `serverCommandNumber` in public 21.8 is a **masked ring index**, not
the full requested sequence. Existing `serverCommand: N:` lines describe CGame
execution requests; they do not prove receipt/generation timestamps. Existing
out-of-range ACK diagnostics can expose server sequence/ACK pairs, but normal
per-command generation and ACK traffic are not logged by default. The commented
server ring dump is not an available console command.

If this attempt joins instead, mark `joined`; record whether actual zombie combat
works without declaring the defect fixed from a cached connection. No client
restart, cache clearing, update or second attempt is automatic.

## 6. Finish observation and collect appended diagnostics

In terminal 2, after the error or observed join:

```bash
python3 scripts/zombies-diagnostics.py process --pid "$CLIENT_PID" > "$SESSION/client-modules-after.jsonl"
python3 scripts/zombies-diagnostics.py payload --directory "$BTD_DIR" > "$SESSION/payload-after.jsonl"
python3 scripts/zombies-diagnostics.py mark session_finished >> "$SESSION/markers.jsonl"
```

If the process exited, the failed snapshot is useful evidence of that limit;
do not relaunch it. When an existing log/checkpoint was available:

```bash
python3 scripts/zombies-diagnostics.py console --file "$CLIENT_LOG" \
  --checkpoint "$SESSION/client-log-checkpoint.json" > "$SESSION/client-appended.jsonl"
```

Stop terminal 1's log follower with Ctrl-C; stop optional capture with Ctrl-C.
Do not stop the server or client through these collectors. Keep the session
directory private. Tell the agent the session directory and observed outcome;
do not relay logs manually or upload assets. The agent can inspect local filtered
artifacts once the operator has completed the reproduction.

## Interpretation and next gates

Correlate remote log timestamps using the clock bracket, then compare operator
markers, numeric sequence evidence and file-size/hash changes. Calculate download
elapsed time separately from connect-to-loading and loading-to-error time.
Report whether transport was observed and whether bytes are file bytes, wire
bytes or only displayed progress. Never divide 33,201,830 by an unrelated elapsed
interval or count cached files as downloaded bytes.

Public source `17182c7` identifies 21.8; the earlier isolated client reported21.1.
This session must establish the actual existing running build. No causal claim
about that difference follows from version numbers alone. Read-only constraints
preclude update/A-B tests. Full command-generation/receipt/ACK/CGame traces may
remain unavailable: report that gap rather than enable logging, attach a debugger
or infer unknown sequences. Any later instrumentation needs separate review and
authorization consistent with these constraints.

After evidence establishes a root cause: implement the smallest correction in
the owning repository, add a behavioral regression that fails before and passes
after, run native/Zombies/Promod/config/container checks appropriate to the change,
obtain independent review and mandatory CI. No merge or deployment is authorized.
A fix remains unqualified until an operator-supervised real client connects and
actual zombie combat/wave progression work. Until then, P0/P1 remain open and mode
switching remains disabled.
