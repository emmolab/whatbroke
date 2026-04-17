import io
import unittest
from unittest.mock import patch

from whatbroke.checks import scheduled


class ScheduledCheckTests(unittest.TestCase):
    def test_user_cron_parser_ignores_env_comments_and_valid_macros(self):
        self.assertIsNone(scheduled._user_cron_issue_from_line("alice", "# comment"))
        self.assertIsNone(scheduled._user_cron_issue_from_line("alice", "PATH=/usr/local/bin:/usr/bin"))
        self.assertIsNone(scheduled._user_cron_issue_from_line("alice", "@daily /usr/local/bin/backup"))
        self.assertIsNone(scheduled._user_cron_issue_from_line("alice", "*/5 * * * * /usr/local/bin/check"))

    def test_user_cron_parser_flags_malformed_entries(self):
        issue = scheduled._user_cron_issue_from_line("alice", "0 0 * * *")
        self.assertIn("malformed cron entry", issue)

        macro_issue = scheduled._user_cron_issue_from_line("alice", "@daily")
        self.assertIn("malformed cron macro entry", macro_issue)

    def test_system_cron_parser_ignores_env_and_comments(self):
        self.assertIsNone(scheduled._system_cron_issue_from_line("/etc/crontab", 1, "# comment"))
        self.assertIsNone(scheduled._system_cron_issue_from_line("/etc/crontab", 2, "MAILTO=root"))
        self.assertIsNone(scheduled._system_cron_issue_from_line("/etc/crontab", 3, "*/5 * * * * root /usr/local/bin/check"))
        self.assertIsNone(scheduled._system_cron_issue_from_line("/etc/crontab", 4, "@daily root /usr/local/bin/rotate"))

    def test_system_cron_parser_flags_malformed_entries(self):
        issue = scheduled._system_cron_issue_from_line("/etc/cron.d/app", 7, "0 0 * * * /usr/local/bin/app")
        self.assertIn("malformed system cron entry", issue)

        macro_issue = scheduled._system_cron_issue_from_line("/etc/cron.d/app", 8, "@daily root")
        self.assertIn("malformed system cron macro entry", macro_issue)

    @patch("whatbroke.checks.scheduled.os.path.isfile", return_value=True)
    @patch("whatbroke.checks.scheduled.os.path.isdir", return_value=True)
    @patch("whatbroke.checks.scheduled.os.listdir", return_value=["app"])
    def test_check_system_cron_syntax_detects_bad_cron_d_entry(self, *_mocks):
        cron_d_body = "MAILTO=root\n0 0 * * * /usr/local/bin/app\n"

        def fake_open(path, *args, **kwargs):
            if path == "/etc/crontab":
                raise FileNotFoundError(path)
            if path == "/etc/cron.d/app":
                return io.StringIO(cron_d_body)
            raise FileNotFoundError(path)

        with patch("builtins.open", side_effect=fake_open):
            issues = scheduled._check_system_cron_syntax()

        self.assertEqual(len(issues), 1)
        self.assertIn("/etc/cron.d/app:2", issues[0])

    @patch("whatbroke.checks.scheduled._run")
    def test_check_crontabs_allows_valid_user_macro_entries(self, mock_run):
        def fake_run(cmd, timeout=5):
            if cmd[:3] == ["crontab", "-l", "-u"]:
                return type("Proc", (), {"returncode": 0, "stdout": "@daily /usr/local/bin/backup\n", "stderr": ""})()
            raise AssertionError(f"unexpected command: {cmd}")

        passwd_data = "alice:x:1000:1000::/home/alice:/bin/bash\n"
        mock_run.side_effect = fake_run

        with patch("builtins.open", return_value=io.StringIO(passwd_data)):
            issues = scheduled._check_crontabs()

        self.assertEqual(issues, [])

    @patch("whatbroke.checks.scheduled._check_systemd_timers", return_value=[])
    @patch("whatbroke.checks.scheduled._list_active_timers", return_value=4)
    @patch("whatbroke.checks.scheduled._list_crontab_users", return_value=[])
    @patch("whatbroke.checks.scheduled._check_crontabs", return_value=[])
    @patch("whatbroke.checks.scheduled._system_cron_entries", return_value=[])
    @patch("whatbroke.checks.scheduled._service_exists", return_value=False)
    @patch("whatbroke.checks.scheduled._cron_service_running", return_value=False)
    def test_timer_only_host_is_not_marked_critical(self, *_mocks):
        result = scheduled.check()

        self.assertEqual(result.status, "OK")
        self.assertIn("4 systemd timer(s)", result.message)
        self.assertIn("Cron service: not installed", result.details)

    @patch("whatbroke.checks.scheduled._check_systemd_timers", return_value=[])
    @patch("whatbroke.checks.scheduled._list_active_timers", return_value=0)
    @patch("whatbroke.checks.scheduled._list_crontab_users", return_value=["alice"])
    @patch("whatbroke.checks.scheduled._check_crontabs", return_value=[])
    @patch("whatbroke.checks.scheduled._system_cron_entries", return_value=[])
    @patch("whatbroke.checks.scheduled._service_exists", return_value=True)
    @patch("whatbroke.checks.scheduled._cron_service_running", return_value=False)
    def test_inactive_cron_with_crontabs_is_critical(self, *_mocks):
        result = scheduled.check()

        self.assertEqual(result.status, "CRIT")
        self.assertIn("cron service down", result.message)
        self.assertEqual(result.remediation, "systemctl enable --now cron  (or crond on RHEL/CentOS)")

    @patch("whatbroke.checks.scheduled._check_systemd_timers", return_value=[])
    @patch("whatbroke.checks.scheduled._list_active_timers", return_value=2)
    @patch("whatbroke.checks.scheduled._list_crontab_users", return_value=[])
    @patch("whatbroke.checks.scheduled._check_crontabs", return_value=[])
    @patch("whatbroke.checks.scheduled._system_cron_entries", return_value=[])
    @patch("whatbroke.checks.scheduled._service_exists", return_value=True)
    @patch("whatbroke.checks.scheduled._cron_service_running", return_value=False)
    def test_installed_but_unused_cron_is_only_context(self, *_mocks):
        result = scheduled.check()

        self.assertEqual(result.status, "OK")
        self.assertIn("Cron service: not running (no cron jobs detected)", result.details)
        self.assertIn("2 systemd timer(s)", result.message)


if __name__ == "__main__":
    unittest.main()
