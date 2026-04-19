import unittest
from types import SimpleNamespace
from unittest.mock import patch

from whatbroke.checks import containers


class ContainersTests(unittest.TestCase):
    def test_parse_exit_code_prefers_inspect_value(self):
        self.assertEqual(containers._parse_exit_code("Exited (0) 2 hours ago", "137"), 137)

    def test_parse_exit_code_falls_back_to_status_text(self):
        self.assertEqual(containers._parse_exit_code("Exited (2) 5 minutes ago"), 2)

    @patch("whatbroke.checks.containers._run")
    def test_get_exited_containers_ignores_clean_exits(self, mock_run):
        mock_run.side_effect = [
            SimpleNamespace(
                stdout=(
                    "abc123456789\tbackup-job\tExited (0) 2 hours ago\talpine\n"
                    "def987654321\tapi\tExited (1) 5 minutes ago\tmyapp:latest\n"
                ),
                returncode=0,
            ),
            SimpleNamespace(stdout="0\n", returncode=0),
            SimpleNamespace(stdout="1\n", returncode=0),
        ]

        exited = containers._get_exited_containers()

        self.assertEqual(len(exited), 1)
        self.assertIn("api", exited[0])
        self.assertNotIn("backup-job", "\n".join(exited))

    @patch("whatbroke.checks.containers._check_libvirt", return_value=[])
    @patch("whatbroke.checks.containers._check_kubernetes", return_value=[])
    @patch("whatbroke.checks.containers._get_restarting_containers", return_value=[])
    @patch("whatbroke.checks.containers._get_exited_containers", return_value=[])
    @patch("whatbroke.checks.containers._docker_available", return_value=True)
    def test_check_stays_ok_when_only_clean_exits_were_filtered_out(self, *_mocks):
        result = containers.check()

        self.assertEqual(result.status, "OK")
        self.assertIn("All container/virtualisation checks passed", result.message)


if __name__ == "__main__":
    unittest.main()
