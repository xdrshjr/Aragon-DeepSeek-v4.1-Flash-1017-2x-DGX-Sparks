"""CPU-only endpoint configuration regression tests; never execute local.sh."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("bench", Path(__file__).with_name("bench.py"))
bench = importlib.util.module_from_spec(SPEC)
with patch.dict(os.environ, {"API_KEY": "", "API_KEY_FILE": "/dev/null"}):
    SPEC.loader.exec_module(bench)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        self.local = self.root / "scripts/local.sh"
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.location = patch.object(bench, "__file__", str(self.root / "tools/bench.py"))
        self.location.start()
        self.addCleanup(self.location.stop)

    def test_missing_file(self):
        self.assertEqual(bench.default_base(), "http://127.0.0.1:8888")

    def test_literal_and_precedence(self):
        self.local.write_text('export PORT="8007" # local\n')
        self.assertEqual(bench.default_base(), "http://127.0.0.1:8007")
        with patch.dict(os.environ, {"PORT": "9999"}):
            self.assertEqual(bench.default_base(), "http://127.0.0.1:9999")
        with patch.dict(os.environ, {"PORT": "9999", "API_URL": "http://localhost:7777/v1"}):
            self.assertEqual(bench.default_base(), "http://localhost:7777/v1")

    def test_last_assignment(self):
        self.local.write_text("PORT=8006\nPORT='8007'\n")
        self.assertEqual(bench.default_base(), "http://127.0.0.1:8007")

    def test_ignores_shell_code_and_mismatched_quotes(self):
        marker = self.root / "executed"
        self.local.write_text(f"# PORT=9001\nSOME_PORT=9002\nPORT=8007\"\nPORT=$(touch {marker})\n")
        self.assertEqual(bench.default_base(), "http://127.0.0.1:8888")
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
