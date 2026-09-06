import importlib.util
import os
from pathlib import Path
import tempfile
import threading
import subprocess
import sys
import select
import unittest
from unittest.mock import patch

from packages.operations.admission import AdmissionClosed, chat_admission

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("byq_admission_operator", ROOT / "scripts/dsh/admission.py")
operator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(operator)


class ChatAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "admission.state"
        operator.initialize(self.path)
        operator.set_state(self.path, "open")
        self.environment = patch.dict(os.environ, {"BYQ_CHAT_ADMISSION_FILE": str(self.path)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_default_is_unchanged_but_configured_missing_or_invalid_gate_fails_closed(self):
        with patch.dict(os.environ, {"BYQ_CHAT_ADMISSION_FILE": ""}):
            with chat_admission():
                pass
        for body in ("unknown\n", "open\ntrailing", "", "closed\n"):
            self.path.write_text(body)
            with self.assertRaises(AdmissionClosed):
                with chat_admission():
                    self.fail("invalid gate admitted")
        self.path.unlink()
        with self.assertRaises(AdmissionClosed):
            with chat_admission():
                self.fail("missing gate admitted")

    def test_close_waits_for_inflight_admission_and_blocks_all_new_admissions(self):
        entered, release = threading.Event(), threading.Event()

        def in_flight():
            with chat_admission():
                entered.set()
                release.wait(3)

        thread = threading.Thread(target=in_flight)
        thread.start()
        self.assertTrue(entered.wait(1))
        try:
            with self.assertRaises(TimeoutError):
                operator.set_state(self.path, "closed", timeout=0.03)
            self.assertEqual(self.path.read_text(), "open\n")
        finally:
            release.set()
            thread.join(3)
        operator.set_state(self.path, "closed", timeout=1)
        for _ in range(2):
            with self.assertRaises(AdmissionClosed):
                with chat_admission():
                    self.fail("maintenance admitted")
        operator.set_state(self.path, "open", timeout=1)
        before = self.path.stat().st_mtime_ns
        with chat_admission():
            pass
        self.assertEqual(self.path.stat().st_mtime_ns, before)

    def test_symlink_and_reinitialization_are_rejected(self):
        with self.assertRaises(FileExistsError):
            operator.initialize(self.path)
        link = Path(self.directory.name) / "link.state"
        link.symlink_to(self.path)
        with patch.dict(os.environ, {"BYQ_CHAT_ADMISSION_FILE": str(link)}):
            with self.assertRaises(AdmissionClosed):
                with chat_admission():
                    self.fail("symlink admitted")
        with self.assertRaises(ValueError):
            operator.set_state(link, "closed", timeout=1)
        self.assertEqual(self.path.read_text(), "open\n")

    def test_operator_waits_for_a_separate_serving_process(self):
        process = subprocess.Popen(
            [sys.executable, "-c", (
                "from packages.operations.admission import chat_admission\n"
                "import sys\n"
                "with chat_admission():\n"
                " print('admitted', flush=True)\n"
                " sys.stdin.readline()\n"
            )], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        try:
            self.assertTrue(select.select([process.stdout], [], [], 5)[0])
            self.assertEqual(process.stdout.readline().strip(), "admitted")
            with self.assertRaises(TimeoutError):
                operator.set_state(self.path, "closed", timeout=0.03)
            process.communicate("release\n", timeout=5)
            self.assertEqual(process.returncode, 0)
            operator.set_state(self.path, "closed", timeout=1)
            with self.assertRaises(AdmissionClosed):
                with chat_admission():
                    self.fail("admitted after cross-process drain")
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
