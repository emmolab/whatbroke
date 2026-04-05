import unittest
from unittest.mock import patch

from whatbroke.checks import security


class SecurityThresholdTests(unittest.TestCase):
    @patch("whatbroke.checks.security._check_failed_logins", return_value=(3, []))
    @patch("whatbroke.checks.security._check_updates", return_value={"count": 8, "has_security": False})
    @patch("whatbroke.checks.security._check_ssh_config", return_value=[])
    @patch("whatbroke.checks.security._check_expiring_certs", return_value=[])
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
    @patch("whatbroke.checks.security._check_selinux_apparmor", return_value=([], ["AppArmor: enabled, but no profiles are currently in enforce mode"]))
    @patch("whatbroke.checks.security._check_entropy", return_value=(256, False))
    def test_apparmor_zero_enforce_is_context_not_warning(self, *_mocks):
        result = security.check()

        self.assertEqual(result.status, "OK")
        self.assertIn("no profiles are currently in enforce mode", " ".join(result.details).lower())


if __name__ == "__main__":
    unittest.main()
