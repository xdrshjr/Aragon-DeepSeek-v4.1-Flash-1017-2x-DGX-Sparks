#!/usr/bin/env python3
"""Verify the optional unit; opt in to transient stub-only user-manager tests."""
import configparser
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / "systemd/dsv41-tensorfold.service"


class UnitSyntaxTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze is not installed")
    def test_systemd_accepts_template(self):
        # Verification is offline; provide a private runtime path even on headless CI.
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ, XDG_RUNTIME_DIR=folder)
            env.pop("DBUS_SESSION_BUS_ADDRESS", None)
            result = subprocess.run(["systemd-analyze", "--user", "verify", str(UNIT)],
                                    env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(os.environ.get("RUN_SYSTEMD_LIFECYCLE_TESTS") == "1",
                     "opt in to temporary user-manager lifecycle tests")
class UnitLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("systemd-run") or not shutil.which("systemctl"):
            raise unittest.SkipTest("systemd user-manager tools are not installed")
        check = subprocess.run(["systemctl", "--user", "show-environment"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        if check.returncode:
            raise unittest.SkipTest("no reachable systemd user manager")

    def exercise(self, status):
        with tempfile.TemporaryDirectory(prefix="tf systemd test ") as folder:
            root = Path(folder)
            (root / "start.sh").write_text(
                '#!/usr/bin/env bash\nset -eu\n'
                'printf "%s %s\\n" "$FOREGROUND" "$PREPARE" >> starts\n'
                'if [[ "$TF_TEST_STATUS" == hold ]]; then exec sleep 30; fi\n'
                'exit "$TF_TEST_STATUS"\n')
            (root / "stop.sh").write_text('#!/usr/bin/env bash\nprintf "stop\\n" >> stops\n')
            cfg = configparser.ConfigParser(interpolation=None)
            cfg.read(UNIT)
            service = cfg["Service"]
            # Only ever execute our relative stub scripts, even if the real unit changes.
            start = shlex.split(service["ExecStart"])
            stop = shlex.split(service["ExecStop"])
            self.assertEqual(start, ["/usr/bin/bash", "./start.sh"])
            self.assertEqual(stop, ["/usr/bin/bash", "./stop.sh"])
            name = "tf-unit-test-" + uuid.uuid4().hex + ".service"
            command = ["systemd-run", "--user", "--quiet", "--collect", "--unit=" + name]
            properties = {
                "Type": service["Type"], "Restart": service["Restart"],
                "StartLimitBurst": cfg["Unit"]["StartLimitBurst"],
                "WorkingDirectory": folder, "ExecStop": service["ExecStop"],
                # Exercise the real policy with short test-only timers.
                "RestartSec": "100ms", "StartLimitIntervalSec": "10s", "TimeoutStopSec": "3s",
            }
            command += ["--property=" + key + "=" + value for key, value in properties.items()]
            command += ["--setenv=" + value for value in shlex.split(service["Environment"])]
            command += ["--setenv=TF_TEST_STATUS=" + str(status)] + start

            def state():
                result = subprocess.run(["systemctl", "--user", "show", name,
                                         "-p", "ActiveState", "-p", "LoadState"],
                                        capture_output=True, text=True, timeout=5)
                return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)

            def starts():
                return (root / "starts").read_text().splitlines() if (root / "starts").exists() else []

            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                until = time.monotonic() + 10
                while time.monotonic() < until:
                    current = state()
                    if status == "hold" and starts() and current.get("ActiveState") == "active":
                        break
                    if status != "hold" and starts() and current.get("ActiveState") in ("failed", "inactive"):
                        break
                    time.sleep(0.05)
                else:
                    self.fail("transient unit did not reach the expected final state")
                if status == "hold":
                    subprocess.run(["systemctl", "--user", "stop", name], check=True,
                                   capture_output=True, timeout=10)
                    time.sleep(0.3)  # longer than the test-only restart delay
                    self.assertEqual(starts(), ["1 0"])
                    self.assertTrue((root / "stops").exists(), "ExecStop did not run")
                    self.assertEqual(state().get("ActiveState"), "inactive")
                else:
                    expected = 1 if status == 0 else 3
                    self.assertEqual(starts(), ["1 0"] * expected)
            finally:
                subprocess.run(["systemctl", "--user", "stop", name],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                subprocess.run(["systemctl", "--user", "reset-failed", name],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)

    def test_failure_exits_stop_at_start_limit(self):
        for status in (1, 137):
            with self.subTest(status=status):
                self.exercise(status)

    def test_success_does_not_restart(self):
        self.exercise(0)

    def test_explicit_stop_does_not_restart(self):
        self.exercise("hold")


if __name__ == "__main__":
    unittest.main()
