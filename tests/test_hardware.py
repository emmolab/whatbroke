import unittest
from unittest.mock import patch

from whatbroke.checks import hardware


class HardwareMemoryPressureTests(unittest.TestCase):
    @patch("whatbroke.checks.hardware._get_uptime", return_value=("2d 3h 4m", 2.1))
    @patch("whatbroke.checks.hardware._get_temperatures", return_value=[])
    @patch("whatbroke.checks.hardware._top_processes", return_value=["123 root 55.0 memhog"])
    @patch(
        "whatbroke.checks.hardware._read_pressure",
        return_value={"some": {"avg10": 6.2}, "full": {"avg10": 1.3}},
    )
    @patch("whatbroke.checks.hardware._get_swap_usage", return_value=(25.0, "1.0 GB", "4.0 GB"))
    @patch(
        "whatbroke.checks.hardware._read_meminfo",
        return_value={"MemTotal": 1024 * 1024, "MemAvailable": 150 * 1024, "SwapTotal": 0, "SwapFree": 0},
    )
    @patch("whatbroke.checks.hardware.os.getloadavg", return_value=(0.5, 0.4, 0.3))
    @patch("whatbroke.checks.hardware.os.cpu_count", return_value=4)
    def test_memory_pressure_escalates_to_broke(self, *_mocks):
        result = hardware.check()

        self.assertEqual(result.status, "BROKE")
        self.assertIn("MemPressure", result.message)
        self.assertTrue(any("tasks are stalling in reclaim" in line for line in result.details))
        self.assertTrue(any("Top memory consumers:" in line for line in result.details))

    @patch("whatbroke.checks.hardware._get_uptime", return_value=("2d 3h 4m", 2.1))
    @patch("whatbroke.checks.hardware._get_temperatures", return_value=[])
    @patch("whatbroke.checks.hardware._top_processes", return_value=[])
    @patch(
        "whatbroke.checks.hardware._read_pressure",
        return_value={"some": {"avg10": 0.4}, "full": {"avg10": 0.0}},
    )
    @patch("whatbroke.checks.hardware._get_swap_usage", return_value=(0.0, "0 kB", "0 kB"))
    @patch(
        "whatbroke.checks.hardware._read_meminfo",
        return_value={"MemTotal": 1024 * 1024, "MemAvailable": 700 * 1024, "SwapTotal": 0, "SwapFree": 0},
    )
    @patch("whatbroke.checks.hardware.os.getloadavg", return_value=(0.5, 0.4, 0.3))
    @patch("whatbroke.checks.hardware.os.cpu_count", return_value=4)
    def test_low_background_pressure_stays_ok(self, *_mocks):
        result = hardware.check()

        self.assertEqual(result.status, "OK")
        self.assertTrue(any("Memory pressure context" in line for line in result.details))
        self.assertNotIn("MemPressure", result.message)


if __name__ == "__main__":
    unittest.main()
