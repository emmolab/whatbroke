import unittest
from unittest.mock import mock_open, patch

from whatbroke.checks import users


class UsersSudoersNoiseTests(unittest.TestCase):
    @patch("glob.glob", return_value=[])
    def test_common_group_nopasswd_defaults_are_suppressed(self, _mock_glob):
        sudoers = "%wheel ALL=(ALL:ALL) NOPASSWD: ALL\n%sudo ALL=(ALL:ALL) NOPASSWD: ALL\n"

        with patch("builtins.open", mock_open(read_data=sudoers)):
            issues = users._check_sudoers()

        self.assertEqual(issues, [])

    @patch("glob.glob", return_value=[])
    def test_direct_user_nopasswd_all_still_flags(self, _mock_glob):
        sudoers = "deploy ALL=(ALL) NOPASSWD: ALL\n"

        with patch("builtins.open", mock_open(read_data=sudoers)):
            issues = users._check_sudoers()

        self.assertEqual(len(issues), 1)
        self.assertIn("deploy ALL=(ALL) NOPASSWD: ALL", issues[0])


if __name__ == "__main__":
    unittest.main()
