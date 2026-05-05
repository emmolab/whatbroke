import unittest
from unittest.mock import patch

from whatbroke.checks import mail


class MailCheckTests(unittest.TestCase):
    @patch("whatbroke.checks.mail.shutil.which", return_value=None)
    @patch("whatbroke.checks.mail._run")
    def test_detect_mta_ignores_msmtp_client_only_hosts(self, mock_run, _mock_which):
        def fake_run(cmd, timeout=10):
            if cmd[:2] == ["systemctl", "cat"]:
                return 1, "", ""
            return 1, "", ""

        mock_run.side_effect = fake_run

        self.assertIsNone(mail._detect_mta())

    @patch("whatbroke.checks.mail._queue_size", return_value=12)
    @patch("whatbroke.checks.mail._service_active", return_value=True)
    @patch("whatbroke.checks.mail._detect_mta", return_value="postfix")
    def test_check_reports_healthy_postfix(self, *_mocks):
        result = mail.check()

        self.assertEqual(result.status, "OK")
        self.assertIn("postfix healthy", result.message)
        self.assertIn("Queue depth: 12 messages  OK", result.details)

    @patch("whatbroke.checks.mail._detect_mta", return_value=None)
    def test_check_skips_when_no_server_mta_detected(self, *_mocks):
        result = mail.check()

        self.assertEqual(result.status, "OK")
        self.assertEqual(result.message, "No MTA detected — mail checks skipped")

    @patch("whatbroke.checks.mail._run")
    def test_opensmtpd_queue_size_reports_zero_for_empty_queue(self, mock_run):
        def fake_run(cmd, timeout=10):
            if cmd == ["smtpctl", "show", "queue"]:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        mock_run.side_effect = fake_run

        self.assertEqual(mail._opensmtpd_queue_size(), 0)

    @patch("whatbroke.checks.mail._run")
    def test_opensmtpd_queue_size_falls_back_to_stats_when_show_queue_fails(self, mock_run):
        def fake_run(cmd, timeout=10):
            if cmd == ["smtpctl", "show", "queue"]:
                return 1, "", "permission denied"
            if cmd == ["smtpctl", "show", "stats"]:
                return 0, "scheduler.envelope=2\nscheduler.envelope.incoming=9\nscheduler.envelope.expired=1\n", ""
            raise AssertionError(f"unexpected command: {cmd}")

        mock_run.side_effect = fake_run

        self.assertEqual(mail._opensmtpd_queue_size(), 3)

    def test_remediation_for_opensmtpd_uses_smtpd_unit_and_commands(self):
        remediation = mail._remediation_for_mta("opensmtpd")

        self.assertIn("journalctl -u smtpd -n 50", remediation)
        self.assertIn("Inspect queue: smtpctl show queue", remediation)
        self.assertIn("Flush queue:   smtpctl schedule all", remediation)


if __name__ == "__main__":
    unittest.main()
