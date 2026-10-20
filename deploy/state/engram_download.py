#!/usr/bin/env python3
"""Fetch Engram's two tables into the Hugging Face cache, resumably.

`hf download` refuses these files: at ~101 GB each they exceed what its plain
HTTP path allows and it demands Xet for them, while hf-mirror's Xet bridge
answers 401 on the CAS reconstruction. A ranged GET from the same mirror works
and sustains ~49 MiB/s, so this does that and resumes from wherever it stopped.

Files land in the snapshot directory as real files (not blob symlinks). That is
what scripts/prepare.sh checks: `-s "$ESNAP/$f"`, then the exact byte size
against the 1017 release's table, then it copies them to the worker.
"""
import os
import subprocess
import sys
import time

REPO = "deepseek-ai/DeepSeek-V4.1-Flash-1017"
REV = "1bae0e1088993b9b82de08f59de5be5a34e42170"
ENDPOINT = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")
SNAP = os.path.expanduser(
    f"~/.cache/huggingface/hub/models--deepseek-ai--DeepSeek-V4.1-Flash-1017"
    f"/snapshots/{REV}"
)
SHARDS = {
    "model-00047-of-00048.safetensors": 101535150936,
    "model-00048-of-00048.safetensors": 101537926640,
}


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def url_for(name: str) -> str:
    return f"{ENDPOINT}/{REPO}/resolve/{REV}/{name}"


def size_of(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def fetch_one(name: str, expected: int) -> bool:
    """Download one shard, resuming, until it holds `expected` bytes."""
    dest = os.path.join(SNAP, name)
    if size_of(dest) == expected:
        log(f"{name}: already complete ({expected} bytes)")
        return True
    attempt = 0
    while True:
        have = size_of(dest)
        if have > expected:
            log(f"{name}: {have} bytes is larger than the expected {expected}: restarting")
            os.remove(dest)
            have = 0
        attempt += 1
        log(f"{name}: attempt {attempt} from {have / 1073741824:.1f} GiB of "
            f"{expected / 1073741824:.1f} GiB")
        command = [
            "curl", "-4", "-sSL", "--fail",
            "-C", "-",
            "--retry", "8", "--retry-delay", "5", "--retry-all-errors",
            "--connect-timeout", "30",
            "-o", dest,
            url_for(name),
        ]
        subprocess.run(command, check=False)
        have = size_of(dest)
        if have == expected:
            log(f"{name}: complete after {attempt} attempt(s)")
            return True
        log(f"{name}: at {have / 1073741824:.1f} GiB after attempt {attempt}")
        if attempt >= 200:
            log(f"{name}: giving up after {attempt} attempts")
            return False
        time.sleep(3)


def main() -> int:
    os.makedirs(SNAP, exist_ok=True)
    failed = []
    for name, expected in SHARDS.items():
        if not fetch_one(name, expected):
            failed.append(name)
    if failed:
        log(f"incomplete: {failed} (re-run to resume)")
        return 1
    log("both Engram shards are complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
