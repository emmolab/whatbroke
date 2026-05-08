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

        exited = containers._get_exited_containers("docker")

        self.assertEqual(len(exited), 1)
        self.assertIn("docker:api", exited[0])
        self.assertNotIn("backup-job", "\n".join(exited))

    @patch("whatbroke.checks.containers._check_libvirt", return_value=([], []))
    @patch("whatbroke.checks.containers._check_kubernetes", return_value=[])
    @patch("whatbroke.checks.containers._get_restarting_containers", return_value=[])
    @patch("whatbroke.checks.containers._get_exited_containers", return_value=[])
    @patch("whatbroke.checks.containers._runtime_available", side_effect=lambda runtime: runtime == "docker")
    def test_check_stays_ok_when_only_clean_exits_were_filtered_out(self, *_mocks):
        result = containers.check()

        self.assertEqual(result.status, "OK")
        self.assertIn("All container/virtualisation checks passed", result.message)

    @patch("whatbroke.checks.containers._check_libvirt", return_value=([], []))
    @patch("whatbroke.checks.containers._check_kubernetes", return_value=[])
    @patch("whatbroke.checks.containers._get_restarting_containers", return_value=[])
    @patch("whatbroke.checks.containers._get_exited_containers", return_value=["docker:api [abc123] — Exited (1) 5 minutes ago (exit 1) — image: myapp:latest"])
    @patch("whatbroke.checks.containers._runtime_available", side_effect=lambda runtime: runtime == "docker")
    def test_check_uses_conservative_remediation_for_exited_containers(self, *_mocks):
        result = containers.check()

        self.assertEqual(result.status, "WARN")
        self.assertIn("1 exited containers", result.message)
        self.assertIn("Inspect failed docker containers first", result.remediation)
        self.assertIn("Remove exited containers only after confirming", result.remediation)
        self.assertNotIn("docker rm $(docker ps -aq -f status=exited)", result.remediation)

    @patch("whatbroke.checks.containers._check_libvirt", return_value=([], []))
    @patch("whatbroke.checks.containers._check_kubernetes", return_value=[])
    @patch("whatbroke.checks.containers._get_restarting_containers", return_value=["docker:api [abc123] — Restarting (restarts: 7) — image: myapp:latest"])
    @patch("whatbroke.checks.containers._get_exited_containers", return_value=[])
    @patch("whatbroke.checks.containers._runtime_available", side_effect=lambda runtime: runtime == "docker")
    def test_check_surfaces_restart_loops_in_summary_message(self, *_mocks):
        result = containers.check()

        self.assertEqual(result.status, "WARN")
        self.assertIn("1 restarting container(s)", result.message)
        self.assertIn("Inspect docker restart loops", result.remediation)

    @patch("whatbroke.checks.containers._check_libvirt", return_value=(["VM api-vm: paused"], []))
    @patch("whatbroke.checks.containers._check_kubernetes", return_value=["Node node-1: NotReady"])
    @patch("whatbroke.checks.containers._get_restarting_containers", return_value=["docker:api [abc123] — Restarting (restarts: 7) — image: myapp:latest"])
    @patch("whatbroke.checks.containers._get_exited_containers", return_value=["docker:worker [def456] — Exited (1) 5 minutes ago (exit 1) — image: myapp:latest"])
    @patch("whatbroke.checks.containers._runtime_available", side_effect=lambda runtime: runtime == "docker")
    def test_check_aggregates_remediation_for_multiple_issue_types(self, *_mocks):
        result = containers.check()

        self.assertEqual(result.status, "CRIT")
        self.assertIn("docker logs <container>", result.remediation)
        self.assertIn("kubectl describe pod <name> -n <ns>", result.remediation)
        self.assertIn("virsh domstate <name>", result.remediation)

    @patch("whatbroke.checks.containers.os.path.exists", return_value=True)
    @patch("whatbroke.checks.containers._run")
    def test_check_libvirt_treats_shut_off_guests_as_notes(self, mock_run, _mock_exists):
        mock_run.side_effect = [
            SimpleNamespace(stdout="active\n", returncode=0),
            SimpleNamespace(
                stdout=(
                    " Id   Name          State\n"
                    "-------------------------------\n"
                    " -    build-box     shut off\n"
                ),
                returncode=0,
            ),
        ]

        issues, notes = containers._check_libvirt()

        self.assertEqual(issues, [])
        self.assertEqual(notes, ["VM build-box: shut off (not alerting by default)"])

    @patch("whatbroke.checks.containers.os.path.exists", return_value=True)
    @patch("whatbroke.checks.containers._run")
    def test_check_libvirt_flags_paused_guests(self, mock_run, _mock_exists):
        mock_run.side_effect = [
            SimpleNamespace(stdout="active\n", returncode=0),
            SimpleNamespace(
                stdout=(
                    " Id   Name          State\n"
                    "-------------------------------\n"
                    " 3    api-vm        paused\n"
                ),
                returncode=0,
            ),
        ]

        issues, notes = containers._check_libvirt()

        self.assertEqual(issues, ["VM api-vm: paused"])
        self.assertEqual(notes, [])

    @patch("whatbroke.checks.containers._check_libvirt", return_value=([], []))
    @patch("whatbroke.checks.containers._check_kubernetes", return_value=[])
    @patch("whatbroke.checks.containers._get_restarting_containers", side_effect=lambda runtime: ["podman:api [abc123] — Restarting (restarts: 3) — image: quay.io/example/api:latest"] if runtime == "podman" else [])
    @patch("whatbroke.checks.containers._get_exited_containers", side_effect=lambda runtime: ["podman:worker [def456] — Exited (125) 2 minutes ago (exit 125) — image: quay.io/example/worker:latest"] if runtime == "podman" else [])
    @patch("whatbroke.checks.containers._runtime_available", side_effect=lambda runtime: runtime == "podman")
    def test_check_supports_podman_without_docker(self, *_mocks):
        result = containers.check()

        self.assertEqual(result.status, "WARN")
        self.assertIn("podman:worker", " ".join(result.details))
        self.assertIn("podman logs <container>", result.remediation)
        self.assertIn("1 exited containers", result.message)


if __name__ == "__main__":
    unittest.main()
