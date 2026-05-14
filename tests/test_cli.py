import contextlib
import io
import json
import os
import runpy
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from whatbroke.cli import _hint_to_show, _load_state, _parse_check_filter, _result_hint, _run_single, _stdout_supports_color, _visible_details, main
from whatbroke.result import Result


class CliColorDetectionTests(unittest.TestCase):
    def test_stdout_supports_color_when_stream_is_tty(self):
        stream = SimpleNamespace(isatty=lambda: True)

        self.assertTrue(_stdout_supports_color(stream))

    def test_stdout_supports_color_returns_false_for_non_tty_streams(self):
        stream = SimpleNamespace(isatty=lambda: False)

        self.assertFalse(_stdout_supports_color(stream))


class CliStateAndHintsTests(unittest.TestCase):
    def _args(self, **overrides):
        base = {
            "compact": False,
            "verbose": False,
            "broken_only": False,
            "json": False,
            "nagios": False,
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

    def test_result_hint_uses_next_for_broken_checks(self):
        hint = _result_hint(Result(
            name="disk",
            status="CRIT",
            message="Disk almost full",
            remediation="Free space on /.\nRemove old backups.",
        ))

        self.assertEqual(hint, "Next: Free space on /.")

    def test_result_hint_combines_intro_line_with_first_actionable_command(self):
        hint = _result_hint(Result(
            name="firewall",
            status="WARN",
            message="Firewall status unclear",
            remediation=(
                "Re-run with sudo before changing firewall state:\n"
                "  nftables:  sudo nft list ruleset\n"
                "  ufw:       sudo ufw status verbose\n"
                "If no live firewall is confirmed, then enable one backend deliberately."
            ),
        ))

        self.assertEqual(hint, "Next: Re-run with sudo before changing firewall state: sudo nft list ruleset")

    def test_result_hint_keeps_first_follow_up_line_when_no_backend_label_exists(self):
        hint = _result_hint(Result(
            name="firewall",
            status="WARN",
            message="No active firewall rules detected",
            remediation=(
                "Enable a firewall:\n"
                "  systemctl enable --now nftables\n"
                "Or choose ufw/firewalld if that better fits the host."
            ),
        ))

        self.assertEqual(hint, "Next: Enable a firewall: systemctl enable --now nftables")

    def test_visible_details_skips_message_duplicates_and_repeated_details(self):
        result = Result(
            name="firewall",
            status="WARN",
            message="Firewall status unclear",
            details=[
                "Firewall status unclear",
                "nftables: installed (ruleset requires root to inspect)",
                "nftables: installed (ruleset requires root to inspect)",
                "ufw: installed (run with sudo to inspect status)",
            ],
        )

        self.assertEqual(
            _visible_details(result),
            [
                "nftables: installed (ruleset requires root to inspect)",
                "ufw: installed (run with sudo to inspect status)",
            ],
        )

    def test_hint_to_show_suppresses_derived_hint_in_verbose_mode_when_fix_block_will_repeat_it(self):
        result = Result(
            name="firewall",
            status="WARN",
            message="Firewall status unclear",
            remediation=(
                "Re-run with sudo before changing firewall state:\n"
                "  nftables:  sudo nft list ruleset\n"
                "  ufw:       sudo ufw status verbose\n"
                "If no live firewall is confirmed, then enable one backend deliberately."
            ),
        )

        self.assertIsNone(_hint_to_show(result, verbose=True))
        self.assertEqual(
            _hint_to_show(result, verbose=False),
            "Next: Re-run with sudo before changing firewall state: sudo nft list ruleset",
        )

    def test_hint_to_show_keeps_explicit_hint_in_verbose_mode(self):
        result = Result(
            name="services",
            status="WARN",
            message="Package manager lock present",
            remediation="Wait for the active package transaction to finish.",
            hint="Next: verify whether a package update is already running.",
        )

        self.assertEqual(
            _hint_to_show(result, verbose=True),
            "Next: verify whether a package update is already running.",
        )

    def test_diff_reports_worsened_and_changed_broken_checks(self):
        previous_state = {
            "updated_at": "2026-04-11T00:00:00+00:00",
            "checks": {
                "firewall": {"status": "WARN", "message": "Firewall status unclear", "first_seen": None, "last_seen": None},
                "services": {"status": "BROKE", "message": "1 failed unit(s)", "first_seen": None, "last_seen": None},
                "hardware": {"status": "OK", "message": "Load normal", "first_seen": None, "last_seen": None},
            },
        }
        results = {
            "firewall": lambda: Result("firewall", "CRIT", "No active firewall rules detected", remediation="Enable nftables"),
            "services": lambda: Result("services", "BROKE", "2 failed unit(s)", remediation="Restart the failed unit"),
            "hardware": lambda: Result("hardware", "OK", "Load healthy"),
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
        self.assertNotIn("hardware", output)
        self.assertNotIn("security", output)

    def test_diff_returns_zero_when_existing_broken_checks_are_unchanged(self):
        previous_state = {
            "updated_at": "2026-04-11T00:00:00+00:00",
            "checks": {
                "services": {"status": "BROKE", "message": "1 failed unit(s)", "first_seen": None, "last_seen": None},
            },
        }
        results = {
            "services": lambda: Result("services", "BROKE", "1 failed unit(s)"),
        }

        with tempfile.TemporaryDirectory() as td, patch("whatbroke.cli._STATE_DIR", td), patch("whatbroke.cli._STATE_FILE", os.path.join(td, "state.json")), patch("whatbroke.cli._load_state", return_value=previous_state):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = _run_single(results, self._args(diff=True))
            output = buf.getvalue()

        self.assertEqual(code, 0)
        self.assertIn("No broken checks changed since last run.", output)

    def test_compact_diff_returns_zero_when_existing_broken_checks_are_unchanged(self):
        previous_state = {
            "updated_at": "2026-04-11T00:00:00+00:00",
            "checks": {
                "services": {"status": "BROKE", "message": "1 failed unit(s)", "first_seen": None, "last_seen": None},
            },
        }
        results = {
            "services": lambda: Result("services", "BROKE", "1 failed unit(s)"),
        }

        with tempfile.TemporaryDirectory() as td, patch("whatbroke.cli._STATE_DIR", td), patch("whatbroke.cli._STATE_FILE", os.path.join(td, "state.json")), patch("whatbroke.cli._load_state", return_value=previous_state):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = _run_single(results, self._args(compact=True, diff=True))
            output = buf.getvalue()

        self.assertEqual(code, 0)
        self.assertEqual(output, "")

    def test_diff_exit_code_tracks_changed_broken_checks_not_unchanged_overall_worst(self):
        previous_state = {
            "updated_at": "2026-04-11T00:00:00+00:00",
            "checks": {
                "disk": {"status": "CRIT", "message": "Disk full", "first_seen": None, "last_seen": None},
                "logs": {"status": "OK", "message": "Healthy", "first_seen": None, "last_seen": None},
            },
        }
        results = {
            "disk": lambda: Result("disk", "CRIT", "Disk full"),
            "logs": lambda: Result("logs", "WARN", "Recent errors"),
        }

        with tempfile.TemporaryDirectory() as td, patch("whatbroke.cli._STATE_DIR", td), patch("whatbroke.cli._STATE_FILE", os.path.join(td, "state.json")), patch("whatbroke.cli._load_state", return_value=previous_state):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = _run_single(results, self._args(diff=True))
            output = buf.getvalue()

        self.assertEqual(code, 1)
        self.assertIn("logs", output)
        self.assertNotIn("disk: ", output)

    def test_json_diff_exit_code_tracks_changed_broken_checks(self):
        previous_state = {
            "updated_at": "2026-04-11T00:00:00+00:00",
            "checks": {
                "disk": {"status": "CRIT", "message": "Disk full", "first_seen": None, "last_seen": None},
                "logs": {"status": "OK", "message": "Healthy", "first_seen": None, "last_seen": None},
            },
        }
        results = {
            "disk": lambda: Result("disk", "CRIT", "Disk full"),
            "logs": lambda: Result("logs", "WARN", "Recent errors"),
        }

        with tempfile.TemporaryDirectory() as td, patch("whatbroke.cli._STATE_DIR", td), patch("whatbroke.cli._STATE_FILE", os.path.join(td, "state.json")), patch("whatbroke.cli._load_state", return_value=previous_state):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = _run_single(results, self._args(json=True, diff=True))
            payload = json.loads(buf.getvalue())

        self.assertEqual(code, 1)
        self.assertEqual([item["name"] for item in payload], ["logs"])

    def test_compact_diff_exit_code_tracks_changed_broken_checks(self):
        previous_state = {
            "updated_at": "2026-04-11T00:00:00+00:00",
            "checks": {
                "disk": {"status": "CRIT", "message": "Disk full", "first_seen": None, "last_seen": None},
                "logs": {"status": "OK", "message": "Healthy", "first_seen": None, "last_seen": None},
            },
        }
        results = {
            "disk": lambda: Result("disk", "CRIT", "Disk full"),
            "logs": lambda: Result("logs", "WARN", "Recent errors"),
        }

        with tempfile.TemporaryDirectory() as td, patch("whatbroke.cli._STATE_DIR", td), patch("whatbroke.cli._STATE_FILE", os.path.join(td, "state.json")), patch("whatbroke.cli._load_state", return_value=previous_state):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = _run_single(results, self._args(compact=True, diff=True))
            output = buf.getvalue()

        self.assertEqual(code, 1)
        self.assertIn("logs:", output)
        self.assertIn("Recent errors", output)
        self.assertNotIn("Disk full", output)

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

    def test_ok_message_drift_does_not_mark_check_as_changed(self):
        previous_state = {
            "updated_at": "2026-04-11T00:00:00+00:00",
            "checks": {
                "hardware": {"status": "OK", "message": "Hardware healthy — Load 0.20/8, Mem 90% free, Up 2d 18h 18m", "first_seen": None, "last_seen": None},
            },
        }
        results = {
            "hardware": lambda: Result("hardware", "OK", "Hardware healthy — Load 0.21/8, Mem 90% free, Up 2d 18h 19m"),
        }

        with tempfile.TemporaryDirectory() as td, patch("whatbroke.cli._STATE_DIR", td), patch("whatbroke.cli._STATE_FILE", os.path.join(td, "state.json")), patch("whatbroke.cli._load_state", return_value=previous_state):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = _run_single(results, self._args())
            output = buf.getvalue()

        self.assertEqual(code, 0)
        self.assertNotIn("[CHANGED]", output)
        self.assertNotIn("changed since last run", output)

    def test_summary_includes_broke_counts(self):
        results = {
            "disk": lambda: Result("disk", "CRIT", "Disk full"),
            "services": lambda: Result("services", "BROKE", "1 failed unit(s)"),
            "logs": lambda: Result("logs", "WARN", "Recent errors"),
        }

        with tempfile.TemporaryDirectory() as td, patch("whatbroke.cli._STATE_DIR", td), patch("whatbroke.cli._STATE_FILE", os.path.join(td, "state.json")):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = _run_single(results, self._args())
            output = buf.getvalue()

        self.assertEqual(code, 3)
        self.assertIn("1 CRIT", output)
        self.assertIn("1 BROKE", output)
        self.assertIn("1 WARN", output)

    def test_json_broken_only_filters_out_ok_results(self):
        results = {
            "disk": lambda: Result("disk", "CRIT", "Disk full"),
            "security": lambda: Result("security", "OK", "Healthy"),
        }

        with tempfile.TemporaryDirectory() as td, patch("whatbroke.cli._STATE_DIR", td), patch("whatbroke.cli._STATE_FILE", os.path.join(td, "state.json")):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = _run_single(results, self._args(json=True, broken_only=True))
            payload = json.loads(buf.getvalue())

        self.assertEqual(code, 3)
        self.assertEqual([item["name"] for item in payload], ["disk"])

    def test_nagios_output_uses_single_line_and_plugin_exit_code(self):
        results = {
            "disk": lambda: Result("disk", "CRIT", "Disk full"),
            "logs": lambda: Result("logs", "WARN", "Recent errors"),
            "security": lambda: Result("security", "OK", "Healthy"),
        }

        with tempfile.TemporaryDirectory() as td, patch("whatbroke.cli._STATE_DIR", td), patch("whatbroke.cli._STATE_FILE", os.path.join(td, "state.json")):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = _run_single(results, self._args(nagios=True))
            output = buf.getvalue().strip()

        self.assertEqual(code, 2)
        self.assertTrue(output.startswith("WHATBROKE CRITICAL - disk:CRIT Disk full, logs:WARN Recent errors |"))
        self.assertIn("checks=3;;;0;", output)
        self.assertIn("crit=1;;;0;", output)

    def test_nagios_empty_selection_reports_unknown(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = _run_single({}, self._args(nagios=True))

        self.assertEqual(code, 3)
        self.assertEqual(buf.getvalue().strip(), "WHATBROKE UNKNOWN - no checks selected | checks=0;;;0;")

    def test_run_single_handles_empty_check_selection(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = _run_single({}, self._args())

        self.assertEqual(code, 0)
        self.assertIn("No checks selected.", buf.getvalue())

    def test_json_mode_handles_empty_check_selection(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = _run_single({}, self._args(json=True))
        payload = json.loads(buf.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(payload, [])

    def test_json_diff_only_outputs_changed_broken_results(self):
        previous_state = {
            "updated_at": "2026-04-11T00:00:00+00:00",
            "checks": {
                "firewall": {"status": "WARN", "message": "Firewall status unclear", "first_seen": None, "last_seen": None},
                "services": {"status": "BROKE", "message": "1 failed unit(s)", "first_seen": None, "last_seen": None},
            },
        }
        results = {
            "firewall": lambda: Result("firewall", "CRIT", "No active firewall rules detected"),
            "services": lambda: Result("services", "BROKE", "2 failed unit(s)"),
            "security": lambda: Result("security", "OK", "Healthy"),
            "users": lambda: Result("users", "WARN", "Empty password detected"),
        }

        with tempfile.TemporaryDirectory() as td, patch("whatbroke.cli._STATE_DIR", td), patch("whatbroke.cli._STATE_FILE", os.path.join(td, "state.json")), patch("whatbroke.cli._load_state", return_value=previous_state):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = _run_single(results, self._args(json=True, diff=True))
            payload = json.loads(buf.getvalue())

        self.assertEqual(code, 3)
        self.assertEqual([item["name"] for item in payload], ["firewall", "services", "users"])
        self.assertEqual([item["change"] for item in payload], ["worse", "changed", "new"])

    def test_json_diff_returns_zero_with_empty_delta_payload(self):
        previous_state = {
            "updated_at": "2026-04-11T00:00:00+00:00",
            "checks": {
                "services": {"status": "BROKE", "message": "1 failed unit(s)", "first_seen": None, "last_seen": None},
            },
        }
        results = {
            "services": lambda: Result("services", "BROKE", "1 failed unit(s)"),
        }

        with tempfile.TemporaryDirectory() as td, patch("whatbroke.cli._STATE_DIR", td), patch("whatbroke.cli._STATE_FILE", os.path.join(td, "state.json")), patch("whatbroke.cli._load_state", return_value=previous_state):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = _run_single(results, self._args(json=True, diff=True))
            payload = json.loads(buf.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(payload, [])


class CliModuleExecutionTests(unittest.TestCase):
    def test_python_m_entrypoint_delegates_to_cli_main(self):
        with patch("whatbroke.cli.main") as mock_main:
            runpy.run_module("whatbroke", run_name="__main__")

        mock_main.assert_called_once_with()


class CliFilterParsingTests(unittest.TestCase):
    def test_main_lists_checks_and_exits(self):
        with patch("whatbroke.cli.discover_checks", return_value={"logs": lambda: Result("logs", "OK", "healthy"), "disk": lambda: Result("disk", "OK", "healthy")}), \
             patch("sys.argv", ["whatbroke", "--list-checks"]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as ctx:
                main()

        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(buf.getvalue().splitlines(), ["disk", "logs"])

    def test_main_lists_checks_with_descriptions_in_verbose_mode(self):
        def disk_check():
            """Disk capacity and storage health."""
            return Result("disk", "OK", "healthy")

        def logs_check():
            """Critical journal errors and noisy failures."""
            return Result("logs", "OK", "healthy")

        with patch("whatbroke.cli.discover_checks", return_value={"logs": logs_check, "disk": disk_check}), \
             patch("sys.argv", ["whatbroke", "--list-checks", "--verbose"]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as ctx:
                main()

        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(
            buf.getvalue().splitlines(),
            [
                "disk: Disk capacity and storage health.",
                "logs: Critical journal errors and noisy failures.",
            ],
        )

    def test_main_lists_checks_as_json(self):
        def disk_check():
            """Disk capacity and storage health."""
            return Result("disk", "OK", "healthy")

        def logs_check():
            """Critical journal errors and noisy failures."""
            return Result("logs", "OK", "healthy")

        with patch("whatbroke.cli.discover_checks", return_value={"logs": logs_check, "disk": disk_check}), \
             patch("sys.argv", ["whatbroke", "--list-checks", "--json"]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as ctx:
                main()

        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(
            json.loads(buf.getvalue()),
            [
                {"name": "disk", "description": "Disk capacity and storage health."},
                {"name": "logs", "description": "Critical journal errors and noisy failures."},
            ],
        )

    def test_main_lists_checks_after_only_filter(self):
        with patch("whatbroke.cli.discover_checks", return_value={
            "logs": lambda: Result("logs", "OK", "healthy"),
            "disk": lambda: Result("disk", "OK", "healthy"),
            "security": lambda: Result("security", "OK", "healthy"),
        }), patch("sys.argv", ["whatbroke", "--list-checks", "--only", " security , disk "]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as ctx:
                main()

        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(buf.getvalue().splitlines(), ["disk", "security"])

    def test_main_lists_checks_after_skip_filter(self):
        with patch("whatbroke.cli.discover_checks", return_value={
            "logs": lambda: Result("logs", "OK", "healthy"),
            "disk": lambda: Result("disk", "OK", "healthy"),
            "security": lambda: Result("security", "OK", "healthy"),
        }), patch("sys.argv", ["whatbroke", "--list-checks", "--skip", "logs"]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as ctx:
                main()

        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(buf.getvalue().splitlines(), ["disk", "security"])

    def test_parse_check_filter_trims_whitespace(self):
        parsed = _parse_check_filter(" disk, security ,logs ", {"disk", "security", "logs"}, "--only")

        self.assertEqual(parsed, {"disk", "security", "logs"})

    def test_parse_check_filter_rejects_unknown_checks(self):
        with self.assertRaises(SystemExit) as ctx:
            _parse_check_filter("disk,typo", {"disk", "logs"}, "--only")

        self.assertIn("Unknown check name(s) for --only: typo", str(ctx.exception))
        self.assertIn("Available checks: disk, logs", str(ctx.exception))

    def test_main_rejects_unknown_skip_checks_before_running(self):
        with patch("whatbroke.cli.discover_checks", return_value={"disk": lambda: Result("disk", "OK", "healthy")}), \
             patch("sys.argv", ["whatbroke", "--skip", " typo "]):
            with self.assertRaises(SystemExit) as ctx:
                main()

        self.assertIn("Unknown check name(s) for --skip: typo", str(ctx.exception))

    def test_main_handles_filters_that_leave_no_checks(self):
        with patch("whatbroke.cli.discover_checks", return_value={"disk": lambda: Result("disk", "OK", "healthy")}), \
             patch("sys.argv", ["whatbroke", "--only", "disk", "--skip", "disk"]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as ctx:
                main()

        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("No checks selected.", buf.getvalue())

    def test_main_auto_disables_color_for_non_tty_compact_output(self):
        with patch("whatbroke.cli.discover_checks", return_value={"firewall": lambda: Result("firewall", "WARN", "Firewall status unclear")}), \
             patch("sys.argv", ["whatbroke", "--compact", "--no-state"]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as ctx:
                main()

        self.assertEqual(ctx.exception.code, 1)
        self.assertEqual(buf.getvalue().strip(), "firewall:WARN Firewall status unclear")
        self.assertNotIn("\x1b", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
