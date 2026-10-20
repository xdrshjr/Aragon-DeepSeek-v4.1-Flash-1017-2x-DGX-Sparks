# Two inference services on the same pair of Sparks

Both services hold about 113 GiB of each Spark's 121 GiB unified memory, so only
one can run at a time. The public API is the same for both: nginx on port 8000
proxies `127.0.0.1:8888`, and its config never changes. A client's `base_url` and
API key stay valid across a switch.

| | DeepSeek-V4-Flash-0731 | DeepSeek-V4.1-Flash-1017 |
| --- | --- | --- |
| Engine | vLLM + DSpark | TensorFold native (Zig) |
| Served model id | `deepseek-v4-flash-0731` | `DeepSeek-V4.1-Flash-1017` |
| Port (internal) | `127.0.0.1:8888` | `127.0.0.1:8888` |
| Unit | `deepseek-v4-flash.service` (enabled) | `dsv41-tensorfold.service` (disabled) |
| Directory | `~/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark` | `~/DeepSeek-v4.1-Flash-1017-2x-DGX-Sparks` |
| Boot default | yes | no |

## Switching

```bash
~/bin/serve v41      # stop v4, wait for memory, start v4.1, wait for HTTP 200
~/bin/serve v4       # stop v4.1, wait for memory, start v4, wait for HTTP 200
~/bin/serve status   # what is up, how much memory is free, which model answers
```

`serve v41` takes minutes on a warm start (it loads ~98 GiB per Spark) and up to
an hour if the weight files still have to be written. Follow either one with:

```bash
journalctl -fu dsv41-tensorfold.service        # v4.1
journalctl -fu deepseek-v4-flash.service       # v4
```

The public endpoint, for both:

```bash
curl -s http://127.0.0.1:8000/v1/models \
  -H "Authorization: Bearer $(sed -n 's/^VLLM_API_KEY=//p' \
      ~/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark/.env.dspark)"
```

v4.1 reuses the v4 API key (pre-created at
`~/.local/state/dsv41-tensorfold/api-key`, mode 600) so no client changes.

## What was set up to make this work

Every file below is in this repository's [`deploy/`](../deploy/) and is placed by
`./deploy/install.sh` (idempotent; starts nothing). The paths and the proxy
address in them are this pair's, not portable defaults.

- `~/bin/serve` — the switch script.
- `/etc/systemd/system/dsv41-tensorfold.service` — v4.1 under systemd, with
  `FOREGROUND=1` so `start.sh` stays attached and its SIGTERM trap runs
  `./stop.sh`. Deliberately **not** enabled: v4 stays the boot default.
- `/etc/sudoers.d/dsv41-switch` — passwordless `systemctl start/stop/reset-failed`
  for exactly those two units, so `serve` is one command. Nothing else.
- `scripts/local.sh` in the v4.1 tree — `WORKER`, `HF_ENDPOINT`, `PORT`,
  `HOST=127.0.0.1`, `API_KEY=1`.
- NFS: the head exports `~/.cache/huggingface` read-only to the worker's two CX7
  addresses (`192.168.200.13`, `192.168.201.13`); the worker reads the checkpoint
  from there instead of holding a second copy.
- `dsv41-download.service` / `dsv41-engram.service` — the two resumable downloads
  (see below); neither is enabled, they are run by hand.

## Installing v4.1 (one window, v4 offline)

```bash
cd ~/DeepSeek-v4.1-Flash-1017-2x-DGX-Sparks
DRY_RUN=1 ./start.sh     # verify wiring; changes nothing
~/bin/prepare-v41        # image (via proxy), then downloads, kit, NFS volume
~/bin/serve v41          # stop v4, wait for memory, start v4.1, wait for 200
```

Use `~/bin/prepare-v41`, not `./scripts/prepare.sh`: GitHub is intermittently
unreachable from this pair (TLS resets), and the wrapper builds the engine image
through the proxy first, with exactly the arguments `prepare.sh` would pass.
`prepare.sh` then finds the image already built (its `tf.patches` label matches)
and does the rest itself. Override the proxy with `PROXY=`.

Both stop a running server when they need the memory. Expect the weight files to
take a couple of hours: rank 0's ~106 GiB is written here, rank 1's ~106 GiB is
written on the worker from this node over NFS.

## Rollback

```bash
~/bin/serve v4
```

If that fails, the v4 service is untouched on disk; finish with:

```bash
sudo systemctl stop dsv41-tensorfold.service
cd ~/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark && ./start-deepseek-v4-flash-dspark.sh
```

Nothing about v4.1 writes into the v4 directory, and the v4 container image,
HF cache directory and `.env.dspark` are untouched.

## Installing: what actually had to be done on this pair

`~/bin/prepare-v41` is not enough on its own here. Three things in
`scripts/prepare.sh` assume a network and a starting state this pair does not
have, and each one blocks the run:

1. **The kernel kit fetch needs the proxy.** `prepare.sh` runs a bare
   `git fetch` from GitHub, which resets the TLS connection here. Pre-place the
   kit at `$HF_CACHE/tensorfold-dsv41/kit-abe07c7d` through the proxy first
   (`git init`, fetch `KIT_REF`, `checkout --detach`); the script then skips the
   fetch. Note the path: it is `$HF_CACHE/tensorfold-dsv41/...`, **not**
   `$HF_CACHE/hub/tensorfold-dsv41/...` — the `hub/` variant is only where the
   model downloads live, and a kit built there is invisible to `prepare.sh`.
2. **The worker needs the base image too.** `prepare.sh` checks the shared
   manifest by running `find` in `$BASE_IMAGE` on the worker, so the worker must
   already hold `nvcr.io/nvidia/pytorch:26.07-py3`. It does not, by default, and
   the check silently becomes a 24 GB pull over this flaky link. Copy it once
   over the CX7 link instead:
   `docker save nvcr.io/nvidia/pytorch:26.07-py3 | ssh aegiston01@192.168.200.13 docker load`
   (98 s). Do **not** add `-n` to that ssh: `docker load` needs the stream.
3. **`tools/validate.py` sends no API key.** It was written for the default
   open server (`API_KEY=0`) and posts without an `Authorization` header, so
   every case fails with `invalid_api_key` against a key-protected server while
   `tools/smoke.py` passes. It now resolves the key the way `tools/client.py`
   does (`API_KEY`, else `API_KEY_FILE`).

Also: starting `dsv41-tensorfold.service` directly makes `start.sh` generate a
**new random** key in `~/.local/state/dsv41-tensorfold/api-key`. To keep clients
unchanged, overwrite that file with the v4 key; the engine rereads it on change,
so no restart is needed. `~/bin/serve v41` does this for you.

## Gotchas found on this pair

- **Xet must stay off.** `hf-mirror.com`'s Xet CAS answers `401` on reconstructing
  the large shards; plain ranged HTTPS from the same mirror sustains ~56 MiB/s.
  `HF_HUB_DISABLE_XET=1` is set in `scripts/local.sh` and in the download unit.
- **`hf download` cannot fetch Engram's tables at all.** They are ~101 GB each, and
  `huggingface_hub` refuses anything that large on its plain HTTP path: it demands
  Xet, which the mirror answers with `401`. `dsv41-engram.service`
  (`~/.local/state/dsv41-tensorfold/engram_download.py`) therefore drives `curl -C -`
  ranged GETs instead, ~49 MiB/s, resuming across interruptions, straight into the
  snapshot directory as real files. `prepare.sh` only checks that they are there at
  the right byte size, so its own failed `hf download` just warns and moves on.
- **DNS breaks under download load.** With the mirror saturating the Wi-Fi link,
  `systemd-resolved` starts timing out, and `docker pull nvcr.io/...` fails with
  `lookup nvcr.io ... i/o timeout`. It resolves fine when the link is idle.
- **`nvcr.io` pulls work anonymously** — no NGC login needed here.
- **CRLF.** The tree was copied from a Windows checkout; every text file had to
  be converted to LF or `./start.sh` fails on `bash\r` and `git apply` rejects the
  patches.
- **`hf` must be on the default PATH.** Ubuntu's `~/.bashrc` returns early for
  non-interactive shells, so the binary is symlinked at `/usr/local/bin/hf`.
- **Memory floor.** `MIN_AVAIL_GIB=112`: a rank that takes all of a Spark's memory
  freezes the machine instead of failing.
