import unittest

from whatbroke.checks import services


class ServicesZombieTests(unittest.TestCase):
    def test_parse_ps_zombies_extracts_richer_fields(self):
        sample = """\
  PID  PPID STAT ELAPSED COMMAND
    1     0 Ss   999999 systemd
  200    10 Z    30     worker
  201    10 Zs   900    gunicorn
"""

        zombies = services._parse_ps_zombies(sample)

        self.assertEqual(
            zombies,
            [
                {"pid": 200, "ppid": 10, "stat": "Z", "etimes": 30, "comm": "worker"},
                {"pid": 201, "ppid": 10, "stat": "Zs", "etimes": 900, "comm": "gunicorn"},
            ],
        )

    def test_summarize_zombies_separates_transient_from_stale(self):
        zombies = [
            {"pid": 200, "ppid": 10, "stat": "Z", "etimes": 30, "comm": "worker"},
            {"pid": 201, "ppid": 10, "stat": "Zs", "etimes": 900, "comm": "gunicorn"},
            {"pid": 202, "ppid": 11, "stat": "Z", "etimes": 1200, "comm": "gunicorn"},
        ]

        summary = services._summarize_zombies(zombies)

        self.assertEqual(len(summary["transient"]), 1)
        self.assertEqual(len(summary["stale"]), 2)
        self.assertEqual(summary["parent_counts"][10], 1)
        self.assertEqual(summary["commands"]["gunicorn"], 2)
        self.assertEqual(summary["oldest"][0]["pid"], 202)


if __name__ == "__main__":
    unittest.main()
