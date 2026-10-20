#!/usr/bin/env python3
"""Download the DeepSeek-V4.1-Flash-1017 checkpoint and Engram's tables, resumably.

Runs on the head Spark under a systemd unit so it outlives an ssh session. Every
step skips files already in the cache, so re-running it after an interruption
costs only the missing bytes.

Xet is disabled on purpose: hf-mirror's Xet bridge answers 401 on the CAS
reconstruction of the large shards here, while plain ranged HTTPS downloads from
the same mirror sustain ~56 MiB/s. The old DeepSeek-V4-Flash recipe on this pair
of Sparks carries HF_HUB_DISABLE_XET=1 for the same reason.
"""
import os
import subprocess
import sys
import time

CACHE = os.path.expanduser("~/.cache/huggingface/hub")
MODEL_ID = "Mia-AiLab/DeepSeek-V4.1-Flash-1017-EXL3-EAQ-v1-2.9-bpw"
MODEL_REV = "6d54be4fca338d79b17c3b03cc9a423bb3ac6718"
ENGRAM_ID = "deepseek-ai/DeepSeek-V4.1-Flash-1017"
ENGRAM_REV = "1bae0e1088993b9b82de08f59de5be5a34e42170"
ENGRAM_SHARDS = (
    "model-00047-of-00048.safetensors",
    "model-00048-of-00048.safetensors",
)
MAX_WORKERS = "6"


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def run_download(repo: str, revision: str, extra: list[str]) -> int:
    """Run one `hf download` and return its exit code."""
    command = [
        "hf",
        "download",
        repo,
        "--revision",
        revision,
        "--cache-dir",
        CACHE,
        "--max-workers",
        MAX_WORKERS,
    ] + extra
    log(f"start {repo} @ {revision[:8]}")
    completed = subprocess.run(command, check=False)
    log(f"exit {completed.returncode} for {repo}")
    return completed.returncode


def main() -> int:
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

    include = ["--include", "model.safetensors.index.json", "--include", "config.json"]
    for shard in ENGRAM_SHARDS:
        include += ["--include", shard]

    codes = [
        run_download(MODEL_ID, MODEL_REV, []),
        run_download(ENGRAM_ID, ENGRAM_REV, include),
    ]
    failed = [code for code in codes if code != 0]
    if failed:
        log(f"finished with failures: {failed} (re-run to resume)")
        return 1
    log("finished: both downloads complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
