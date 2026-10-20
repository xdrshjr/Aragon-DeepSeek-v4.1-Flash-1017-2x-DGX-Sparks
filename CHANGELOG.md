# Changelog

## Unreleased

- First version: DeepSeek-V4.1-Flash-1017 EXL3 2.9 bpw on two DGX
  Sparks, TensorFold's native Zig engine with BertholomusAI's `dsv41` family (`deepseek-v41-zig` @ `3ff3b2ac`), their kit
  (`abe07c7`) and their weight-file tool (`deepseek-v41-zig-tp4` @ `5940208`). Scripts adapted from the GLM-5.3-Flash
  recipe. Not served yet: see the README's Status.
- From the GLM-5.3-Flash recipe: the node and NFS helpers, `stop.sh`, the start banner, the layered settings,
  `scripts/zig_flags.py` (run by `start.sh` against the image's `capabilities --json` before anything is stopped),
  `scripts/publish-image.sh` and the registry pull, the API checks in `tools/` (`toolcheck.py`, `needle.py`,
  `end_of_turn.py`, `anthropiccheck.py`), the Hermes Agent page and the `.github` templates. Not ported, because they read
  the GLM Python engine's `/health` counters or its prompt cache, patches or settings: `tools/hermes_benchmark.py`,
  the pool, kept-state, display-KV and CPU/GPU tests, the spill tier, `SHARED_PREFIX`, the three and four Spark scripts,
  and the Ablit weights. (`tools/prompt_reuse.py` is ported since, with its cached-token lookup adapted.)
- `stop.sh` counts running requests from the native server's `/health` (`live.connections`).
- Served and measured on one pair of Sparks (README, Status). With sparkDash's real prompts:
  prefill ~2,140-2,180 tok/s from 8K to 64K prompts (2,000 at 256K), decode 74.9 tok/s (prose) and 109.9 tok/s
  (code) for one stream, 130.0 and 155.5 tok/s for four. `tools/bench.py`'s random-word prompts give less decode (55-61 tok/s, 113-117 for four): the drafter
  cannot predict them.
- Both GPUs must share one clock ceiling: a Spark locked at 1,800 MHz against 2,200 MHz on the other cost ~3-6% of prefill
  and ~3% of decode (TP=2 meets twice a layer, so the slower GPU sets the pace).
- Rank 0 reads Engram's tables from local disk (`HEAD_ENGRAM_DIR`): over NFS a random read took ~940 us against ~90 us
  locally, and prefill was ~690-890 tok/s instead of ~1,500-2,000.
- Memory safety: `scripts/memguard.sh` (kills a rank's container under `MEMGUARD_GIB`), the `MIN_AVAIL_GIB` preflight, setup
  stops a running server before it builds or downloads, and `HEAD_ENGRAM_DIR` is checked (both shards, exact sizes) before
  anything starts.
- `HEAD_NFS_SERVER` / `HEAD_NFS_VOLUME`: rank 0 reads the checkpoint over NFS through a docker volume (sshfs does not work:
  it lists files as type "unknown" and the engine skips them).
- `API_KEY=1`: an opt-in API key (off by default; the API is open on the network otherwise).
- `tools/bench.py`, `tools/smoke.py` and `tools/prompt_reuse.py`.
- Engine patches in `zig/patches/` (off by default; bit-identical to the unpatched image on 31 of 31 prompts): prompt-cache placement
  (`TF_DS_CACHE_PLACEMENT=1`, **on**: a resumed turn no longer misses the cache because another conversation's kept rows were in
  the way), a second Engram AIO ring (`TF_DS_ENGRAM_LANES=2`, off: 1.5-2.6% slower) and a prefill indexer row split
  (`TF_DS_IDX_SPLIT=1`, off: no measurable gain). `tools/exact.py` records and compares replies.
- `zig/patches/0004-call-gate.patch`: the engine enforces `tool_choice` `"required"` and a named function (taken from the spark1/spark2
  deployment's copy; built into the running image `exl3-tp2-7c9bf5d36350`: required, named, streaming and thinking-on requests
  return valid tool calls, auto/none/absent are unchanged).
- `RANK1_PROFILE` (rank 1 `--profile`); both GPUs must share one clock ceiling; each Spark can run from a local copy of the
  cache (no NFS), with `PREPARE=0`.
- **First deployment of the whole recipe on a real pair** (two GB10 Sparks, a head that also carries ~6 GiB of
  desktop, workers reached over their CX7 links). Everything below came out of that run; the runbook is
  `docs/serve-two-models.md` and the files are in `deploy/`.
- `tools/validate.py` now sends the API key: it posted without an `Authorization` header, so against a server
  started with `API_KEY=1` every case failed with `invalid_api_key` while `tools/smoke.py` passed. It resolves
  the key the way `tools/client.py` does (`API_KEY`, else `API_KEY_FILE`).
- Xet has to be off on this network: `hf-mirror.com`'s CAS bridge answers `401` on reconstructing the large
  shards, while plain ranged HTTPS from the same mirror sustains ~56 MiB/s. `HF_HUB_DISABLE_XET=1`.
- `hf download` cannot fetch Engram's tables at all: at ~101 GB each `huggingface_hub` refuses them on its
  plain HTTP path and demands the Xet path that is broken here. `deploy/state/engram_download.py` drives
  `curl -C -` ranged GETs instead (~49 MiB/s, resumable) straight into the snapshot directory.
- `scripts/prepare.sh` needs two things this pair does not have by default. Its kit fetch is a bare
  `git fetch` from GitHub, which resets the TLS connection here, so the kit has to be pre-placed at
  `$HF_CACHE/tensorfold-dsv41/kit-<KIT_REF>` (note: not under `hub/`) through a proxy. And its NFS manifest
  check runs `find` in `$BASE_IMAGE` **on the worker**, so the worker must already carry
  `nvcr.io/nvidia/pytorch:26.07-py3` or the check silently becomes a 24 GB pull over the same flaky link.
  `deploy/bin/prepare-v41` builds the image through a proxy with exactly `prepare.sh`'s arguments, and
  `docker save | ssh <worker> docker load` moves the base image across the CX7 link in ~98 s.
- `start.sh` with `API_KEY=1` generates a **new random** key when `~/.local/state/dsv41-tensorfold/api-key`
  is missing. Starting the unit by hand therefore changes the key clients must send; `deploy/bin/serve`
  writes the key you name into that file first (the engine rereads it, so no restart).
- `deploy/bin/serve`: these two models cannot coexist (each rank holds ~113 GiB of a Spark's 121 GiB, and a
  rank that takes all of it freezes the machine), so switching is stop-one/start-the-other behind the same
  `:8000` entry point. Both services keep `127.0.0.1:8888`, so nginx and the client's `base_url` never change.
- Copied trees from a Windows checkout carry CRLF: `./start.sh` then fails on `bash\r` and `git apply`
  rejects every patch in `zig/patches/`.
