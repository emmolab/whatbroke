import unittest
from unittest.mock import patch

from whatbroke.checks import sysctl


class SysctlCheckTests(unittest.TestCase):
    @patch("whatbroke.checks.sysctl._sysctl")
    def test_check_warns_on_ipv6_redirect_acceptance_when_ipv6_enabled(self, mock_sysctl):
        values = {
            "kernel.randomize_va_space": "2",
            "net.ipv4.tcp_syncookies": "1",
            "net.ipv4.conf.all.accept_redirects": "0",
            "net.ipv4.conf.default.accept_redirects": "0",
            "net.ipv6.conf.all.disable_ipv6": "0",
            "net.ipv6.conf.all.accept_redirects": "1",
            "net.ipv6.conf.default.accept_redirects": "1",
            "fs.suid_dumpable": "0",
            "kernel.dmesg_restrict": "1",
            "kernel.kptr_restrict": "1",
            "net.ipv4.conf.all.rp_filter": "1",
            "vm.swappiness": "10",
            "vm.overcommit_memory": "0",
        }
        mock_sysctl.side_effect = values.get

        result = sysctl.check()

        self.assertEqual(result.status, "WARN")
        self.assertEqual(result.message, "2 high-signal sysctl issue(s)")
        self.assertIn("net.ipv6.conf.all.accept_redirects = 1  (expected 0) — IPv6 redirect acceptance enabled — routing can be manipulated", result.details)
        self.assertIn("net.ipv6.conf.default.accept_redirects = 1  (expected 0) — IPv6 redirect acceptance enabled on new interfaces", result.details)

    @patch("whatbroke.checks.sysctl._sysctl")
    def test_check_treats_ipv6_redirects_as_not_applicable_when_ipv6_disabled(self, mock_sysctl):
        values = {
            "kernel.randomize_va_space": "2",
            "net.ipv4.tcp_syncookies": "1",
            "net.ipv4.conf.all.accept_redirects": "0",
            "net.ipv4.conf.default.accept_redirects": "0",
            "net.ipv6.conf.all.disable_ipv6": "1",
            "fs.suid_dumpable": "0",
            "kernel.dmesg_restrict": "1",
            "kernel.kptr_restrict": "1",
            "net.ipv4.conf.all.rp_filter": "1",
            "vm.swappiness": "10",
            "vm.overcommit_memory": "0",
        }
        mock_sysctl.side_effect = values.get

        result = sysctl.check()

        self.assertEqual(result.status, "OK")
        self.assertIn("net.ipv6: disabled or not exposed by this kernel", result.details)


if __name__ == "__main__":
    unittest.main()
