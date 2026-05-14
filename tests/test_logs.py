import unittest
from unittest.mock import patch

from whatbroke.checks import logs


class LogsThresholdTests(unittest.TestCase):
    def test_oom_fallback_matcher_is_specific(self):
        self.assertTrue(logs._looks_like_oom_event("kernel: Out of memory: Killed process 1234 (python)"))
        self.assertTrue(logs._looks_like_oom_event("kernel: invoked oom-killer: gfp_mask=0x1100ca"))
        self.assertTrue(logs._looks_like_oom_event("kernel: Memory cgroup out of memory: Killed process 4321 (java)"))
        self.assertFalse(logs._looks_like_oom_event("systemd: classroom.service finished successfully"))
        self.assertFalse(logs._looks_like_oom_event("kernel: bloom filter resized for conntrack"))

    @patch("whatbroke.checks.logs._run")
    def test_oom_fallback_dmesg_ignores_non_oom_lines(self, mock_run):
        mock_run.side_effect = [
            type("Proc", (), {"returncode": 1, "stdout": "", "stderr": ""})(),
            type("Proc", (), {
                "returncode": 0,
                "stdout": (
                    "kernel: bloom filter resized for conntrack\n"
                    "kernel: invoked oom-killer: gfp_mask=0x1100ca\n"
                    "kernel: classroom.service finished successfully\n"
                ),
                "stderr": "",
            })(),
        ]

        events = logs._check_oom_events()

        self.assertEqual(events, ["kernel: invoked oom-killer: gfp_mask=0x1100ca"])

    @patch(
        "whatbroke.checks.logs._check_journal_critical",
        return_value=([
            "May 01 host kernel: Warning: Deprecated Hardware is detected: x86_64-v2 CPU baseline will be removed in a future major release"
        ], []),
    )
    @patch("whatbroke.checks.logs._check_oom_events", return_value=[])
    @patch("whatbroke.checks.logs._check_kernel_messages", return_value=[])
    @patch("whatbroke.checks.logs._check_application_logs", return_value=[])
    @patch("whatbroke.checks.logs._check_large_logs", return_value=[])
    def test_deprecated_hardware_journal_warning_is_deferred_not_critical(self, *_mocks):
        result = logs.check()

        self.assertEqual(result.status, "WARN")
        self.assertIn("deferred high-priority", result.message)
        self.assertTrue(any("high-priority but non-urgent" in line for line in result.details))
        self.assertFalse(any("critical/alert/emerg" in line for line in result.details))

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
