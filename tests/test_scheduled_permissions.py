import io
import unittest
from unittest.mock import patch

from whatbroke.checks import scheduled


class ScheduledPermissionTests(unittest.TestCase):
    @patch("whatbroke.checks.scheduled.os.geteuid", return_value=1000)
    @patch("whatbroke.checks.scheduled.pwd.getpwuid")
    def test_crontab_list_command_uses_plain_list_for_current_user(self, mock_getpwuid, *_mocks):
        mock_getpwuid.return_value.pw_name = "alice"

        self.assertEqual(scheduled._crontab_list_command("alice"), ["crontab", "-l"])
        self.assertIsNone(scheduled._crontab_list_command("bob"))

    @patch("whatbroke.checks.scheduled.os.geteuid", return_value=1000)
    @patch("whatbroke.checks.scheduled.pwd.getpwuid")
    @patch("whatbroke.checks.scheduled._run")
    def test_check_crontabs_skips_uninspectable_other_users_when_unprivileged(self, mock_run, mock_getpwuid, *_mocks):
        mock_getpwuid.return_value.pw_name = "openclaw"

        def fake_run(cmd, timeout=5):
            if cmd == ["crontab", "-l"]:
                return type("Proc", (), {"returncode": 1, "stdout": "", "stderr": "no crontab for openclaw\n"})()
            raise AssertionError(f"unexpected command: {cmd}")

        passwd_data = "openclaw:x:1000:1000::/home/openclaw:/bin/bash\nalice:x:1001:1001::/home/alice:/bin/bash\n"
        mock_run.side_effect = fake_run

        with patch("builtins.open", return_value=io.StringIO(passwd_data)):
            issues = scheduled._check_crontabs()

        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
