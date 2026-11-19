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



class UnitFileTest(unittest.TestCase):
    """Settings in freezy-net.service that chaos testing on the field server showed are needed."""

    def setUp(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "freezy-net.service")
        with open(path) as f:
            self.lines = [line.strip() for line in f]

    def test_start_limit_is_off(self):
        # Ten rejected requests in four seconds hit the default limit (5 starts in 10 s). That failed
        # freezy-net.path too, and a good request sent afterwards was never applied.
        self.assertIn("StartLimitIntervalSec=0", self.lines)

    def test_filter_is_loaded_before_the_helper_runs(self):
        # With the filter table deleted by hand, loading a match brought the team networks up
        # unfiltered.
        pre = [line for line in self.lines if line.startswith("ExecStartPre=")]
        self.assertEqual(len(pre), 1)
        self.assertIn("freezy-field.nft", pre[0])
        self.assertLess(self.lines.index(pre[0]), self.lines.index("ExecStart=/usr/libexec/freezy-net-helper"))

    def test_a_killed_helper_is_started_again(self):
        # Killed mid-run on the field, the helper stayed down: the arena waited two minutes for a
        # verdict and the team networks were left part-changed.
        self.assertIn("Restart=on-failure", self.lines)

    def test_watch_runs_the_helper_when_it_starts(self):
        # A request written while freezy-net.path was stopped was never applied after it started again.
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "freezy-net.path")
        with open(path) as f:
            self.assertIn("Wants=freezy-net.service", [line.strip() for line in f])


class MatchPlaybookTest(unittest.TestCase):
    """The order of work in match_network.yaml. On the field, a run that failed at the Kea step left the
    team gateways on the new teams and DHCP on the old ones."""

    def setUp(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is not installed")
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ansible", "match_network.yaml")
        with open(path) as f:
            self.tasks = yaml.safe_load(f)[0]["tasks"]
        self.outer = next(task for task in self.tasks if "block" in task)
        self.change = next(task for task in self.outer["block"] if "block" in task)

    def test_kea_configuration_is_checked_before_anything_changes(self):
        stage = self.outer["block"][0]
        self.assertIn("-t /tmp/kea-dhcp4.conf", stage["ansible.builtin.template"]["validate"])
        self.assertLess(self.outer["block"].index(stage), self.outer["block"].index(self.change))
        before = self.tasks[:self.tasks.index(self.outer)] + [stage]
        self.assertFalse([t["name"] for t in before if "nmcli connection modify" in str(t) or "systemd" in str(t)])

    def test_staging_file_is_removed_however_the_run_ends(self):
        self.assertIn("freezy_kea_staged.path", str(self.outer["always"]))

    def test_every_change_is_inside_the_block_that_rolls_back(self):
        changing = [task["name"] for task in self.change["block"]]
        self.assertIn("Set or clear each team VLAN's address", changing)
        self.assertIn("Put the checked Kea configuration in place", changing)
        self.assertIn("Load the new configuration into Kea", changing)

    def test_a_vlan_is_activated_when_its_live_address_is_wrong(self):
        # On the field, a run killed between changing the profiles and activating them left five of
        # six gateways on the old teams. The next load saw the profiles already right, activated
        # nothing, and failed because Kea had no address to listen on.
        self.assertIn("Read each team VLAN's live address", [task["name"] for task in self.tasks])
        apply = next(task for task in self.change["block"] if "nmcli connection up" in str(task))
        self.assertIn("freezy_live", str(apply["loop"]))
        self.assertIn("item.1.stdout", apply["when"])

    def test_a_failure_puts_addresses_and_kea_back_and_still_fails(self):
        rescue = [task["name"] for task in self.change["rescue"]]
        self.assertIn("Put each team VLAN's address back", rescue)
        self.assertIn("Put the previous Kea configuration back", rescue)
        self.assertIn("ansible.builtin.fail", self.change["rescue"][-1])

if __name__ == "__main__":
    unittest.main()
