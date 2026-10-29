# deploy-notes — this pair's upgrades, and the two traps in them

A record of what it took to move this pair onto the merged tree on 2026-10-29.
Like [`deploy/`](../deploy/), it is one working deployment, not a portable
procedure: the addresses, paths and image tags below are this pair's.

## The pair

| | head | worker |
| --- | --- | --- |
| Host | `spark-57ad` | `spark-49c1` |
| ssh | `spark02` → `aegiston02@192.168.1.252` | `aegiston01@192.168.200.13` |
| CX7 rail | `192.168.200.12` / `192.168.201.12` | `192.168.200.13` / `192.168.201.13` |
| GPU | GB10, aarch64, driver 580.173.02 | the same |

Rails `enp1s0f0np0` (192.168.200.0/24) and `enP2p1s0f0np0` (192.168.201.0/24)
both reach the peer at MTU 9000; the `f1` twins are unused and read `DOWN`.
`scripts/local.sh` on the head holds this pair's values:

```bash
WORKER=aegiston01@192.168.200.13
export HF_ENDPOINT=https://hf-mirror.com
PORT=8888
HOST=127.0.0.1
API_KEY=1
CONTEXT=640000
PARALLEL=2
export MODEL_REVISION=6d54be4fca338d79b17c3b03cc9a423bb3ac6718
```

`HOST=127.0.0.1` keeps the API off the network: reach it through an ssh tunnel,
not by binding `0.0.0.0`. `API_KEY=1` means every request needs
`Authorization: Bearer $(cat ~/.local/state/dsv41-tensorfold/api-key)`; `/health`
stays open.

## Why `MODEL_REVISION` is pinned to `6d54be4f`

The repository's default moved to EAQ v1 `45ee5d0f` because `6d54be4f` was
removed from the Hub (the README says so under "Quick start"). This pair still
holds the `6d54be4f` snapshot and both ranks' weight files, and **everything on
disk is keyed by that revision**:

- the 187 GiB checkpoint snapshot (`~/.cache/huggingface/hub/models--Mia-AiLab--…/snapshots/6d54be4f…`)
- rank 0's weight file (head, `tensorfold-dsv41/6d54be4f/…`) and rank 1's (worker, `rank-cache-6d54be4f/`, 99 GiB each)
- the docker volume the worker reads over NFS, and `TF_DS_RANK_CACHE` in rank 0's environment

Taking the new default would therefore mean a 196 GiB download plus two ~106 GB
weight files, hours of work for no change in what the pair serves. Pinning the
revision instead makes `scripts/prepare.sh` skip all of it — `DRY_RUN=1` proves
it before anything is stopped:

```
[start.sh] Ready: tensorfold-dsv41:exl3-tp2-8e32557ada53,
           Mia-AiLab/DeepSeek-V4.1-Flash-1017-EXL3-EAQ-v1-2.9-bpw @ 6d54be4f,
           Engram's tables, the weight files and the kit
```

The cost of the pin: `6d54be4f` no longer resolves on the Hub, so this pair
cannot re-download the checkpoint it serves. Back the snapshot up if that
matters — a lost snapshot cannot be fetched again at this revision.

## The upgrade that was run

The tree went from a copy of the pre-merge recipe to commit `35ec46e` (the
upstream 53 commits plus `deploy/`), which changed the engine patch series from
four patches to thirty (plus two for the inputs' tools):

| Image | Tree | Notes |
| --- | --- | --- |
| `tensorfold-dsv41:exl3-tp2-7c9bf5d36350` | before | four engine patches (`0001`, `0002`, `0003`, `0004`), no inputs patches; kept for rollback |
| `tensorfold-dsv41:exl3-tp2-8e32557ada53` | `35ec46e` | 30 engine + 2 inputs patches, now serving |

What the new tree brings that this pair now runs:

- `0033` / `GRAPH_CAP=128` — the CUDA graph cache evicts the least recently
  replayed graph instead of growing until memguard kills rank 0 (issue #69)
- `0023` — a prompt's render and tokenization scratch is given back instead of
  held for the whole reply, which is what made long conversations climb
- `0027`, `0028`, `0029`-`0032` — tool-call prose as content, request text never
  becoming control tokens, and the Anthropic frontend's lenient `budget_tokens`,
  `clear_thinking` and `system` placement
- `0005` / `TF_DS_PREFILL_INTERLEAVE_MS=250` — a long cold prompt no longer
  freezes a decoding stream for its whole duration
- `0010` — the RDMA gather proxy naps when idle instead of spinning a core
- log rotation (`--log-opt max-size=100m --log-opt max-file=3`)

Verified after the restart: `/health` ok, `/v1/models` lists
`DeepSeek-V4.1-Flash-1017`, a completion answers with `exact_mode: exact`, and
both containers carry `TF_DS_GRAPH_CAP=128` (`--graph-cap 128` on rank 1).

Build note: the `docker build` step that fetches the inputs repository failed
once with `curl 56 Recv failure: Connection timed out` after 799 s. A plain
retry reused every earlier layer — the Zig compiles are the expensive part — and
finished in 7m33s. Expect to retry that step on this network.

## Trap 1: building the image next to a running server gets the server killed

`scripts/memguard.sh` watches `MemAvailable` and kills the rank when it drops
under `MEMGUARD_GIB`. On 2026-10-29 a `docker build` (three `zig` processes,
`-j$(nproc)`) ran while the pair was serving, and rank 0 was killed under it:

```
2026-10-29 10:23:40 memguard: MemAvailable 3709 MiB was under the 4 GiB floor: killed container dsv41-1017-exl3-tf
     RSS     PID COMMAND
 2719828 3197484 tensorfold-nati
  474372    4833 gnome-shell
  407092 2545575 zig
  349080 2545564 zig
  296456 2545569 zig
```

Rank 0 exited 137 (SIGKILL); rank 1 followed with exit 1 within seconds, as it
must — a rank that loses its peer waits forever. The pair was down ~30 minutes
and the 8-day container log survived only as the tail `stop.sh` saves.

This is not a one-off: `memguard.log` holds the same kill from 2026-10-20
(`3879 MiB was under the 4 GiB floor`). Both times the margin was a few hundred
MiB, because a loaded pair leaves 6-8 GiB available and a Zig build takes 1-2.

The floor itself is what changed in this upgrade, and it is the reason this
should stop happening. The old image killed at once under 4 GiB; `35ec46e`'s
`start.sh` announces its guard as:

```
Memory guard on: each rank's container is killed when the memory available stays
under 2.5 GiB for 4 s, or falls under 1 GiB
```

so a dip that recovers is logged rather than killed. Do not rely on that alone,
though. Build with the pair stopped, or accept that the build may take the
service down:

```bash
./stop.sh                                  # frees ~113 GiB a rank
./start.sh                                 # prepares (builds if the tree changed) and starts
```

Building first and starting afterwards is what the 2026-10-29 run ended up
doing, and it is the sequence to copy.

## Trap 2: a killed rank leaves the start lock held

`start.sh` takes a lock with `exec 8>"$STATE_DIR/start.lock"` and `flock -n 8`.
The descriptor is inherited by the `memguard.sh` child it starts, so when
memguard kills the *container* the `start.sh` parent can stay alive holding the
lock with nothing left to supervise. The next start then refuses:

```
[start.sh] ERROR: another ./start.sh is already running; wait for it to finish
```

On this pair that 8-day-old `start.sh` (PID 2572735) was still holding the lock
long after both containers had died. Find the holder, confirm no container is
running, and end only that process:

```bash
fuser -v ~/.local/state/dsv41-tensorfold/start.lock   # who holds it
pgrep -a -f 'start[.]sh'
docker ps -a                                          # Exited (137) / Exited (1): nothing to lose
kill -TERM <pid-of-that-start.sh>
./stop.sh                                             # saves the logs, removes the containers
./start.sh
```

Do not delete `start.lock`: the lock is the `flock` on the descriptor, not the
file, so removing it frees nothing and a second start would then run beside the
first.

## Rollback

Both images are on both Sparks (`prepare.sh` keeps them identical), so a rollback
is one variable and no preparation:

```bash
IMAGE=tensorfold-dsv41:exl3-tp2-7c9bf5d36350 PREPARE=0 ./start.sh restart
```

`PREPARE=0` is what makes it safe: it keeps `prepare.sh` from re-preparing for
the current tree. Note the old image's memguard is the 4 GiB one, so the trap
above applies again once you are back on it.

The pre-upgrade tree is still on the head at `~/dsv41-oldrepo-20261029-101451`
and the previous `scripts/local.sh` at `~/local.sh.bak-20261029-101617`; the
live tree at `~/DeepSeek-v4.1-Flash-1017-2x-DGX-Sparks` is now a git clone of
`35ec46e`, so `git log` and `git diff` work on it.

## What to watch after the upgrade

- `MemAvailable` on both Sparks over days, not minutes. The reason for the
  upgrade was a graph cache that grew without bound; the post-load reading at
  2026-10-29 was 7.3 GiB on the head and 8.5 GiB on the worker. A steady fall
  from there means something else grows — try `GRAPH_CAP=64` before assuming
  `0033` is not working.
- `docker logs` size: rotation caps a rank at `100m x 3`, so a monitoring poll
  that used to add ~265k lines a day can no longer fill the disk.
- Whether a long cold prompt still starves a decoding stream now that
  `TF_DS_PREFILL_INTERLEAVE_MS=250` is on. Before, the waiting stream got no
  token for ~90 s.
