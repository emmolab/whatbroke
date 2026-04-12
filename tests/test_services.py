import unittest
from unittest.mock import patch

from whatbroke.checks import services


class ServicesZombieTests(unittest.TestCase):
    def test_parse_ps_zombies_extracts_richer_fields(self):
        sample = """\
  PID  PPID STAT ELAPSED COMMAND
    1     0 Ss   999999 systemd
  200    10 Z    30     worker
  201    10 Zs   900    gunicorn
"""

        zombies = services._parse_ps_zombies(sample)

        self.assertEqual(
            zombies,
            [
                {"pid": 200, "ppid": 10, "stat": "Z", "etimes": 30, "comm": "worker"},
                {"pid": 201, "ppid": 10, "stat": "Zs", "etimes": 900, "comm": "gunicorn"},
            ],
        )

    def test_summarize_zombies_separates_transient_from_stale(self):
        zombies = [
            {"pid": 200, "ppid": 10, "stat": "Z", "etimes": 30, "comm": "worker"},
            {"pid": 201, "ppid": 10, "stat": "Zs", "etimes": 900, "comm": "gunicorn"},
            {"pid": 202, "ppid": 11, "stat": "Z", "etimes": 1200, "comm": "gunicorn"},
        ]

        summary = services._summarize_zombies(zombies)

        self.assertEqual(len(summary["transient"]), 1)
        self.assertEqual(len(summary["stale"]), 2)
        self.assertEqual(summary["parent_counts"][10], 1)
        self.assertEqual(summary["commands"]["gunicorn"], 2)
        self.assertEqual(summary["oldest"][0]["pid"], 202)

    @patch("whatbroke.checks.services._check_failed_systemd_services", return_value=[])
    @patch("whatbroke.checks.services._check_zombie_processes", return_value={"all": [], "stale": [], "transient": [], "parent_counts": {}, "commands": {}, "oldest": []})
    @patch("whatbroke.checks.services._check_pkg_manager_locks", return_value=([], ["Ignoring idle apt lock file: /var/lib/dpkg/lock-frontend"], []))
    @patch("whatbroke.checks.services._check_listening_ports", return_value=[])
    def test_idle_apt_lock_file_is_not_alerted(self, *_mocks):
        result = services.check()

        self.assertEqual(result.status, "OK")
        self.assertIn("Ignoring idle apt lock file", " ".join(result.details))

    @patch("whatbroke.checks.services._check_failed_systemd_services", return_value=["cron.service"])
    @patch("whatbroke.checks.services._check_zombie_processes", return_value={"all": [], "stale": [], "transient": [], "parent_counts": {}, "commands": {}, "oldest": []})
    @patch("whatbroke.checks.services._check_pkg_manager_locks", return_value=([], ["Ignoring idle apt lock file: /var/lib/dpkg/lock-frontend"], []))
    @patch("whatbroke.checks.services._check_listening_ports", return_value=[("tcp", "0.0.0.0", "22")])
    def test_non_ok_result_suppresses_low_signal_service_details(self, *_mocks):
        result = services.check()

        self.assertEqual(result.status, "CRIT")
        self.assertIn("Failed unit: cron.service", result.details)
        self.assertNotIn("Processes: no zombies", result.details)
        self.assertNotIn("Ignoring idle apt lock file: /var/lib/dpkg/lock-frontend", result.details)
        self.assertNotIn("Listening sockets: 1", result.details)

    @patch("whatbroke.checks.services._file_has_live_holder", return_value=True)
    def test_live_lock_holder_is_reported(self, *_mocks):
        issues, notes, remediation = services._check_pkg_manager_locks()

        self.assertTrue(any("transaction in progress" in issue for issue in issues))
        self.assertTrue(any("Wait for the active" in item for item in remediation))


if __name__ == "__main__":
    unittest.main()
