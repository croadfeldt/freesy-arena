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


def commit(n):
    """A 40-character commit id for version n."""
    return f"{n:x}" * 40 if n < 16 else f"{n:040x}"


class FakeRunner:
    """Records every command, and keeps a small fake podman image store for the arena's account."""

    def __init__(self, is_arena_user=False, changed="", revision="", previous_exists=True, heads=None,
                 kea_built_from=KEA_SOURCE, versions=None):
        self.is_arena_user = is_arena_user
        self.arena_home = "/home/cheesy"
        self.calls = []
        self.changed, self.revision = changed, revision
        self.heads = heads or {}
        self.kea_built_from = kea_built_from
        self.clock = 1000
        self.images = {}  # image id -> {"created": int, "revision": str}
        self.tags = {}    # image name -> image id
        # Kept versions from earlier updates: n -> created; the newest is running and the next one previous.
        for n in sorted(versions or {}):
            self.add_image(f"{fu.REPOSITORY}:{commit(n)[:12]}", commit(n), created=n)
        if versions:
            newest = sorted(versions, reverse=True)
            self.tags[fu.IMAGE] = self.tags[f"{fu.REPOSITORY}:{commit(newest[0])[:12]}"]
            if previous_exists and len(newest) > 1:
                self.tags[fu.PREVIOUS] = self.tags[f"{fu.REPOSITORY}:{commit(newest[1])[:12]}"]
        else:
            self.add_image(fu.IMAGE, "", created=1)
            if previous_exists:
                self.add_image(fu.PREVIOUS, "", created=0)

    def add_image(self, name, revision, created=None):
        image = f"id{len(self.images):04d}"
        if created is None:
            self.clock += 1
            created = self.clock
        self.images[image] = {"created": created, "revision": revision}
        self.tags[name] = image
        return image

    def resolve(self, reference):
        if reference in self.images:
            return reference
        return self.tags.get(reference)

    def podman(self, args):
        if args[:2] == ["image", "exists"]:
            return "", 0 if self.resolve(args[2]) else 1
        if args[:2] == ["image", "inspect"]:
            fmt, reference = args[3], args[4]
            if "freezy.source" in fmt:
                return (self.kea_built_from or ""), 0 if self.kea_built_from is not None else 125
            image = self.resolve(reference)
            if not image:
                return "", 125
            if fmt == "{{.Id}}":
                return image, 0
            if fmt == "{{.Id}} {{.Created.Unix}}":
                return f"{image} {self.images[image]['created']}", 0
            return self.images[image]["revision"], 0
        if args[0] == "tag":
            self.tags[args[2]] = self.resolve(args[1])
            return "", 0
        if args[0] == "build":
            if fu.KEA_IMAGE in args:
                return "", 0
            label = args[args.index("--label") + 1]
            self.add_image(fu.IMAGE, label.split("=", 1)[1])
            return "", 0
        if args[0] == "pull":
            self.add_image(args[-1], self.revision)
            return "", 0
        if args[0] == "images":
            prefix = args[-1] + ":"
            return "\n".join(name[len(prefix):] for name in self.tags if name.startswith(prefix)), 0
        if args[0] == "rmi":
            image = self.tags.pop(args[1])
            if image not in self.tags.values():
                del self.images[image]
            return "", 0
        raise AssertionError(f"unexpected podman call {args}")

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
        elif args[:1] == ("git",) and "log" in args:
            out = "Subject of " + args[-1][:7]
        elif args[:1] == ("podman",):
            out, rc = self.podman(list(args[1:]))
        elif args[:1] == ("ansible-playbook",):
            out = "localhost : ok=21 changed=3 unreachable=0 failed=0"
        if check and rc != 0:
            raise fu.Stop(f"{args} failed")
        return subprocess.CompletedProcess(args, rc, out, "")

    def commands(self, who=None):
        return [" ".join(args) for w, args in self.calls if who is None or w == who]

    def kept(self):
        prefix = fu.REPOSITORY + ":"
        return sorted(name[len(prefix):] for name in self.tags
                      if name.startswith(prefix) and len(name) - len(prefix) == 12)


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
        self.assertIn(f"podman build -q --label {fu.REVISION_LABEL}={'bbbb' * 10} -t {fu.IMAGE} {ARENA_CHECKOUT}",
                      runner.commands("arena"))
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
        running, previous = runner.tags[fu.IMAGE], runner.tags[fu.PREVIOUS]
        updater(runner, arena).rollback(False)
        self.assertEqual(previous, runner.tags[fu.IMAGE])
        self.assertEqual([12], arena.loaded)
        self.assertFalse([c for c in runner.commands() if c.startswith("git")])
        # The image it left becomes the previous one, so a second rollback undoes the first.
        self.assertEqual(running, runner.tags[fu.PREVIOUS])
        updater(runner, FakeArena()).rollback(False)
        self.assertEqual(running, runner.tags[fu.IMAGE])

    def test_rollback_without_a_previous_image_changes_nothing(self):
        runner = FakeRunner(previous_exists=False)
        with self.assertRaisesRegex(fu.Stop, "no previous image"):
            updater(runner, FakeArena()).rollback(False)
        self.assertFalse([c for c in runner.commands() if "tag" in c or "systemctl" in c])


@mock.patch.object(fu, "say", lambda message: None)
class VersionsTest(unittest.TestCase):
    def test_every_update_tags_the_image_with_its_commit(self):
        runner = FakeRunner()
        updater(runner, FakeArena()).update("", False, False)
        self.assertEqual(runner.tags[fu.IMAGE], runner.tags[f"{fu.REPOSITORY}:{'bbbb' * 3}"])

    def test_a_pulled_image_is_tagged_with_the_commit_it_was_built_from(self):
        runner = FakeRunner(revision="cccc" * 10)
        updater(runner, FakeArena()).update("quay.io/x/freezy-arena:latest", False, False)
        self.assertEqual(runner.tags[fu.IMAGE], runner.tags[f"{fu.REPOSITORY}:{'cccc' * 3}"])

    def test_the_newest_five_are_kept_and_older_ones_deleted(self):
        runner = FakeRunner(versions={n: n for n in range(1, 7)})
        updater(runner, FakeArena()).update("", False, False)
        self.assertEqual(sorted([commit(n)[:12] for n in (3, 4, 5, 6)] + ["bbbb" * 3]), runner.kept())
        self.assertEqual(5, len(runner.kept()))

    def test_the_running_and_previous_images_are_never_deleted(self):
        # After a rollback to the oldest version, it is running and must survive the next clean-up.
        runner = FakeRunner(versions={n: n for n in range(1, 7)})
        updater(runner, FakeArena()).rollback(False, commit(1)[:7])
        updater(runner, FakeArena()).update("", False, False)
        self.assertIn(commit(1)[:12], runner.kept())
        self.assertEqual(runner.tags[fu.PREVIOUS], runner.tags[f"{fu.REPOSITORY}:{commit(1)[:12]}"])

    def test_rollback_to_a_kept_version_by_its_commit(self):
        runner, arena = FakeRunner(versions={n: n for n in range(1, 4)}), FakeArena()
        running = runner.tags[fu.IMAGE]
        updater(runner, arena).rollback(False, commit(1)[:7])
        self.assertEqual(runner.tags[f"{fu.REPOSITORY}:{commit(1)[:12]}"], runner.tags[fu.IMAGE])
        self.assertEqual(running, runner.tags[fu.PREVIOUS])
        self.assertEqual([12], arena.loaded)

    def test_rollback_to_an_unknown_or_running_version_changes_nothing(self):
        runner = FakeRunner(versions={n: n for n in range(1, 4)})
        with self.assertRaisesRegex(fu.Stop, "No single kept version"):
            updater(runner, FakeArena()).rollback(False, "deadbeef")
        with self.assertRaisesRegex(fu.Stop, "already running"):
            updater(runner, FakeArena()).rollback(False, commit(3)[:12])
        self.assertFalse([c for c in runner.commands() if c.startswith("podman tag") or "systemctl" in c])

    def test_list_marks_the_running_and_previous_versions(self):
        said = []
        runner = FakeRunner(versions={n: n for n in range(1, 4)})
        with mock.patch.object(fu, "say", said.append):
            updater(runner, FakeArena()).list_versions()
        self.assertEqual([commit(n)[:12] for n in (3, 2, 1)], [line.split()[0] for line in said])
        self.assertIn("running", said[0])
        self.assertIn("previous", said[1])
        self.assertIn("Subject of", said[2])
        self.assertFalse([c for c in runner.commands() if c.startswith("podman tag") or "systemctl" in c])


class WorkflowTest(unittest.TestCase):
    def test_images_are_pushed_only_on_a_merge(self):
        text = (HERE.parent / ".github/workflows/images.yml").read_text()
        self.assertIn("github.event_name == 'push'", text)
        self.assertIn("branches: [ Freezy-Arena-2026 ]", text)
        self.assertIn("if: env.PUSH == 'true'", text)


if __name__ == "__main__":
    unittest.main()
