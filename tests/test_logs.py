import unittest
from unittest.mock import patch

from whatbroke.checks import logs


class LogsThresholdTests(unittest.TestCase):
    @patch("whatbroke.checks.logs._check_journal_critical", return_value=([], [f"err {i}" for i in range(5)]))
    @patch("whatbroke.checks.logs._check_oom_events", return_value=[])
    @patch("whatbroke.checks.logs._check_kernel_messages", return_value=[])
    @patch("whatbroke.checks.logs._check_application_logs", return_value=[])
    @patch("whatbroke.checks.logs._check_large_logs", return_value=[])
    def test_small_error_volume_stays_ok(self, *_mocks):
        result = logs.check()

        self.assertEqual(result.status, "OK")
        self.assertIn("below alert threshold", result.details[0])

    @patch("whatbroke.checks.logs._check_journal_critical", return_value=([], [f"Apr 1 host kernel[1]: app.service: err {i}" for i in range(25)]))
    @patch("whatbroke.checks.logs._check_oom_events", return_value=[])
    @patch("whatbroke.checks.logs._check_kernel_messages", return_value=[])
    @patch("whatbroke.checks.logs._check_application_logs", return_value=[])
    @patch("whatbroke.checks.logs._check_large_logs", return_value=[])
    def test_repeated_error_volume_warns_and_shows_top_unit(self, *_mocks):
        result = logs.check()

        self.assertEqual(result.status, "WARN")
        self.assertTrue(any("Top noisy units:" in line for line in result.details))

    @patch("whatbroke.checks.logs._check_journal_critical", return_value=([], ["kernel: [UFW BLOCK] IN=eth0"] * 50))
    @patch("whatbroke.checks.logs._check_oom_events", return_value=[])
    @patch("whatbroke.checks.logs._check_kernel_messages", return_value=["kernel: [UFW BLOCK] IN=eth0"] * 50)
    @patch("whatbroke.checks.logs._check_application_logs", return_value=[])
    @patch("whatbroke.checks.logs._check_large_logs", return_value=[])
    def test_ufw_block_spam_is_suppressed_not_alerted(self, *_mocks):
        result = logs.check()

        self.assertEqual(result.status, "OK")
        self.assertTrue(any("noise suppressed" in line.lower() for line in result.details))
        self.assertFalse(any("50 journal errors" in line for line in result.details))


if __name__ == "__main__":
    unittest.main()
