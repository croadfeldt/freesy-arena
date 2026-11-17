"""Tests for freezy-net-helper, run against a fake ansible-playbook.

    python3 -m unittest deploy/host/test_freezy_net_helper.py
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "freezy-net-helper")

# Stands in for ansible-playbook: records its arguments, then exits as the test asks.
FAKE_ANSIBLE = """#!/bin/sh
printf '%s\\n' "$@" >> "$FAKE_LOG"
echo "fake playbook output"
if [ -n "$FAKE_NEXT_REQUEST" ] && [ ! -e "$FAKE_LOG.swapped" ]; then
  touch "$FAKE_LOG.swapped"
  cp "$FAKE_NEXT_REQUEST" "$FAKE_SPOOL/request/teams.json"
fi
exit "${FAKE_RC:-0}"
"""


class HelperTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.spool = os.path.join(self.dir.name, "spool")
        os.makedirs(os.path.join(self.spool, "request"))
        os.makedirs(os.path.join(self.spool, "result"))
        self.fake = os.path.join(self.dir.name, "fake-ansible")
        with open(self.fake, "w") as f:
            f.write(FAKE_ANSIBLE)
        os.chmod(self.fake, 0o755)
        self.log = os.path.join(self.dir.name, "calls.log")
        self.env = dict(
            os.environ,
            FREEZY_NET_SPOOL=self.spool,
            FREEZY_NET_ANSIBLE=self.fake,
            FREEZY_NET_PLAYBOOK="/nonexistent/match_network.yaml",
            FAKE_LOG=self.log,
            FAKE_SPOOL=self.spool,
        )

    def tearDown(self):
        self.dir.cleanup()

    def request_path(self):
        return os.path.join(self.spool, "request", "teams.json")

    def write_request(self, request, path=None):
        with open(path or self.request_path(), "w") as f:
            f.write(request if isinstance(request, str) else json.dumps(request))

    def run_helper(self, **env):
        return subprocess.run(
            [sys.executable, HELPER], env=dict(self.env, **env), capture_output=True, text=True, timeout=30,
        )

    def result(self):
        path = os.path.join(self.spool, "result", "status.json")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return f.read().splitlines()

    def test_applies_valid_request(self):
        teams = ["254", "", "1114", "8", "", "10101"]
        self.write_request({"id": "1700000000", "team_numbers": teams})
        completed = self.run_helper()
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual({"id": "1700000000", "state": "ok", "message": ""}, self.result())

        # The playbook runs once, locally, with exactly the six team numbers.
        calls = self.calls()
        self.assertEqual(["-i", "localhost,", "-c", "local", "-e"], calls[:5])
        self.assertEqual({"team_numbers": teams}, json.loads(calls[5]))
        self.assertEqual("/nonexistent/match_network.yaml", calls[6])
        self.assertEqual(7, len(calls))

        # The result is world-readable so the arena's container can read it.
        mode = os.stat(os.path.join(self.spool, "result", "status.json")).st_mode
        self.assertEqual(0o644, stat.S_IMODE(mode))

    def test_reports_playbook_failure(self):
        self.write_request({"id": "a1", "team_numbers": ["254", "", "", "", "", ""]})
        completed = self.run_helper(FAKE_RC="2")
        self.assertEqual(1, completed.returncode)
        result = self.result()
        self.assertEqual("a1", result["id"])
        self.assertEqual("error", result["state"])
        self.assertIn("rc=2", result["message"])
        self.assertIn("fake playbook output", result["message"])

    def test_reports_missing_ansible(self):
        self.write_request({"id": "a2", "team_numbers": [""] * 6})
        self.run_helper(FREEZY_NET_ANSIBLE="/nonexistent/ansible-playbook")
        self.assertEqual("error", self.result()["state"])

    def test_rejects_bad_requests_without_running_anything(self):
        bad_requests = [
            "not json",
            "[]",
            {"id": "x", "team_numbers": ["254"] * 5},
            {"id": "x", "team_numbers": ["254"] * 7},
            {"id": "x", "team_numbers": [254, "", "", "", "", ""]},
            {"id": "x", "team_numbers": ["254; reboot", "", "", "", "", ""]},
            {"id": "x", "team_numbers": ["0", "", "", "", "", ""]},
            {"id": "x", "team_numbers": ["123456", "", "", "", "", ""]},
            {"id": "x", "team_numbers": ["-e@/etc/shadow", "", "", "", "", ""]},
            {"id": "x", "team_numbers": [""] * 6, "extra_vars": {"become": True}},
            {"id": "../../etc", "team_numbers": [""] * 6},
            {"id": "x" * 65, "team_numbers": [""] * 6},
            {"team_numbers": [""] * 6},
            "x" * 5000,
        ]
        for request in bad_requests:
            with self.subTest(request=request):
                self.write_request(request)
                completed = self.run_helper()
                self.assertEqual(1, completed.returncode)
                self.assertEqual([], self.calls())
                result = self.result()
                if result is not None:
                    self.assertEqual("error", result["state"])
                    self.assertIn("rejected", result["message"])

    def test_tells_the_arena_when_a_request_with_a_valid_id_is_rejected(self):
        self.write_request({"id": "b7", "team_numbers": ["abc", "", "", "", "", ""]})
        self.run_helper()
        result = self.result()
        self.assertEqual("b7", result["id"])
        self.assertEqual("error", result["state"])

    def test_does_not_follow_a_symlinked_request(self):
        target = os.path.join(self.dir.name, "elsewhere.json")
        self.write_request({"id": "s1", "team_numbers": [""] * 6}, path=target)
        os.symlink(target, self.request_path())
        completed = self.run_helper()
        self.assertEqual(1, completed.returncode)
        self.assertEqual([], self.calls())
        self.assertIsNone(self.result())

    def test_missing_request_is_an_error_not_a_crash(self):
        completed = self.run_helper()
        self.assertEqual(1, completed.returncode)
        self.assertNotIn("Traceback", completed.stderr)

    def test_picks_up_a_request_that_arrives_during_a_run(self):
        # systemd does not start the service again while it is running, so the helper must notice a
        # newer request itself.
        newer = os.path.join(self.dir.name, "newer.json")
        self.write_request({"id": "second", "team_numbers": ["1114", "", "", "", "", ""]}, path=newer)
        self.write_request({"id": "first", "team_numbers": ["254", "", "", "", "", ""]})
        completed = self.run_helper(FAKE_NEXT_REQUEST=newer)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("second", self.result()["id"])
        applied = [json.loads(arg)["team_numbers"][0] for arg in self.calls() if arg.startswith("{")]
        self.assertEqual(["254", "1114"], applied)


if __name__ == "__main__":
    unittest.main()
