import unittest
from unittest.mock import patch

from whatbroke.checks import scheduled


class ScheduledCheckTests(unittest.TestCase):
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
