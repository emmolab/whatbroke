import unittest
from unittest.mock import patch

from whatbroke.checks import mail


class MailCheckTests(unittest.TestCase):
    @patch("whatbroke.checks.mail._run")
    def test_detect_mta_ignores_msmtp_client_only_hosts(self, mock_run):
        def fake_run(cmd, timeout=10):
            if cmd[:2] == ["systemctl", "cat"]:
                return 1, "", ""
            if cmd[:1] == ["which"] and cmd[1] == "msmtp":
                return 0, "/usr/bin/msmtp\n", ""
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


if __name__ == "__main__":
    unittest.main()
