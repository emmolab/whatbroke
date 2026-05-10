import unittest
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

from whatbroke.checks import security


class SecuritySshConfigTests(unittest.TestCase):
    @patch("whatbroke.checks.security.shutil.which", return_value="/usr/sbin/sshd")
    @patch("whatbroke.checks.security._run")
    def test_ssh_config_prefers_effective_sshd_settings(self, run_mock, _which_mock):
        run_mock.return_value = MagicMock(
            returncode=0,
            stdout="permitrootlogin yes\npasswordauthentication yes\n",
        )

        issues = security._check_ssh_config()

        self.assertEqual(issues, ["root-login", "password-auth"])
        run_mock.assert_called_once()
        self.assertEqual(run_mock.call_args.args[0][:3], ["sshd", "-T", "-f"])

    @patch("whatbroke.checks.security.shutil.which", return_value="/usr/sbin/sshd")
    @patch("whatbroke.checks.security.os.path.exists", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data="PermitRootLogin yes\nPasswordAuthentication yes\n")
    @patch("whatbroke.checks.security._run")
    def test_ssh_config_falls_back_to_file_when_sshd_t_fails(self, run_mock, _open_mock, _exists_mock, _which_mock):
        run_mock.return_value = MagicMock(returncode=1, stdout="", stderr="bad config")

        issues = security._check_ssh_config()

        self.assertEqual(issues, ["root-login", "password-auth"])


class SecurityFailedLoginParsingTests(unittest.TestCase):
    @patch("whatbroke.checks.security.os.path.exists", return_value=True)
    @patch("whatbroke.checks.security._run")
    def test_failed_login_parser_counts_ssh_failures_only(self, run_mock, _exists_mock):
        run_mock.return_value = MagicMock(
            returncode=0,
            stdout=(
                "Apr 30 08:00:00 host sshd[123]: Failed password for root from 1.2.3.4 port 22 ssh2\n"
                "Apr 30 08:00:01 host sudo: pam_unix(sudo:auth): authentication failure; logname= user=alice\n"
                "Apr 30 08:00:02 host sshd[124]: Invalid user admin from 5.6.7.8 port 22\n"
                "Apr 30 08:00:03 host su: FAILED su for root by bob\n"
            ),
        )

        count, samples = security._check_failed_logins()

        self.assertEqual(count, 2)
        self.assertEqual(len(samples), 2)
        self.assertTrue(all("sshd" in sample.lower() for sample in samples))

    @patch("whatbroke.checks.security.os.path.exists", return_value=False)
    @patch("whatbroke.checks.security._run")
    def test_failed_login_parser_falls_back_to_journalctl_when_auth_logs_absent(self, run_mock, _exists_mock):
        run_mock.return_value = MagicMock(
            returncode=0,
            stdout=(
                "Apr 30 08:00:00 host sshd[123]: Failed password for root from 1.2.3.4 port 22 ssh2\n"
                "Apr 30 08:00:01 host sshd[124]: Invalid user admin from 5.6.7.8 port 22\n"
                "Apr 30 08:00:02 host systemd[1]: Started Session 1 of user root.\n"
            ),
        )

        count, samples = security._check_failed_logins()

        self.assertEqual(count, 2)
        self.assertEqual(len(samples), 2)
        self.assertTrue(all("sshd" in sample.lower() for sample in samples))
        self.assertEqual(run_mock.call_args.args[0][:2], ["journalctl", "--since"])


class SecurityLetsEncryptHelpersTests(unittest.TestCase):
    @patch("whatbroke.checks.security.Path.read_text", autospec=True)
    @patch("whatbroke.checks.security.Path.exists", autospec=True)
    def test_certbot_cron_detection_accepts_renew_job(self, exists_mock, read_text_mock):
        cron_file = Path("/etc/cron.d/certbot")

        def fake_exists(path_obj):
            return path_obj == cron_file

        exists_mock.side_effect = fake_exists
        read_text_mock.return_value = "0 */12 * * * root certbot renew -q\n"

        self.assertTrue(security._has_certbot_renewal_cron())


class SecurityThresholdTests(unittest.TestCase):
    @patch("whatbroke.checks.security._check_failed_logins", return_value=(3, []))
    @patch("whatbroke.checks.security._check_updates", return_value={"count": 8, "has_security": False})
    @patch("whatbroke.checks.security._check_ssh_config", return_value=[])
    @patch("whatbroke.checks.security._check_expiring_certs", return_value=[])
    @patch("whatbroke.checks.security._check_letsencrypt_state", return_value={"managed": 0, "earliest_days": None, "notes": [], "issues": [], "remediation": []})
    @patch("whatbroke.checks.security._check_selinux_apparmor", return_value=([], []))
    @patch("whatbroke.checks.security._check_entropy", return_value=(256, False))
    def test_small_nonsecurity_update_backlog_is_informational(self, *_mocks):
        result = security.check()

        self.assertEqual(result.status, "OK")
        self.assertIn("Updates: 8 packages pending (informational)", result.details)

    @patch("whatbroke.checks.security._check_failed_logins", return_value=(3, []))
    @patch("whatbroke.checks.security._check_updates", return_value={"count": 12, "has_security": True})
    @patch("whatbroke.checks.security._check_ssh_config", return_value=[])
    @patch("whatbroke.checks.security._check_expiring_certs", return_value=[])
    @patch("whatbroke.checks.security._check_letsencrypt_state", return_value={"managed": 0, "earliest_days": None, "notes": [], "issues": [], "remediation": []})
    @patch("whatbroke.checks.security._check_selinux_apparmor", return_value=([], []))
    @patch("whatbroke.checks.security._check_entropy", return_value=(256, False))
    def test_security_updates_still_raise_warning(self, *_mocks):
        result = security.check()

        self.assertEqual(result.status, "WARN")
        self.assertIn("security updates available", result.details[1].lower())

    @patch("whatbroke.checks.security._check_failed_logins", return_value=(0, []))
    @patch("whatbroke.checks.security._check_updates", return_value={})
    @patch("whatbroke.checks.security._check_ssh_config", return_value=[])
    @patch("whatbroke.checks.security._check_expiring_certs", return_value=[])
    @patch("whatbroke.checks.security._check_letsencrypt_state", return_value={"managed": 0, "earliest_days": None, "notes": [], "issues": [], "remediation": []})
    @patch("whatbroke.checks.security._check_selinux_apparmor", return_value=([], ["AppArmor: enabled, but no profiles are currently in enforce mode"]))
    @patch("whatbroke.checks.security._check_entropy", return_value=(256, False))
    def test_apparmor_zero_enforce_is_context_not_warning(self, *_mocks):
        result = security.check()

        self.assertEqual(result.status, "OK")
        self.assertIn("no profiles are currently in enforce mode", " ".join(result.details).lower())

    @patch("whatbroke.checks.security._check_failed_logins", return_value=(0, []))
    @patch("whatbroke.checks.security._check_updates", return_value={})
    @patch("whatbroke.checks.security._check_ssh_config", return_value=[])
    @patch("whatbroke.checks.security._check_expiring_certs", return_value=[])
    @patch(
        "whatbroke.checks.security._check_letsencrypt_state",
        return_value={
            "managed": 2,
            "earliest_days": 41,
            "notes": ["Let's Encrypt: 2 managed lineage(s); earliest expiry in 41d"],
            "issues": [],
            "remediation": [],
        },
    )
    @patch("whatbroke.checks.security._check_selinux_apparmor", return_value=([], []))
    @patch("whatbroke.checks.security._check_entropy", return_value=(256, False))
    def test_letsencrypt_inventory_is_context_when_healthy(self, *_mocks):
        result = security.check()

        self.assertEqual(result.status, "OK")
        self.assertIn("earliest expiry in 41d", " ".join(result.details))

    @patch("whatbroke.checks.security._check_failed_logins", return_value=(0, []))
    @patch("whatbroke.checks.security._check_updates", return_value={})
    @patch("whatbroke.checks.security._check_ssh_config", return_value=[])
    @patch("whatbroke.checks.security._check_expiring_certs", return_value=[])
    @patch(
        "whatbroke.checks.security._check_letsencrypt_state",
        return_value={
            "managed": 1,
            "earliest_days": 17,
            "notes": [],
            "issues": ["Let's Encrypt: certbot renewal timer is not fully active (disabled, inactive)"],
            "remediation": ["Enable/start certbot.timer or provide an equivalent renewal job"],
        },
    )
    @patch("whatbroke.checks.security._check_selinux_apparmor", return_value=([], []))
    @patch("whatbroke.checks.security._check_entropy", return_value=(256, False))
    def test_letsencrypt_operational_issue_raises_warning(self, *_mocks):
        result = security.check()

        self.assertEqual(result.status, "WARN")
        self.assertIn("Let's Encrypt state to review", result.message)
        self.assertIn("certbot.timer", result.remediation)

    @patch("whatbroke.checks.security.shutil.which", return_value="/bin/systemctl")
    @patch("whatbroke.checks.security._has_certbot_renewal_cron", return_value=True)
    @patch("whatbroke.checks.security._run")
    @patch("whatbroke.checks.security.Path.glob", return_value=[Path("/etc/letsencrypt/renewal/example.conf")])
    @patch("whatbroke.checks.security.Path.exists", autospec=True)
    def test_letsencrypt_timer_warning_is_suppressed_when_cron_exists(self, exists_mock, _glob_mock, run_mock, _cron_mock, _which_mock):
        def fake_exists(path_obj):
            return str(path_obj) == "/etc/letsencrypt/renewal"

        exists_mock.side_effect = fake_exists
        run_mock.side_effect = [
            MagicMock(returncode=0, stdout=""),
            MagicMock(returncode=1, stdout="disabled"),
            MagicMock(returncode=3, stdout="inactive"),
        ]

        state = security._check_letsencrypt_state()

        self.assertEqual(state["issues"], [])
        self.assertIn("cron-based renewal job exists", " ".join(state["notes"]))

    @patch("whatbroke.checks.security._check_failed_logins", return_value=(0, []))
    @patch("whatbroke.checks.security._check_updates", return_value={})
    @patch("whatbroke.checks.security._check_ssh_config", return_value=[])
    @patch("whatbroke.checks.security._check_expiring_certs", return_value=[])
    @patch("whatbroke.checks.security._check_letsencrypt_state", return_value={"managed": 0, "earliest_days": None, "notes": [], "issues": [], "remediation": []})
    @patch("whatbroke.checks.security._check_selinux_apparmor", return_value=([], []))
    @patch("whatbroke.checks.security._check_reboot_required", return_value={"required": True, "details": ["Reboot required marker present: /run/reboot-required"], "packages": ["linux-image"], "source": "/run/reboot-required"})
    @patch("whatbroke.checks.security._check_entropy", return_value=(256, False))
    def test_explicit_reboot_required_raises_warning(self, *_mocks):
        result = security.check()

        self.assertEqual(result.status, "WARN")
        self.assertIn("reboot pending", result.message)
        self.assertIn("Reboot required marker present", " ".join(result.details))
        self.assertIn("controlled reboot", result.remediation)

    @patch("whatbroke.checks.security._check_failed_logins", return_value=(0, []))
    @patch("whatbroke.checks.security._check_updates", return_value={})
    @patch("whatbroke.checks.security._check_ssh_config", return_value=[])
    @patch("whatbroke.checks.security._check_expiring_certs", return_value=[])
    @patch("whatbroke.checks.security._check_letsencrypt_state", return_value={"managed": 0, "earliest_days": None, "notes": [], "issues": [], "remediation": []})
    @patch("whatbroke.checks.security._check_selinux_apparmor", return_value=([], []))
    @patch("whatbroke.checks.security._check_reboot_required", return_value={"required": False, "details": [], "packages": [], "source": None})
    @patch("whatbroke.checks.security._check_entropy", return_value=(256, False))
    def test_clean_host_reports_no_explicit_reboot_signal(self, *_mocks):
        result = security.check()

        self.assertEqual(result.status, "OK")
        self.assertIn("Reboot status: no explicit reboot-required signal detected", result.details)


class SecurityPackageManagerDetectionTests(unittest.TestCase):
    @patch("whatbroke.checks.security._detect_package_kind", return_value="rpm")
    @patch("whatbroke.checks.security.shutil.which")
    @patch("whatbroke.checks.security._run")
    def test_update_check_skips_apt_on_mixed_tool_rpm_hosts(self, run_mock, which_mock, _detect_mock):
        which_mock.side_effect = lambda tool: {
            "apt": "/usr/bin/apt",
            "dnf": "/usr/bin/dnf",
        }.get(tool)
        run_mock.return_value = MagicMock(returncode=0, stdout="", stderr="")

        security._check_updates()

        self.assertTrue(run_mock.called)
        self.assertEqual(run_mock.call_args.args[0][0], "dnf")

    @patch("whatbroke.checks.security._detect_package_kind", return_value="rpm")
    @patch("whatbroke.checks.security.shutil.which")
    @patch("whatbroke.checks.security._run")
    def test_update_check_counts_rpm_updates_from_dnf(self, run_mock, which_mock, _detect_mock):
        which_mock.side_effect = lambda tool: {
            "apt": "/usr/bin/apt",
            "dnf": "/usr/bin/dnf",
        }.get(tool)
        run_mock.return_value = MagicMock(
            returncode=100,
            stdout="pkg-a.x86_64 1.2 repo\npkg-b.noarch 3.4 repo\n",
            stderr="",
        )

        updates = security._check_updates()

        self.assertEqual(updates, {"count": 2, "has_security": False})
        self.assertEqual(run_mock.call_args.args[0], ["dnf", "check-update"])


if __name__ == "__main__":
    unittest.main()
