import socket
import unittest
from unittest.mock import patch

from whatbroke.checks import networking


class NetworkingCheckTests(unittest.TestCase):
    @patch("whatbroke.checks.networking.socket.getaddrinfo")
    def test_dns_resolution_accepts_ipv6_results(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 0, 0, 0)),
        ]

        results = networking._test_dns_resolution()

        self.assertEqual(results[0], ("example.com", "2606:2800:220:1:248:1893:25c8:1946", None))

    @patch("whatbroke.checks.networking._check_nic_errors", return_value=[])
    @patch("whatbroke.checks.networking._check_ntp_sync", return_value=(True, "NTP service: systemd-timesyncd"))
    @patch("whatbroke.checks.networking._test_outbound_https", return_value=[("https://example.com/", True, "HTTP 200"), ("https://github.com/", True, "HTTP 200")])
    @patch("whatbroke.checks.networking._test_dns_resolution", return_value=[("example.com", "93.184.216.34", None), ("github.com", "140.82.121.4", None), ("cloudflare.com", "104.16.132.229", None)])
    @patch("whatbroke.checks.networking._check_resolver_config", return_value=(["1.1.1.1"], []))
    @patch("whatbroke.checks.networking._check_gateway_reachability", return_value=(True, "192.0.2.1"))
    @patch("whatbroke.checks.networking._check_default_route", return_value=(True, "default via 192.0.2.1 dev eth0", "192.0.2.1", "eth0"))
    def test_check_reports_ok_for_healthy_network(self, *_mocks):
        result = networking.check()

        self.assertEqual(result.status, "OK")
        self.assertEqual(result.message, "All networking checks passed")
        self.assertIn("Gateway reachability: OK (192.0.2.1 via eth0)", result.details)
        self.assertIn("Outbound HTTPS: OK", result.details)

    @patch("whatbroke.checks.networking._check_nic_errors", return_value=[])
    @patch("whatbroke.checks.networking._check_ntp_sync", return_value=(True, "NTP service: systemd-timesyncd"))
    @patch("whatbroke.checks.networking._test_outbound_https", return_value=[("https://example.com/", True, "HTTP 200"), ("https://github.com/", True, "HTTP 200")])
    @patch("whatbroke.checks.networking._test_dns_resolution", return_value=[("example.com", "93.184.216.34", None), ("github.com", "140.82.121.4", None), ("cloudflare.com", "104.16.132.229", None)])
    @patch("whatbroke.checks.networking._check_resolver_config", return_value=(["1.1.1.1"], []))
    @patch("whatbroke.checks.networking._check_gateway_reachability", return_value=(False, "Destination Host Unreachable"))
    @patch("whatbroke.checks.networking._check_default_route", return_value=(True, "default via 192.0.2.1 dev eth0", "192.0.2.1", "eth0"))
    def test_check_does_not_alert_on_gateway_ping_failure_when_broader_connectivity_is_healthy(self, *_mocks):
        result = networking.check()

        self.assertEqual(result.status, "OK")
        self.assertEqual(result.message, "All networking checks passed")
        self.assertIn("Gateway reachability: inconclusive", " ".join(result.details))
        self.assertIsNone(result.remediation)

    @patch("whatbroke.checks.networking._check_nic_errors", return_value=[])
    @patch("whatbroke.checks.networking._check_ntp_sync", return_value=(True, "NTP service: systemd-timesyncd"))
    @patch("whatbroke.checks.networking._test_outbound_https", return_value=[("https://example.com/", False, "timed out"), ("https://github.com/", True, "HTTP 200")])
    @patch("whatbroke.checks.networking._test_dns_resolution", return_value=[("example.com", "93.184.216.34", None), ("github.com", "140.82.121.4", None), ("cloudflare.com", "104.16.132.229", None)])
    @patch("whatbroke.checks.networking._check_resolver_config", return_value=(["1.1.1.1"], []))
    @patch("whatbroke.checks.networking._check_gateway_reachability", return_value=(False, "Destination Host Unreachable"))
    @patch("whatbroke.checks.networking._check_default_route", return_value=(True, "default via 192.0.2.1 dev eth0", "192.0.2.1", "eth0"))
    def test_check_keeps_gateway_warning_when_other_connectivity_signals_are_failing(self, *_mocks):
        result = networking.check()

        self.assertEqual(result.status, "WARN")
        self.assertIn("gateway unreachable", result.message)
        self.assertEqual(result.remediation, "Check outbound 443/TLS reachability, proxy policy, and CA trust")

    @patch("whatbroke.checks.networking._check_nic_errors", return_value=[])
    @patch("whatbroke.checks.networking._check_ntp_sync", return_value=(True, "NTP service: systemd-timesyncd"))
    @patch("whatbroke.checks.networking._test_outbound_https", return_value=[("https://example.com/", False, "timed out"), ("https://github.com/", False, "timed out")])
    @patch("whatbroke.checks.networking._test_dns_resolution", return_value=[("example.com", "93.184.216.34", None), ("github.com", "140.82.121.4", None), ("cloudflare.com", "104.16.132.229", None)])
    @patch("whatbroke.checks.networking._check_resolver_config", return_value=(["1.1.1.1"], []))
    @patch("whatbroke.checks.networking._check_gateway_reachability", return_value=(True, "192.0.2.1"))
    @patch("whatbroke.checks.networking._check_default_route", return_value=(True, "default via 192.0.2.1 dev eth0", "192.0.2.1", "eth0"))
    def test_check_marks_total_https_failure_as_broke(self, *_mocks):
        result = networking.check()

        self.assertEqual(result.status, "BROKE")
        self.assertIn("2/2 HTTPS probes failed", result.message)
        self.assertEqual(result.remediation, "Check outbound 443/TLS reachability, proxy policy, and CA trust")

    @patch("whatbroke.checks.networking._check_nic_errors", return_value=[])
    @patch("whatbroke.checks.networking._check_ntp_sync", return_value=(True, "NTP service: systemd-timesyncd"))
    @patch("whatbroke.checks.networking._test_outbound_https", return_value=[("https://example.com/", True, "HTTP 200"), ("https://github.com/", True, "HTTP 200")])
    @patch("whatbroke.checks.networking._test_dns_resolution", return_value=[("example.com", None, "temporary failure in name resolution"), ("github.com", None, "temporary failure in name resolution"), ("cloudflare.com", "104.16.132.229", None)])
    @patch("whatbroke.checks.networking._check_resolver_config", return_value=([], ["no nameserver entries configured"]))
    @patch("whatbroke.checks.networking._check_gateway_reachability", return_value=(True, "192.0.2.1"))
    @patch("whatbroke.checks.networking._check_default_route", return_value=(True, "default via 192.0.2.1 dev eth0", "192.0.2.1", "eth0"))
    def test_check_escalates_broken_resolver_and_dns_failures(self, *_mocks):
        result = networking.check()

        self.assertEqual(result.status, "CRIT")
        self.assertIn("resolver config broken", result.message)
        self.assertIn("2 DNS failures", result.message)
        self.assertEqual(result.remediation, "Check /etc/resolv.conf and your resolver service")

    @patch("whatbroke.checks.networking._check_nic_errors", return_value=[])
    @patch("whatbroke.checks.networking._check_ntp_sync", return_value=(False, "NTP service: systemd-timesyncd"))
    @patch("whatbroke.checks.networking._test_outbound_https", return_value=[("https://example.com/", True, "HTTP 200"), ("https://github.com/", True, "HTTP 200")])
    @patch("whatbroke.checks.networking._test_dns_resolution", return_value=[("example.com", "93.184.216.34", None), ("github.com", "140.82.121.4", None), ("cloudflare.com", "104.16.132.229", None)])
    @patch("whatbroke.checks.networking._check_resolver_config", return_value=([], []))
    @patch("whatbroke.checks.networking._check_gateway_reachability", return_value=(True, "192.0.2.1"))
    @patch("whatbroke.checks.networking._check_default_route", return_value=(True, "default via 192.0.2.1 dev eth0", "192.0.2.1", "eth0"))
    def test_check_summarises_unsynchronised_ntp(self, *_mocks):
        result = networking.check()

        self.assertEqual(result.status, "WARN")
        self.assertIn("NTP unsynchronised", result.message)
        self.assertEqual(result.remediation, "Enable NTP: timedatectl set-ntp true")

    @patch("whatbroke.checks.networking._check_nic_errors", return_value=["eth0: 42 RX errors", "eth1: 200 RX drops"])
    @patch("whatbroke.checks.networking._check_ntp_sync", return_value=(True, "NTP service: systemd-timesyncd"))
    @patch("whatbroke.checks.networking._test_outbound_https", return_value=[("https://example.com/", True, "HTTP 200"), ("https://github.com/", True, "HTTP 200")])
    @patch("whatbroke.checks.networking._test_dns_resolution", return_value=[("example.com", "93.184.216.34", None), ("github.com", "140.82.121.4", None), ("cloudflare.com", "104.16.132.229", None)])
    @patch("whatbroke.checks.networking._check_resolver_config", return_value=([], []))
    @patch("whatbroke.checks.networking._check_gateway_reachability", return_value=(True, "192.0.2.1"))
    @patch("whatbroke.checks.networking._check_default_route", return_value=(True, "default via 192.0.2.1 dev eth0", "192.0.2.1", "eth0"))
    def test_check_summarises_nic_issues(self, *_mocks):
        result = networking.check()

        self.assertEqual(result.status, "WARN")
        self.assertIn("2 NIC error(s)", result.message)
        self.assertEqual(result.remediation, "Check NIC hardware and driver: ethtool <iface>")


if __name__ == "__main__":
    unittest.main()
