"""Tests for deploy/freezy-update against a fake field server: every command it would run is recorded,
and the arena is a fake that reports a loaded match.

    python3 -m unittest deploy/test_freezy_update.py
"""
import importlib.machinery
import importlib.util
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
loader = importlib.machinery.SourceFileLoader("freezy_update", str(HERE / "freezy-update"))
spec = importlib.util.spec_from_loader("freezy_update", loader)
fu = importlib.util.module_from_spec(spec)
loader.exec_module(fu)

CHECKOUT = Path("/home/ansible/freesy-arena-2026")
ARENA_CHECKOUT = Path("/home/cheesy/freesy-arena-2026")
KEA_SOURCE = "kkkk" * 10
HOST_SETUP = f"ansible-playbook -i localhost, -c local {CHECKOUT}/deploy/host/ansible/host_setup.yaml"


class FakeRunner:
    def __init__(self, is_arena_user=False, changed="", revision="", previous_exists=True, heads=None,
                 kea_built_from=KEA_SOURCE):
        self.is_arena_user = is_arena_user
        self.arena_home = "/home/cheesy"
        self.calls = []
        self.changed, self.revision, self.previous_exists = changed, revision, previous_exists
        self.heads = heads or {}
        self.kea_built_from = kea_built_from

    def run(self, *args, who="me", cwd=None, check=True):
        self.calls.append((who, list(args)))
        out, rc = "", 0
        if args[:1] == ("git",) and "HEAD:deploy/kea" in args:
            out = KEA_SOURCE
        elif args[:1] == ("git",) and "rev-parse" in args:
            sequence = self.heads.setdefault(args[2], ["aaaa" * 10, "bbbb" * 10])
            out = sequence.pop(0) if len(sequence) > 1 else sequence[0]
        elif args[:1] == ("git",) and "diff" in args:
            out = self.changed
        elif args[:3] == ("podman", "image", "exists"):
            rc = 0 if (args[3] != fu.PREVIOUS or self.previous_exists) else 1
        elif args[:3] == ("podman", "image", "inspect") and "freezy.source" in " ".join(args):
            out = self.kea_built_from or ""
            rc = 0 if self.kea_built_from is not None else 125
        elif args[:3] == ("podman", "image", "inspect"):
            out = self.revision
        elif args[:1] == ("ansible-playbook",):
            out = "localhost : ok=21 changed=3 unreachable=0 failed=0"
        elif args[:1] == ("cmp",):
            rc = 0
        return subprocess.CompletedProcess(args, rc, out, "")

    def commands(self, who=None):
        return [" ".join(args) for w, args in self.calls if who is None or w == who]


class FakeArena:
    def __init__(self, state=fu.PRE_MATCH, match_id=12, answers=(True,)):
        self.state, self.match_id = state, match_id
        self.answer_sequence = list(answers)
        self.loaded = []

    def status(self):
        return {"match_id": self.match_id, "name": "Qualification 12", "state": self.state}

    def answers(self):
        return self.answer_sequence.pop(0) if len(self.answer_sequence) > 1 else self.answer_sequence[0]

    def load(self, match_id):
        self.loaded.append(match_id)


def updater(runner, arena, arena_checkout=ARENA_CHECKOUT):
    return fu.Updater(CHECKOUT, arena_checkout, {}, runner, arena, wait=lambda seconds: None)


@mock.patch.object(fu, "say", lambda message: None)
class UpdateTest(unittest.TestCase):
    def test_refuses_during_a_match_and_changes_nothing(self):
        runner, arena = FakeRunner(), FakeArena(state=fu.PRE_MATCH + 4)
        with self.assertRaisesRegex(fu.Stop, "A match is running"):
            updater(runner, arena).update("quay.io/x/freezy-arena:latest", False, False)
        self.assertEqual([], runner.calls)

    def test_force_restarts_during_a_match(self):
        runner, arena = FakeRunner(), FakeArena(state=fu.PRE_MATCH + 4)
        updater(runner, arena).update("quay.io/x/freezy-arena:latest", False, True)
        self.assertIn("systemctl --user restart freezy-arena.service", runner.commands("arena"))

    def test_pulls_the_image_keeps_the_old_one_and_loads_the_match_again(self):
        runner, arena = FakeRunner(), FakeArena()
        updater(runner, arena).update("quay.io/x/freezy-arena:latest", False, False)
        arena_commands = runner.commands("arena")
        keep = arena_commands.index(f"podman tag {fu.IMAGE} {fu.PREVIOUS}")
        pull = arena_commands.index("podman pull -q quay.io/x/freezy-arena:latest")
        restart = arena_commands.index("systemctl --user restart freezy-arena.service")
        self.assertLess(keep, pull)
        self.assertLess(pull, restart)
        self.assertEqual([12], arena.loaded)
        self.assertFalse([c for c in runner.commands("root") if c.startswith("podman build")])

    def test_builds_when_no_image_source_is_set(self):
        runner, arena = FakeRunner(), FakeArena()
        updater(runner, arena).update("", False, False)
        self.assertIn(f"podman build -q -t {fu.IMAGE} {ARENA_CHECKOUT}", runner.commands("arena"))
        self.assertFalse([c for c in runner.commands() if c.startswith("podman pull")])

    def test_the_test_match_is_not_loaded_again(self):
        runner, arena = FakeRunner(), FakeArena(match_id=0)
        updater(runner, arena).update("", False, False)
        self.assertEqual([], arena.loaded)

    def test_host_changes_run_host_setup_before_the_arena_restarts(self):
        runner, arena = FakeRunner(changed="deploy/host/freezy-firewalld-zones"), FakeArena()
        updater(runner, arena).update("", False, False)
        self.assertIn(HOST_SETUP, runner.commands("root"))
        everything = runner.commands()
        self.assertLess(everything.index(HOST_SETUP), everything.index("systemctl --user restart freezy-arena.service"))
        self.assertFalse([c for c in runner.commands("root") if c.startswith("podman build")])

    def test_host_setup_runs_even_when_the_checkout_was_pulled_by_hand(self):
        # The first run on the field server: the checkout had to be pulled to get this script, so the
        # script's own pull changed nothing, and the host files of that pull were never applied.
        runner = FakeRunner(heads={str(CHECKOUT): ["bbbb" * 10]})
        updater(runner, FakeArena()).update("", False, False)
        self.assertIn(HOST_SETUP, runner.commands("root"))

    def test_kea_is_rebuilt_and_restarted_when_not_built_from_this_checkout(self):
        for built_from in (None, "old" * 10):
            runner = FakeRunner(kea_built_from=built_from)
            updater(runner, FakeArena()).update("", False, False)
            root = runner.commands("root")
            self.assertIn(f"podman build -q --label freezy.source={KEA_SOURCE} -t {fu.KEA_IMAGE} "
                          f"{CHECKOUT}/deploy/kea", root)
            self.assertIn("systemctl restart freezy-kea.service", root)

    def test_kea_built_from_this_checkout_is_left_running(self):
        runner = FakeRunner()
        updater(runner, FakeArena()).update("", False, False)
        self.assertFalse([c for c in runner.commands("root") if "kea" in c and ("build" in c or "restart" in c)])

    def test_interface_playbooks_are_left_to_a_person(self):
        runner, arena = FakeRunner(changed="deploy/host/ansible/host_network.yaml"), FakeArena()
        updater(runner, arena).update("", False, False)
        self.assertFalse([c for c in runner.commands() if "host_network.yaml" in c and "ansible-playbook" in c])

    def test_as_the_arena_account_host_changes_stop_before_the_arena_is_touched(self):
        runner = FakeRunner(is_arena_user=True, changed="deploy/host/ansible/host_setup.yaml")
        with self.assertRaisesRegex(fu.Stop, "Those need root"):
            updater(runner, FakeArena(), arena_checkout=CHECKOUT).update("", False, False)
        self.assertFalse([c for c in runner.commands() if "podman" in c or "systemctl" in c])

    def test_as_the_arena_account_its_checkout_is_pulled_once(self):
        runner = FakeRunner(is_arena_user=True)
        updater(runner, FakeArena(), arena_checkout=CHECKOUT).update("", False, False)
        self.assertEqual(1, len([c for c in runner.commands() if " pull " in c and c.startswith("git")]))

    def test_an_arena_that_does_not_come_up_goes_back_to_the_previous_image(self):
        runner = FakeRunner()
        arena = FakeArena(answers=[False] * fu.START_TIMEOUT_SEC + [True])
        with self.assertRaisesRegex(fu.Stop, "Rolled back"):
            updater(runner, arena).update("quay.io/x/freezy-arena:latest", False, False)
        arena_commands = runner.commands("arena")
        self.assertEqual(f"podman tag {fu.PREVIOUS} {fu.IMAGE}",
                         [c for c in arena_commands if c.startswith("podman tag")][-1])
        self.assertEqual(2, arena_commands.count("systemctl --user restart freezy-arena.service"))
        self.assertEqual([12], arena.loaded)

    def test_says_so_when_the_pulled_image_is_older_than_the_checkout(self):
        said = []
        runner, arena = FakeRunner(revision="cccc" * 10), FakeArena()
        with mock.patch.object(fu, "say", said.append):
            updater(runner, arena).update("quay.io/x/freezy-arena:latest", False, False)
        self.assertTrue([m for m in said if m.startswith("Note: the image is from cccccccccccc")])

    def test_rollback_restores_the_previous_image_and_the_match(self):
        runner, arena = FakeRunner(), FakeArena()
        updater(runner, arena).rollback(False)
        self.assertIn(f"podman tag {fu.PREVIOUS} {fu.IMAGE}", runner.commands("arena"))
        self.assertEqual([12], arena.loaded)
        self.assertFalse([c for c in runner.commands() if c.startswith("git")])

    def test_rollback_without_a_previous_image_changes_nothing(self):
        runner = FakeRunner(previous_exists=False)
        with self.assertRaisesRegex(fu.Stop, "no previous image"):
            updater(runner, FakeArena()).rollback(False)
        self.assertFalse([c for c in runner.commands() if "tag" in c or "systemctl" in c])


class WorkflowTest(unittest.TestCase):
    def test_images_are_pushed_only_on_a_merge(self):
        text = (HERE.parent / ".github/workflows/images.yml").read_text()
        self.assertIn("github.event_name == 'push'", text)
        self.assertIn("branches: [ Freezy-Arena-2026 ]", text)
        self.assertIn("if: env.PUSH == 'true'", text)


if __name__ == "__main__":
    unittest.main()
