import unittest
from unittest.mock import patch

from whatbroke.checks import firewall


class FirewallTests(unittest.TestCase):
    @patch("whatbroke.checks.firewall._probe_nftables", return_value=(False, None, ""))
    @patch("whatbroke.checks.firewall._probe_firewalld", return_value=(None, ""))
    @patch("whatbroke.checks.firewall._probe_iptables", return_value=(False, 0, "iptables: 0 non-default rule(s)"))
    @patch("whatbroke.checks.firewall._probe_ufw", return_value=(True, "ufw: active"))
    def test_check_reports_ok_when_ufw_is_active(self, *_mocks):
        result = firewall.check()

        self.assertEqual(result.status, "OK")
        self.assertEqual(result.message, "Firewall active")
        self.assertIn("ufw: active", result.details)

    @patch("whatbroke.checks.firewall.os.geteuid", return_value=0)
    @patch("whatbroke.checks.firewall._service_active", return_value=True)
    @patch("whatbroke.checks.firewall._run", return_value=(1, "", ""))
    @patch("whatbroke.checks.firewall.shutil.which", return_value="/usr/sbin/ufw")
    def test_probe_ufw_falls_back_to_service_state_when_status_command_fails_as_root(self, *_mocks):
        active, detail = firewall._probe_ufw()

        self.assertTrue(active)
        self.assertEqual(detail, "ufw: active (service running; status command unavailable)")

    @patch("whatbroke.checks.firewall.os.geteuid", return_value=1000)
    @patch("whatbroke.checks.firewall._ufw_enabled_in_config", return_value=True)
    @patch("whatbroke.checks.firewall._service_active", return_value=False)
    @patch("whatbroke.checks.firewall._run", return_value=(1, "", "ERROR: You need to be root to run this script"))
    @patch("whatbroke.checks.firewall.shutil.which", return_value="/usr/sbin/ufw")
    def test_probe_ufw_reports_enabled_but_unconfirmed_when_unprivileged(self, *_mocks):
        active, detail = firewall._probe_ufw()

        self.assertIsNone(active)
        self.assertEqual(detail, "ufw: installed/enabled (run with sudo to confirm live status)")

    @patch("whatbroke.checks.firewall.os.geteuid", return_value=0)
    @patch("whatbroke.checks.firewall._ufw_enabled_in_config", return_value=False)
    @patch("whatbroke.checks.firewall._service_active", return_value=False)
    @patch("whatbroke.checks.firewall._run", return_value=(1, "", ""))
    @patch("whatbroke.checks.firewall.shutil.which", return_value="/usr/sbin/ufw")
    def test_probe_ufw_reports_inactive_when_root_can_not_confirm_any_signal(self, *_mocks):
        active, detail = firewall._probe_ufw()

        self.assertFalse(active)
        self.assertEqual(detail, "ufw: inactive")


if __name__ == "__main__":
    unittest.main()
