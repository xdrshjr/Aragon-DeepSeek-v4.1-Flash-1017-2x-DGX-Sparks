"""The pinned kit has decode kernels for at most sixteen rows."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RoundRowsTest(unittest.TestCase):
    def test_supported_and_missing_kernel_sizes(self):
        line = next(line for line in (ROOT / "start.sh").read_text().splitlines()
                    if line.startswith('[[ -z "$ROUND_ROWS" ]] || {'))
        for value in ("", "16", "17", "32", "48", "0", "garbage"):
            with self.subTest(value=value):
                result = subprocess.run(["bash", "-c", 'die() { exit 1; }; ROUND_ROWS=$1; ' + line, "test", value],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, value in ("", "16"), result.stderr)


if __name__ == "__main__":
    unittest.main()
