import unittest
from unittest.mock import patch

from whatbroke.checks import security


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


if __name__ == "__main__":
    unittest.main()
