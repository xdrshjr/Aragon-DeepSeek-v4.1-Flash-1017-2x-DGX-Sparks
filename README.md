<h1 align="center">DeepSeek-V4.1-Flash-1017 EXL3 on 2x DGX Sparks with TensorFold</h1>

<p align="center">
  <sub>by <a href="https://x.com/MiaAI_lab">Mia's AI Lab</a></sub>
  <br><br>
  <a href="https://github.com/sponsors/MiaAI-Lab" target="_blank" rel="noopener noreferrer" style="display:inline-block;margin:0 8px;vertical-align:middle;"><img src="https://img.shields.io/badge/Sponsor%20me%20on%20GitHub-181717?style=for-the-badge&logo=githubsponsors&logoColor=white" alt="Sponsor me on GitHub" height="28" style="height:28px;width:auto;vertical-align:middle;border:0;" /></a>
  <a href="https://x.com/MiaAI_lab" target="_blank" rel="noopener noreferrer" style="display:inline-block;margin:0 8px;vertical-align:middle;"><img src="https://img.shields.io/badge/Follow%20me%20on%20X-000000?style=for-the-badge&logo=x&logoColor=white" alt="Follow Mia on X" height="28" style="height:28px;width:auto;vertical-align:middle;border:0;" /></a>
</p>

Serve **DeepSeek-V4.1-Flash-1017** from two NVIDIA DGX Sparks (GB10, 128 GB each, linked by their ConnectX-7 ports)
through an OpenAI-compatible API, with the full **1,048,576-token window**, **image input**, tool calling, thinking on
or off, and **DSpark** speculative decoding from the checkpoint's own draft blocks, using
[TensorFold](https://github.com/ashhart/TensorFold)'s native Zig engine and the 2.9 bit EXL3 quantization
[`Mia-AiLab/DeepSeek-V4.1-Flash-1017-EXL3-EAQ-v1-2.9-bpw`](https://huggingface.co/Mia-AiLab/DeepSeek-V4.1-Flash-1017-EXL3-EAQ-v1-2.9-bpw)
(196 GiB; experimental: its model card has no perplexity or KL measurement against the unquantized model).

- Checkpoint: `Mia-AiLab/DeepSeek-V4.1-Flash-1017-EXL3-EAQ-v1-2.9-bpw` (39 shards, routed experts at 3 bits a
  weight, 2 bits in layers 18-22, attention at 5, shared experts at 4-5, head at 6, DSpark blocks at 4; the vision tower
  and the DSpark blocks are in it; the revision is pinned in `scripts/config.sh`), plus Engram's two tables, unquantized,
  from `deepseek-ai/DeepSeek-V4.1-Flash-1017` @ `1bae0e10` (shards 47 and 48, ~203 GB; the quantization leaves them out)
- API model id: `DeepSeek-V4.1-Flash-1017`, port 8888
- Engine: TensorFold native (Zig 0.17.0), BertholomusAI's `dsv41` family at TP=2, one rank on each Spark
- One command on the first Spark: `./start.sh` sets up both Sparks and starts both ranks; `./stop.sh` stops them

## Start the model you want

This pair serves **one model at a time**: a rank holds ~113 GiB of a Spark's 121 GiB unified memory, and a rank that takes
all of it does not fail cleanly, it freezes the machine. Switching therefore means stopping one service and starting the
other. Both sit behind the same endpoint, so a client only changes the model id it sends.

| Serve | Run | Model id the client sends |
| --- | --- | --- |
| **DeepSeek-V4.1-Flash-1017** (this recipe) | `serve v41` | `DeepSeek-V4.1-Flash-1017` |
| **DeepSeek-V4-Flash-0731** (vLLM + DSpark) | `serve v4` | `deepseek-v4-flash-0731` |
| Whatever is up, to see the state | `serve status` | — |

```bash
serve v41        # stop what holds the memory, wait for free memory on both Sparks, start, wait for HTTP 200
serve v4         # the same, the other way round
serve status     # what is up, how much memory is free, which model answers
```

`serve` waits for both Sparks before it starts anything, so it is safe to run when a switch was interrupted. A warm start
takes minutes (~98 GiB of weights per Spark); the first start on a fresh pair also writes the weight files and takes hours.

`serve` and the units it drives live in [`deploy/`](deploy/) and are placed by `./deploy/install.sh` (Quick start, step 5).
It is written for a pair that runs **both** of these services: it also drives the other one's systemd unit and reads its
API key. On a pair that serves only this model, use `./start.sh` and `./stop.sh` instead — they are the recipe's own entry
points, and everything above is a thin layer on top of them.

## Status

What is checked, and how:

- `DRY_RUN=1 ./start.sh` prints the link it found (on a pair of Sparks) and both ranks' docker commands; `./stop.sh`
  and `scripts/*.sh` pass `bash -n`.
- The kit's RoPE tables, made from this checkpoint's `config.json`, match the kit's recorded sha256 (4 of 4), and the
  token map made from its `tokenizer.json` is byte for byte the one the kit's Engram fixtures were recorded with.
  `scripts/prepare.sh` checks both on every run. The checkpoint holds all 43 `gate.bias_vl` tensors (F32) the image
  routing bias is made from.
- `zig/Dockerfile` builds (`tensorfold-dsv41:exl3-tp2-136c93b359b4`, 24.9 GB, about 6 minutes of Zig compiling on a
  Spark): `tensorfold-native 1.0.2`, `tf-dsv41-lanes`, `tf-dsv41-rank-cache` and the three inputs' scripts are in it.
- `tf-dsv41-rank-cache` plans the TP=2 split: run on a copy of the real headers (tensor bytes left out) of an earlier 43-shard
  2.9 bpw EXL3 checkpoint with the same tensor widths, it gives each rank 143,770 entries and 98.9 GiB, the ~98 GiB a
  Spark the weights need. (Not re-run on the 39-shard checkpoint.)

Served and measured on one pair of Sparks (the head also runs a desktop and ~18 small containers; the worker is otherwise
idle). Two sets of numbers, from two tools:

**[sparkDash](https://github.com/MiaAI-Lab/sparkDash)** (real prose and code prompts, as sparkDash reported them, with the
server at `CONTEXT=524288`, up to 4 streams, drafts on):

| Decode, tok/s | 1 stream | 2 streams | 4 streams |
| --- | --- | --- | --- |
| Prose | 74.9 (TTFT 131 ms) | 105.5 total, 55.0 each (TTFT 243 ms) | 130.0 total, 34.9 each (TTFT 411 ms) |
| Code | 109.9 (TTFT 200 ms) | 139.8 total, 74.8 each (TTFT 291 ms) | 155.5 total, 44.4 each (TTFT 511 ms) |

| Prefill, prompt tokens | 8K | 16K | 32K | 64K | 128K | 256K |
| --- | --- | --- | --- | --- | --- | --- |
| tok/s | 2,166 | 2,183 | 2,175 | 2,136 | 2,079 | 2,000 |
| TTFT | 4.0 s | 7.7 s | 15.3 s | 30.9 s | 63.2 s | 131.3 s |

An earlier sparkDash run, with one Spark's GPU locked at 1,800 MHz (the other at 2,200), read prose 74.6 and code 108.1
tok/s for one stream, 140.6 and 152.7 for four, and prefill 2,008-2,062 tok/s from 4K to 64K prompts (1,877 at 256K).

**`tools/bench.py`** (thinking off, temperature 0, random-word prompts so no prefix cache is hit and the drafter has little
to predict; medians of one or two repetitions, so differences of a few percent are noise):

| | Result |
| --- | --- |
| Prefill, 2K / 8K / 30K / 100K-token prompts | ~1,500-1,600 / ~1,960 / ~2,000 / ~1,950 tok/s (TTFT 1.2 s / 3.9 s / 14.4 s / 49 s) |
| Decode, 1 stream | 55-61 tok/s |
| Decode, 4 streams together | 113-117 tok/s |
| Drafting (DSpark) | ~2.2-2.4 tokens a round on random-word prompts (about 50 of 88 and 58 of 93 drafted tokens accepted) |

The lower `bench.py` decode numbers are the prompt, not the engine: real text drafts much better than random words.

These need **Engram's tables on local disk on both Sparks**: with the head reading them over NFS (`HEAD_ENGRAM_DIR` unset
and a remote `HF_CACHE`) a random 4 KiB read took ~940 us against ~90 us from local disk, and prefill was ~690-890 tok/s.
BertholomusAI's figures for the earlier checkpoint on two Sparks (decode 89.8 / 59.0 / 106.6 tok/s for code / prose /
structured, 4 streams 118.9 tok/s together, prompts at ~2,400 tok/s up to 128K) are the reference these are compared with:
with real prompts decode is above them (one stream: prose 74.9 against 59.0, code 109.9 against 89.8; four streams:
130.0 and 155.5 against 118.9), and prefill is ~9-11% under them from 8K to 64K prompts (~2,140-2,180 against ~2,400 tok/s).

A needle-in-a-haystack test at `CONTEXT=524288` (`tools/bench.py --suite needle`, a passphrase hidden at 10%, 50% and 90%
depth of a 479,012-token prompt) found it 3 of 3 times; each prefill took ~280 s (~1,710 tok/s). The head's lowest free
memory during it was 2.67 GiB, 0.17 GiB above the 2.5 GiB floor `memguard` was set to, so a 512K window is the practical
limit for a head that carries ~6 GiB of other software. A 100K-token prompt also ran without errors at the full
1,048,576-token window (3.14 GiB free at the lowest) and at 524,288 tokens.

**Engine patches** (`zig/patches/`, three, written for this recipe). Each is **off by default**, so the image behaves like
the pinned engine: its replies' token hashes equal the unpatched image's on 31 of 31 prompts (1 to 100,000 tokens, cached-prefix
resumes, four at once, a three-conversation scenario; `tools/exact.py`). Each is switched on with a `TF_DS_*` variable, which
`start.sh` gives to both ranks, and each was tested on its own:

| Switch | Result |
| --- | --- |
| `TF_DS_CACHE_PLACEMENT=1` (**on**) | In the three-conversation scenario, conversation B's second turn used to miss the prompt cache and re-read its whole 6K-token prompt (0 tokens reused); it now reuses 4,096, with an identical reply. Every other turn is unchanged. |
| `TF_DS_ENGRAM_LANES=2` (off) | A second I/O ring for the prompt's Engram reads. Bit-identical, but prefill 1.5-2.6% *slower* from 8K to 131K: the drive is the limit. |
| `TF_DS_IDX_SPLIT=1` (off) | Splits the prefill indexer's rows between the two ranks. Bit-identical, with no measurable gain on this pair (modeled at +1% at 64K and +2% at 128K; the undisturbed 32K repetitions tie the baseline). If the two ranks ever disagree on the setting the pair hangs, so it stays off. |

What is **not** checked: image input and `tools/validate.py` on this pair; other cabling, hardware or a head with less
memory to spare; days of uptime; and the engine's behaviour at the memory floor under heavy concurrent long prompts (the
watchdog exists because that can freeze a Spark; see [Memory and safety](#memory-and-safety)).

## Requirements

- **Two DGX Sparks** (or two GB10 systems with 128 GB unified memory), with nothing else large on them: the weights take
  ~98 GiB a Spark and rank 0 holds ~104 GiB on the GPU, so a Spark's memory is the limit, not its disk or its link.
  `start.sh` refuses to start unless `MIN_AVAIL_GIB` (109) is available on each Spark. A head that also runs a desktop
  and development tools (~6 GiB here) was left with ~3.1 GiB at the worst point of a 100K-token prompt at the full window
  and ~3.7 GiB at 524,288 tokens: give the head less to do, or lower `CONTEXT`.
- **The same GPU clock ceiling on both Sparks** (`nvidia-smi -lgc 0,2200`; check with `nvidia-smi -q -d CLOCK`). With TP=2 the
  ranks meet twice a layer, so the slower GPU sets the pace: one Spark found locked at 1,800 MHz cost about 3-6% of prefill
  and 3% of decode against 2,200 MHz on both (rigmark, same prompts; the GPUs peaked at 85 / 81 C and nothing throttled).
- **A direct ConnectX-7 link:** a QSFP cable between the CX7 ports and an IPv4 address on each end in one private subnet
  (e.g. `192.0.2.1/24` and `192.0.2.2/24`; `ping` must work), with a RoCE v2 GID (`start.sh` checks). One QSFP port of a
  Spark reaches the GB10 over two PCIe Gen5 x4 links, so it appears as two netdevs and two RoCE devices (`enp1s0f0np0` /
  `enP2p1s0f0np0`, `rocep1s0f0` / `roceP2p1s0f0`). Address both twins on each Spark (one subnet each is fine, the same
  MTU on both Sparks): both are then used as two rails; one rail is one x4 (~112 Gb/s of the port's 200).
- **Key-based ssh** from the first Spark (the head, which runs `./start.sh` and the API) to the second (the worker):
  `ssh-copy-id user@<worker>`; check with `ssh -o BatchMode=yes user@<worker> true`.
- Docker with the NVIDIA container runtime and your user in the `docker` group, on both Sparks; `git`, `python3` and the
  `hf` CLI (`pip install -U huggingface_hub`) on the head.
- **Disk.** Head: ~505 GB (the checkpoint 196 GiB, Engram's tables ~203 GB, rank 0's weight file ~106 GB) plus ~25 GB for
  the image under Docker's root. Worker: ~310 GB (Engram's tables and rank 1's weight file) plus the image; the worker
  reads the checkpoint from the head over NFS.
- **NFS.** The worker mounts the head's Hugging Face cache read-only. On the head, once (needs root; the worker needs
  nothing installed):

  ```bash
  sudo apt install nfs-kernel-server
  echo "$HOME/.cache/huggingface <worker CX7 address>(ro,no_subtree_check)" | sudo tee -a /etc/exports
  sudo exportfs -ra
  ```

  `prepare.sh` then creates a read-only docker NFS volume on the worker (`NFS_VOLUME`, no sudo) and checks that the worker
  sees every file the ranks read. `NFS_PATH` is the exported path as the worker mounts it (default: the head's `HF_CACHE`;
  `/` for an NFSv4 export with `fsid=0`), `NFS_SERVER` the head's address (default: its address on the link).

  **Or no NFS at all.** Each Spark can run from a local copy: set `HF_CACHE` to a local tree holding the checkpoint's small files
  and its vision shard (`model-00039-of-00039`, the only shard read at run time), the served `model/` folder, the kit, the token
  map and, on the head, rank 0's weight file; set `NFS_VOLUME` to the same path as a *host path* (the worker bind-mounts it) and
  leave `HEAD_NFS_SERVER` empty. Set `PREPARE=0` too: `scripts/prepare.sh` assumes a complete cache and would start downloading
  the 196 GiB checkpoint into a partial one.

## Quick start

Everything runs on the **head** Spark: the one that also serves the API. The worker needs no copy of this repository.

### 1. Get the repository, set the one value only you know

```bash
git clone https://github.com/xdrshjr/Aragon-DeepSeek-v4.1-Flash-1017-2x-DGX-Sparks.git
cd Aragon-DeepSeek-v4.1-Flash-1017-2x-DGX-Sparks
cp scripts/local.sh.example scripts/local.sh
$EDITOR scripts/local.sh        # WORKER=user@<the worker's CX7 address>; FABRIC_PEER if it is on another network
```

`WORKER` is the worker's ssh target; the ranks talk over the route to it. Key-based ssh must already work:
`ssh -o BatchMode=yes $WORKER true` has to succeed before anything else does.

### 2. Check the wiring before anything moves

```bash
DRY_RUN=1 ./start.sh
```

It prints the CX7 link it found, the RoCE rails it will use, and both ranks' exact `docker run` commands, then stops. It
stops nothing, downloads nothing, starts nothing. A wrong rail or cable is cheapest to find here.

### 3. Prepare the pair (first time only, hours) and start

```bash
./start.sh
```

That one command does the setup when something is missing and then starts the server: it builds the engine image (~6
minutes of Zig on a Spark), downloads the checkpoint (196 GiB) and Engram's tables (~203 GB), makes the kernel kit and
both ranks' weight files (~106 GB each), and only then loads the weights. Expect hours the first time, and minutes
after that. Every step is resumable: if it stops, run it again.

```bash
./start.sh restart      # restart both ranks, e.g. after changing a setting
./stop.sh               # stop both ranks and free their GPU memory
docker logs -f dsv41-1017-exl3-tf                      # rank 0's log (here)
ssh $WORKER docker logs -f dsv41-1017-exl3-tf          # rank 1's log (why it exited, if it did)
```

`start.sh` shows each step and the server's log, runs a smoke test through both ranks, then prints
`DeepSeek-V4.1-Flash-1017 is now LIVE! on port 8888`. `stop.sh` gzips each rank's log (newest 10 kept, `LOG_KEEP`) into
`~/.cache/dsv41-tensorfold/logs` before it removes the container.

### 4. Point a client at it

```bash
export API_URL=http://<head-address>:8888        # the port start.sh serves on (PORT)
curl -s $API_URL/v1/models
curl -s $API_URL/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model": "DeepSeek-V4.1-Flash-1017",
  "messages": [{"role": "user", "content": "Hello"}],
  "max_tokens": 64,
  "chat_template_kwargs": {"enable_thinking": false}}'
```

Any OpenAI client works with `base_url = "http://<head-address>:8888/v1"` and the model `DeepSeek-V4.1-Flash-1017`. The
model thinks before it answers unless a request turns thinking off, and `max_tokens` counts the reasoning too, so give
replies room. `API_KEY=1 ./start.sh restart` requires `Authorization: Bearer $(cat ~/.local/state/dsv41-tensorfold/api-key)`.

```bash
python3 tools/smoke.py                                   # quick: health, streaming, a tool call, determinism
python3 tools/validate.py $API_URL --model DeepSeek-V4.1-Flash-1017   # end to end: text, thinking, tools, image, long prompt
```

### 5. Optional: share the pair with a second service

If another model already runs on these Sparks, put both behind one command instead of starting them by hand:

```bash
./deploy/install.sh      # places serve, prepare-v41, the systemd units and a narrowly scoped sudoers drop-in
serve status             # the installer starts nothing; this reports what is already up
~/bin/prepare-v41        # first time on this pair only: image, downloads, both weight files
serve v41                # stop the other service, wait for memory, start this one, wait for HTTP 200
```

From then on `serve v41` / `serve v4` switch between them, and the client's `base_url` and API key stay valid.

`serve` is written against the pair it was deployed on, so it carries that pair's details: the second service's directory
and `.env.dspark` (where it reads the API key clients already use), its systemd unit name, the worker's CX7 addresses, and
the proxy used for the image build. Point those at your own deployments before you rely on it; [`deploy/README.md`](deploy/README.md)
says which file holds what.

The runbook is [`docs/serve-two-models.md`](docs/serve-two-models.md) — including the four network problems
`scripts/prepare.sh` assumes away on a real pair: GitHub resetting TLS during the kit fetch, an Xet bridge that answers
`401` on the large shards, a worker that lacks the base image its NFS check runs in, and `hf download` refusing the
~101 GB Engram shards outright.

## What `start.sh` and `scripts/prepare.sh` do

`scripts/prepare.sh` (run by `start.sh` when something is missing; safe to re-run) on the head:

1. checks docker, the GPU, ssh and the link;
2. builds the image from `zig/Dockerfile` (the pinned engine plus the inputs' tools) and copies it to the worker;
3. downloads the checkpoint and Engram's two shards (with their index and config) at their pinned revisions, and checks the
   shards' sizes (`VERIFY_SHA=1` also their sha256, as the model card lists them: the 1017 tables are new, the older
   release's must not be used);
4. fetches the kit at `KIT_REF`, makes its four RoPE tables and the image routing bias from the checkpoint, and checks every
   file against the kit's MANIFEST (the image bias may differ: it is 1017's own);
5. writes Engram's token map and rank 0's weight file from the checkpoint (no GPU), and the folder rank 0 serves (the
   checkpoint's files linked, with `model/chat_template.jinja`: the release ships its chat format as `encoding/encoding.py`,
   which the server cannot run);
6. creates the worker's NFS volume and checks it;
7. copies Engram's tables to the worker's disk (a decode round reads ~70 random 4 KiB rows from them; over NFS that took most
   of a round) and writes rank 1's weight file there from the checkpoint over NFS.

`start.sh` then starts rank 1 on the worker (`tf-dsv41-lanes`, following) and rank 0 here (`tensorfold-native serve`), waits
for the API, and runs a smoke test.

## Configuration

Settings come from the environment, `scripts/local.sh` or `.env`; the defaults and their notes are in
[`scripts/config.sh`](scripts/config.sh). The ones you are likely to touch:

| Setting | Default | |
| --- | --- | --- |
| `CONTEXT` | 1048576 | a request's positions at most; rank 1's `--pool` follows it |
| `PARALLEL` | 4 | requests at once (the engine's streams, 1 to 16; the family was measured at 4) |
| `THINKING`, `REASONING_EFFORT` | 1, empty | think first unless a request turns it off; `low` / `medium` / `high` / `xhigh` as the default effort |
| `TEMPERATURE`, `TOP_P`, `TOP_K` | 1.0, 0.95, 20 | the server's sampling defaults; a request's own values win |
| `DRAFTS` | 1 | the checkpoint's DSpark draft blocks (drafted replies equal plain ones) |
| `RDMA`, `GRAPHS`, `SIDE`, `PREFETCH`, `ENGRAM_AIO` | 1 | the engine's served settings |
| `MAX_TOKENS` | 32768 | a reply's budget when a request sets none |
| `MIN_AVAIL_GIB` | 109 | `start.sh` refuses to start with less memory available than this on either Spark (`0` skips the check) |
| `MEMGUARD_GIB` | 4 | `scripts/memguard.sh` kills a rank's container when the memory available stays under this floor (decimals fine; `0` turns it off) |
| `HEAD_ENGRAM_DIR` | empty | a local folder with Engram's two shards for rank 0 (as `WORKER_ENGRAM_DIR` is on the worker); empty reads them from `HF_CACHE` |
| `HEAD_NFS_SERVER`, `HEAD_NFS_VOLUME` | empty | rank 0 reads the checkpoint over NFS through a docker volume the docker daemon mounts (no root, survives a reboot); empty uses `HF_CACHE` as a host path. sshfs does not work: it lists files as type "unknown", which the engine skips |
| `TF_DS_CACHE_PLACEMENT`, `TF_DS_ENGRAM_LANES`, `TF_DS_IDX_SPLIT` | unset | the engine patches' switches (`zig/patches/`, see Status); a `TF_DS_*` variable you export goes to both ranks |
| `RANK1_PROFILE` | empty | `1` or `2` starts rank 1 with `--profile`, which prints its prefill phase timings when rank 0 stops first (adds a sync per chunk: for attribution, not for timing) |
| `API_KEY` | 0 | `1` makes rank 0 require a key (`Authorization: Bearer`; generated in `$STATE_DIR/api-key`, mode 600). The API is open on the network by default |
| `HOST`, `PORT`, `SERVED_NAME` | 0.0.0.0, 8888, `DeepSeek-V4.1-Flash-1017` | |
| `WORKER`, `FABRIC_PEER`, `NFS_*` | | see Requirements |
| `TF_REF`, `INPUTS_REF`, `KIT_REF` | pinned | the engine, the inputs' tools and the kit (changing one rebuilds or re-checks) |
| `PULL` | 1 | `0` never pulls a published image (`GHCR_IMAGE`, `IMAGE_TAG`, `IMAGE_DIGEST`; the image of these pins is `ghcr.io/miaai-lab/deepseek-v4.1-flash-1017-2x-dgx-sparks-tensorfold:exl3-tp2-7c9bf5d36350`) |

Extra arguments to `./start.sh` go to rank 0's `tensorfold-native serve` after the defaults; every `TENSORFOLD_*` and
`TF_DS_*` variable you set goes to both ranks. Images are always on (rank 0 runs the vision tower).

## Memory and safety

A Spark's GPU shares its memory with the host. A rank that takes all of it does not get a clean error: the machine stops
answering and has to be power-cycled (this happened once, with the engine's reserve lowered to 10 GiB). So:

- the engine's own reserve (`TENSORFOLD_MEMORY_RESERVE_GIB`, 12.2 GiB) is left alone: do not lower it to make the weights fit;
- `start.sh` checks `MIN_AVAIL_GIB` on both Sparks before it stops or starts anything, and stops a running server before
  it builds or downloads;
- `scripts/memguard.sh` runs on both Sparks while the server is up and kills the rank's container (kill first, log after)
  when `MemAvailable` stays under `MEMGUARD_GIB` for two samples 0.5 s apart. It is a brake, not a guarantee: a very fast
  allocation can outrun it. Its log is `~/.cache/dsv41-tensorfold/logs/memguard.log`;
- the KV cache is small (compressed FP4 with block scales; about 0.5 GiB at 262,144 tokens and ~1.8 GiB at the full window,
  by two memory readings); it is sized from `CONTEXT` when the model loads and shared by the streams. Most of the
  memory is the weights (~99 GiB, of which ~3.5 GiB are the drafter's), so the head's other software decides what is left.

## Repository layout

```
start.sh, stop.sh            start and stop both ranks
scripts/config.sh            every setting and its default (layered: environment, scripts/local.sh, .env)
scripts/nodes.sh             the worker over ssh, the CX7 link and its RoCE rails, NFS volume, NCCL settings
scripts/prepare.sh           image, downloads, kit, token map, weight files, the worker's NFS volume and disk
scripts/memguard.sh          the memory watchdog start.sh runs on both Sparks (kills a rank's container below MEMGUARD_GIB)
scripts/zig_flags.py         start.sh's check of rank 0's serve flags against the image's `capabilities --json`
scripts/publish-image.sh     pushes the built image to ghcr.io (only on purpose)
zig/Dockerfile, zig/patches  the engine image; patches to the pinned engine (four)
model/chat_template.jinja    the chat template rank 0 serves
tools/validate.py            an end-to-end check of a running server
tools/bench.py               prefill, decode, multi-stream and needle measurements as JSON, with `--compare A.json B.json`
tools/exact.py               records a server's replies (token hashes) on a fixed prompt set and compares two records: proves a new image equals the old one
tools/smoke.py               a quick correctness check: health, stop strings, streaming, a tool call and its result
tools/prompt_reuse.py        a conversation resumes from its kept prompt state (from the GLM-5.3-Flash recipe)
tools/toolcheck.py, needle.py, end_of_turn.py, anthropiccheck.py   single checks, from the GLM-5.3-Flash recipe
docs/zig-engine.md           how the pieces fit, and what is not verified
docs/hermes-agent.md         Hermes Agent as a client (by Steve Darlow)
docs/serve-two-models.md     two models on one pair, the switch script, and every network problem hit on a real pair
deploy/                      serve (switch), prepare-v41 (proxy build), the download helpers, the units, an installer
```

## License

This recipe's own code, scripts and documentation: Apache-2.0 ([`LICENSE`](LICENSE), [`NOTICE`](NOTICE)). The weights keep
their own MIT license (DeepSeek's; Mia's AI Lab's quantization). TensorFold, BertholomusAI's fork and kit, and the other
third-party parts keep theirs ([`NOTICE`](NOTICE)).

## Credits

- **[DeepSeek](https://huggingface.co/deepseek-ai)**: DeepSeek-V4.1-Flash-1017, its weights, its DSpark draft blocks, its
  Engram tables and its reference inference code (MIT).
- **Mia's AI Lab** ([Mia-AiLab](https://huggingface.co/Mia-AiLab)): the EAQ v1 EXL3 2.9 bpw quantization served here,
  [`Mia-AiLab/DeepSeek-V4.1-Flash-1017-EXL3-EAQ-v1-2.9-bpw`](https://huggingface.co/Mia-AiLab/DeepSeek-V4.1-Flash-1017-EXL3-EAQ-v1-2.9-bpw)
  (MIT), the earlier release
  [`Mia-AiLab/DeepSeek-V4.1-Flash-EXL3-2.9bpw`](https://huggingface.co/Mia-AiLab/DeepSeek-V4.1-Flash-EXL3-2.9bpw) whose
  per-tensor widths it equals, and the chat template (`model/chat_template.jinja`, written for that earlier release).
- **[turboderp](https://github.com/turboderp-org)**: [ExLlamaV3](https://github.com/turboderp-org/exllamav3), the EXL3 format
  and its quantizer (MIT).
- **[TensorFold](https://github.com/ashhart/TensorFold)** by Ash Hart ([ashhart](https://github.com/ashhart)) and the
  TensorFold contributors (Apache-2.0): the native Zig engine and its OpenAI-compatible server.
- **[BertholomusAI (Albert Lee, @bertholomus)](https://github.com/bertholomus)** (Apache-2.0): the DeepSeek-V4.1-Flash
  family on TensorFold's native engine (the two-node tensor-parallel split, the EXL3 kernels' use, Engram, DSpark drafting,
  the RDMA ring, the vision tower), in their fork
  [bertholomus/TensorFold, branch `deepseek-v41-zig`](https://github.com/bertholomus/TensorFold/tree/deepseek-v41-zig) at
  [`3ff3b2a`](https://github.com/bertholomus/TensorFold/commit/3ff3b2ac1d71a789cb930068c46d9abed025eefa), and its
  weight-file and token-map tools, in their branch
  [`deepseek-v41-zig-tp4`](https://github.com/bertholomus/TensorFold/tree/deepseek-v41-zig-tp4) at
  [`5940208`](https://github.com/bertholomus/TensorFold/commit/59402086381a42c74d53053443224eec2790b4c5); the kernel kit,
  the served settings and the two-node launch commands, in their recipe
  [bertholomus/deepseek-v4.1-tensorfold-tp2-2xgb10](https://github.com/bertholomus/deepseek-v4.1-tensorfold-tp2-2xgb10) at
  [`abe07c7`](https://github.com/bertholomus/deepseek-v4.1-tensorfold-tp2-2xgb10/commit/abe07c7d509a0199cc7fec15263be2aa52ac652f).
  Commits in that branch by [sayyidfareed](https://github.com/sayyidfareed) (RDMA GID and MTU),
  [Lucas Peters](https://github.com/lucas-peters) (indexer alignment; the kit's `_topk_sel` variant), lepetitprince716-prog
  (expert-run loading) and LeetJoe (image placeholder escaping).
- **Mia's AI Lab**: this recipe's scripts, adapted from
  [GLM-5.3-Flash-EXL3-2x-DGX-Sparks-TensorFold](https://github.com/MiaAI-Lab/GLM-5.3-Flash-EXL3-2x-DGX-Sparks-TensorFold)
  (branch `zig-engine`), with code by webzone (both PCIe links of a port as twin rails), [Alexbob0](https://github.com/Alexbob0)
  (workers by host name; `tools/end_of_turn.py`) and john (each rank's rendezvous address); `tools/anthropiccheck.py` by
  Eduardo Florencio ([eduffd](https://github.com/eduffd)), and the Hermes Agent page by Steve Darlow
  ([@kerpopule](https://github.com/kerpopule)).
- **Mia's AI Lab**: this recipe's own engine patches, `zig/patches/0001`-`0003` (changes to BertholomusAI's engine, written
  for this recipe, Apache-2.0): the prefill indexer split between the two ranks, a second AIO ring for Engram reads and
  prompt-cache placement for resumed prompts; also `tools/exact.py` (token-hash replay check) and `scripts/memguard.sh`.
  The idea of splitting the indexer is drowzeys's, from the GLM-5.3-Flash recipe's design (no code of it was used).
  `0004` (`tool_choice` enforcement) is a Zig port of the call gate in TensorFold's Python engine (`call_gate.py`), by the
  TensorFold contributors (Apache-2.0).
- **NVIDIA**: the DGX Spark and GB10 hardware, and the PyTorch container (`nvcr.io/nvidia/pytorch:26.07-py3`) the image is
  built on (CUDA, NCCL, cuBLAS; under NVIDIA's container license).

Full list, with commits: [`CREDITS.md`](CREDITS.md).
