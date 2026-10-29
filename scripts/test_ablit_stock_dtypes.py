#!/usr/bin/env python3
"""Regression test for ablit_stock_dtypes.py (issues #11 and #13). Needs torch and safetensors, so run it in the image:

  docker run --rm --network none --entrypoint python3 -v "$PWD/scripts:/s:ro" "$IMAGE" /s/test_ablit_stock_dtypes.py

Builds a two-shard "stock" folder and an "overlay" folder where shard 1 is a hardlink of stock's and shard 2 has the
Keys graft's F16 -> F32 cast of the drafter's confidence head. Without the script the head stays F32 (the engine reads
it as F16); with it the head is stock's F16 bytes again, a hardlinked stock shard is never written, and a tensor that
is not a pure cast of stock's is refused.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import torch
from safetensors import safe_open
from safetensors.torch import save_file

SCRIPT = Path(__file__).with_name("ablit_stock_dtypes.py")
HEAD = "mtp.2.confidence_head.proj.weight"
BIAS = "mtp.0.ffn.gate.bias"


def run(stock: Path, ablit: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(SCRIPT), str(stock), str(ablit)], capture_output=True, text=True)


def dtype_of(path: Path, key: str) -> torch.dtype:
    with safe_open(str(path), framework="pt") as f:
        return f.get_tensor(key).dtype


def build(root: Path, tamper: bool = False):
    stock, ablit = root / "stock", root / "ablit"
    stock.mkdir()
    ablit.mkdir()
    g = torch.Generator().manual_seed(0)
    keep = {"layers.0.attn.wo_b.weight": torch.randn(4, 4, generator=g).half()}
    mtp = {HEAD: torch.randn(1, 8, generator=g).half(), BIAS: torch.randn(8, generator=g).half()}
    save_file(keep, str(stock / "model-00001-of-00002.safetensors"), metadata={"format": "pt"})
    save_file(mtp, str(stock / "model-00002-of-00002.safetensors"), metadata={"format": "pt"})
    os.link(stock / "model-00001-of-00002.safetensors", ablit / "model-00001-of-00002.safetensors")
    cast = {k: v.float() for k, v in mtp.items()}
    if tamper:
        cast[HEAD][0, 0] += 1.0
    save_file(cast, str(ablit / "model-00002-of-00002.safetensors"), metadata={"format": "pt"})
    index = {"weight_map": {"layers.0.attn.wo_b.weight": "model-00001-of-00002.safetensors",
                            HEAD: "model-00002-of-00002.safetensors", BIAS: "model-00002-of-00002.safetensors"}}
    (ablit / "model.safetensors.index.json").write_text(json.dumps(index))
    return stock, ablit


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        stock, ablit = build(Path(d))
        s1 = stock / "model-00001-of-00002.safetensors"
        before = s1.read_bytes()
        assert dtype_of(ablit / "model-00002-of-00002.safetensors", HEAD) == torch.float32
        r = run(stock, ablit)
        assert r.returncode == 0, r.stderr
        got = ablit / "model-00002-of-00002.safetensors"
        assert dtype_of(got, HEAD) == torch.float16, "the confidence head must be F16 again"
        assert got.read_bytes() == (stock / "model-00002-of-00002.safetensors").read_bytes(), "not stock's bytes"
        assert s1.read_bytes() == before and os.path.samefile(s1, ablit / s1.name), "a hardlinked stock shard changed"
        r = run(stock, ablit)
        assert r.returncode == 0 and "already has its stock dtype" in r.stdout, r.stdout + r.stderr

    with tempfile.TemporaryDirectory() as d:
        stock, ablit = build(Path(d), tamper=True)
        r = run(stock, ablit)
        assert r.returncode == 1 and "not a cast" in r.stderr, "a changed value must be refused: " + r.stderr
        assert dtype_of(ablit / "model-00002-of-00002.safetensors", HEAD) == torch.float32, "refused, so untouched"
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
