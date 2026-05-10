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

    @patch("whatbroke.checks.firewall._probe_nftables", return_value=(True, 5, "nftables: 5 rule(s)"))
    @patch("whatbroke.checks.firewall._probe_firewalld", return_value=(False, "firewalld: installed but not running"))
    @patch("whatbroke.checks.firewall._probe_ufw", return_value=(False, "ufw: inactive"))
    def test_check_keeps_inactive_secondary_backends_contextual_when_primary_firewall_is_active(self, *_mocks):
        result = firewall.check()

        self.assertEqual(result.status, "OK")
        self.assertEqual(result.message, "Firewall active")
        self.assertIn("nftables: 5 rule(s)", result.details)
        self.assertIn("ufw: inactive  (inactive backend, another firewall appears active)", result.details)
        self.assertIn("firewalld: installed but not running  (inactive backend, another firewall appears active)", result.details)

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

    @patch("whatbroke.checks.firewall._probe_nftables", return_value=(False, None, ""))
    @patch("whatbroke.checks.firewall._probe_firewalld", return_value=(None, ""))
    @patch("whatbroke.checks.firewall._probe_iptables", return_value=(False, 0, ""))
    @patch("whatbroke.checks.firewall._probe_ufw", return_value=(None, "ufw: installed/enabled (run with sudo to confirm live status)"))
    def test_check_reports_unconfirmed_firewall_context_when_ufw_needs_privilege(self, *_mocks):
        result = firewall.check()

        self.assertEqual(result.status, "WARN")
        self.assertEqual(result.message, "Firewall present but live status could not be confirmed without privilege")
        self.assertIn("ufw: installed/enabled (run with sudo to confirm live status)", result.details)
        self.assertNotIn("No active firewall rules detected", result.details)
        self.assertIn("Re-run with sudo before changing firewall state", result.remediation)
        self.assertIn("sudo ufw status verbose", result.remediation)

    @patch("whatbroke.checks.firewall._probe_nftables", return_value=(None, None, "nftables: installed (ruleset requires root to inspect)"))
    @patch("whatbroke.checks.firewall._probe_firewalld", return_value=(None, ""))
    @patch("whatbroke.checks.firewall._probe_ufw", return_value=(None, ""))
    def test_check_reports_unconfirmed_firewall_context_when_nftables_needs_privilege(self, *_mocks):
        result = firewall.check()

        self.assertEqual(result.status, "WARN")
        self.assertEqual(result.message, "Firewall present but live status could not be confirmed without privilege")
        self.assertIn("nftables: installed (ruleset requires root to inspect)", result.details)
        self.assertNotIn("No active firewall rules detected", result.details)
        self.assertIn("Re-run with sudo before changing firewall state", result.remediation)
        self.assertIn("sudo nft list ruleset", result.remediation)

    @patch("whatbroke.checks.firewall._probe_nftables", return_value=(None, None, "nftables: installed (ruleset requires root to inspect)"))
    @patch("whatbroke.checks.firewall._probe_firewalld", return_value=(False, "firewalld: installed but not running"))
    @patch("whatbroke.checks.firewall._probe_ufw", return_value=(None, ""))
    def test_check_keeps_inactive_backends_out_of_summary_when_firewall_state_is_unconfirmed(self, *_mocks):
        result = firewall.check()

        self.assertEqual(result.status, "WARN")
        self.assertEqual(result.message, "Firewall present but live status could not be confirmed without privilege")
        self.assertIn("firewalld: installed but not running", result.details)
        self.assertNotIn("installed but not running", result.message)

    @patch("whatbroke.checks.firewall._run", return_value=(1, "", "Operation not permitted"))
    @patch("whatbroke.checks.firewall.shutil.which", return_value="/usr/sbin/nft")
    def test_probe_nftables_returns_unconfirmed_when_ruleset_requires_root(self, *_mocks):
        active, rules, detail = firewall._probe_nftables()

        self.assertIsNone(active)
        self.assertIsNone(rules)
        self.assertEqual(detail, "nftables: installed (ruleset requires root to inspect)")

    @patch("whatbroke.checks.firewall._service_active", return_value=True)
    @patch("whatbroke.checks.firewall.shutil.which", return_value=None)
    def test_probe_firewalld_reports_unconfirmed_when_service_is_active_but_cli_missing(self, *_mocks):
        active, detail = firewall._probe_firewalld()

        self.assertIsNone(active)
        self.assertEqual(detail, "firewalld: service active (firewall-cmd unavailable to confirm state)")

    @patch("whatbroke.checks.firewall._service_active", return_value=True)
    @patch("whatbroke.checks.firewall._run", return_value=(1, "", "Failed to connect to socket /run/dbus/system_bus_socket: Permission denied"))
    @patch("whatbroke.checks.firewall.shutil.which", return_value="/usr/bin/firewall-cmd")
    def test_probe_firewalld_reports_unconfirmed_when_state_lookup_needs_privilege(self, *_mocks):
        active, detail = firewall._probe_firewalld()

        self.assertIsNone(active)
        self.assertEqual(detail, "firewalld: service active (run with sudo to confirm daemon state)")

    @patch("whatbroke.checks.firewall._service_active", return_value=True)
    @patch("whatbroke.checks.firewall._run", return_value=(1, "not running\n", ""))
    @patch("whatbroke.checks.firewall.shutil.which", return_value="/usr/bin/firewall-cmd")
    def test_probe_firewalld_reports_unconfirmed_when_service_is_active_but_state_lookup_fails(self, *_mocks):
        active, detail = firewall._probe_firewalld()

        self.assertIsNone(active)
        self.assertEqual(detail, "firewalld: service active (daemon state lookup failed)")


if __name__ == "__main__":
    unittest.main()
