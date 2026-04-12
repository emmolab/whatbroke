import contextlib
import io
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from whatbroke.cli import _load_state, _result_hint, _run_single
from whatbroke.result import Result


class CliStateAndHintsTests(unittest.TestCase):
    def _args(self, **overrides):
        base = {
            "compact": False,
            "verbose": False,
            "broken_only": False,
            "json": False,
            "no_color": True,
            "no_state": False,
            "diff": False,
        }
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_load_state_accepts_legacy_flat_format(self):
        with tempfile.TemporaryDirectory() as td:
            state_path = os.path.join(td, "state.json")
            with open(state_path, "w") as f:
                json.dump({"firewall": {"status": "WARN", "message": "old"}}, f)

            with patch("whatbroke.cli._STATE_FILE", state_path):
                state = _load_state()

        self.assertIn("firewall", state["checks"])
        self.assertEqual(state["checks"]["firewall"]["status"], "WARN")

    def test_result_hint_uses_why_and_next_for_broken_checks(self):
        hint = _result_hint(Result(
            name="disk",
            status="CRIT",
            message="Disk almost full",
            remediation="Free space on /.\nRemove old backups.",
        ))

        self.assertIn("Why:", hint)
        self.assertIn("Next: Free space on /.", hint)

    def test_diff_reports_worsened_and_changed_broken_checks(self):
        previous_state = {
            "updated_at": "2026-04-11T00:00:00+00:00",
            "checks": {
                "firewall": {"status": "WARN", "message": "Firewall status unclear", "first_seen": None, "last_seen": None},
                "services": {"status": "BROKE", "message": "1 failed unit(s)", "first_seen": None, "last_seen": None},
            },
        }
        results = {
            "firewall": lambda: Result("firewall", "CRIT", "No active firewall rules detected", remediation="Enable nftables"),
            "services": lambda: Result("services", "BROKE", "2 failed unit(s)", remediation="Restart the failed unit"),
            "security": lambda: Result("security", "OK", "Healthy"),
        }

        with tempfile.TemporaryDirectory() as td, patch("whatbroke.cli._STATE_DIR", td), patch("whatbroke.cli._STATE_FILE", os.path.join(td, "state.json")), patch("whatbroke.cli._load_state", return_value=previous_state):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = _run_single(results, self._args(diff=True))
            output = buf.getvalue()

        self.assertEqual(code, 3)
        self.assertIn("firewall", output)
        self.assertIn("[WORSE]", output)
        self.assertIn("services", output)
        self.assertIn("[CHANGED]", output)
        self.assertNotIn("security", output)

    def test_summary_includes_recovered_counts(self):
        previous_state = {
            "updated_at": "2026-04-11T00:00:00+00:00",
            "checks": {
                "firewall": {"status": "WARN", "message": "Firewall status unclear", "first_seen": None, "last_seen": None},
            },
        }
        results = {
            "firewall": lambda: Result("firewall", "OK", "Firewall active"),
        }

        with tempfile.TemporaryDirectory() as td, patch("whatbroke.cli._STATE_DIR", td), patch("whatbroke.cli._STATE_FILE", os.path.join(td, "state.json")), patch("whatbroke.cli._load_state", return_value=previous_state):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = _run_single(results, self._args())
            output = buf.getvalue()

        self.assertEqual(code, 0)
        self.assertIn("1 recovered", output)


if __name__ == "__main__":
    unittest.main()
