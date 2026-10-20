# deploy/ — what running this recipe on a real pair added

The recipe's own `start.sh` / `stop.sh` / `scripts/prepare.sh` serve one model.
These files are what it took to run **two** models on the same pair of Sparks —
DeepSeek-V4-Flash-0731 (vLLM + DSpark) and this recipe's
DeepSeek-V4.1-Flash-1017 — and to get through four network problems that the
scripts assume away.

They are a record of one working deployment, not a portable product: paths,
unit names and one proxy address are this pair's.

```bash
./deploy/install.sh --dry-run     # print what it would place
./deploy/install.sh               # place it; starts nothing
```

| File | What it is |
| --- | --- |
| `bin/serve` | `serve status\|v41\|v4`: stop one, wait for memory, start the other, wait for HTTP 200 |
| `bin/prepare-v41` | builds the engine image through a proxy, then hands over to `scripts/prepare.sh` |
| `state/download.py` | resumable checkpoint + Engram download (`hf download`, Xet off) |
| `state/engram_download.py` | the Engram tables by `curl -C -`, because `hf download` refuses 101 GB files |
| `systemd/dsv41-tensorfold.service` | this recipe under systemd (`FOREGROUND=1`), deliberately not enabled |
| `systemd/dsv41-download.service` | the checkpoint download, as a oneshot |
| `systemd/dsv41-engram.service` | the Engram download, as a oneshot |
| `sudoers/dsv41-switch` | passwordless `start`/`stop`/`reset-failed` for those two serving units only |

The runbook, including every failure this pair hit and why, is
[`../docs/serve-two-models.md`](../docs/serve-two-models.md).

## Why `serve` exists at all

Each service holds ~113 GiB of a Spark's 121 GiB unified memory, so they cannot
both run: `MIN_AVAIL_GIB=112` is the weights plus the engine's reserve. A rank
that takes all of the memory does not fail cleanly, it freezes the machine.
`serve` therefore stops one before starting the other, and refuses to start
until both Sparks report enough free memory.

Both listen on `127.0.0.1:8888`, behind an nginx on `:8000` that is never
touched, so a client's `base_url` and API key survive a switch. The one thing to
watch: `start.sh` with `API_KEY=1` **generates a new random key** when
`~/.local/state/dsv41-tensorfold/api-key` is missing, which would silently break
clients. `serve` writes the existing v4 key into that file before starting; the
engine rereads it on change, so no restart is involved. If you start the unit by
hand instead, do that yourself.
