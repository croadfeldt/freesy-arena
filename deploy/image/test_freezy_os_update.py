"""The image's update command holds during a match, and the boot check fails on the right things.

Run: python3 -m unittest deploy/image/test_freezy_os_update.py
"""
import importlib.machinery
import importlib.util
import os
import stat
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = os.path.join(HERE, "files", "usr", "lib", "greenboot", "check", "required.d", "50-freezy.sh")


def load():
    loader = importlib.machinery.SourceFileLoader("freezy_os_update", os.path.join(HERE, "freezy-os-update"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("freezy_os_update", loader))
    loader.exec_module(module)
    module.say = lambda message: None
    return module


update = load()


class FakeArena:
    def __init__(self, state=0, answers=True):
        self.state, self.is_up = state, answers

    def status(self):
        if not self.is_up:
            raise OSError("connection refused")
        return {"match_id": 7, "name": "Qualification 7", "state": self.state}


class HoldTest(unittest.TestCase):
    def run_it(self, argv, arena):
        ran = []
        code = update.main(argv, arena=arena, run=lambda command: ran.append(command) or 0)
        return code, ran

    def test_an_update_between_matches_is_staged_and_nothing_restarts(self):
        self.assertEqual(self.run_it([], FakeArena()), (0, [["bootc", "upgrade"]]))

    def test_nothing_is_staged_during_a_match(self):
        for state in (1, 3, 6):
            with self.subTest(state=state):
                self.assertEqual(self.run_it([], FakeArena(state)), (1, []))
                self.assertEqual(self.run_it(["--image", "quay.io/x/y:1", "--apply"], FakeArena(state)), (1, []))
                self.assertEqual(self.run_it(["--rollback"], FakeArena(state)), (1, []))

    def test_force_goes_ahead_during_a_match(self):
        self.assertEqual(self.run_it(["--force"], FakeArena(3)), (0, [["bootc", "upgrade"]]))

    def test_an_arena_that_is_down_holds_nothing(self):
        # A broken arena may be the reason for the update or the rollback.
        self.assertEqual(self.run_it(["--rollback"], FakeArena(answers=False)), (0, [["bootc", "rollback"]]))

    def test_check_only_answers(self):
        self.assertEqual(self.run_it(["--check"], FakeArena()), (0, []))
        self.assertEqual(self.run_it(["--check"], FakeArena(3)), (1, []))

    def test_apply_restarts_after_the_change_and_only_if_it_worked(self):
        self.assertEqual(self.run_it(["--image", "quay.io/x/y:1", "--apply"], FakeArena()),
                         (0, [["bootc", "switch", "quay.io/x/y:1"], ["systemctl", "reboot"]]))
        ran = []
        code = update.main(["--apply"], arena=FakeArena(), run=lambda command: ran.append(command) or 1)
        self.assertEqual((code, ran), (1, [["bootc", "upgrade"]]))

    def test_an_image_carried_in_on_a_disk(self):
        self.assertEqual(self.run_it(["--image", "/run/media/usb/image", "--transport", "oci"], FakeArena()),
                         (0, [["bootc", "switch", "--transport", "oci", "/run/media/usb/image"]]))

    def test_it_asks_the_arena_the_way_freezy_update_does(self):
        # The match play client lives in deploy/freezy-update; install.sh puts that file where this
        # command loads it from.
        self.assertEqual(update.ARENA_TOOLS, "/usr/libexec/freezy-update")
        with open(os.path.join(HERE, "install.sh")) as handle:
            self.assertIn('"$src/deploy/freezy-update" /usr/libexec/freezy-update', handle.read())
        update.ARENA_TOOLS = os.path.join(HERE, "..", "freezy-update")
        self.addCleanup(setattr, update, "ARENA_TOOLS", "/usr/libexec/freezy-update")
        self.assertTrue(callable(update.arena_client().status))
        self.assertEqual(update.PRE_MATCH, 0)


class BootCheckTest(unittest.TestCase):
    """Runs the real check against stand-ins for systemctl, nft and curl."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = os.path.join(self.tmp.name, "bin")
        os.makedirs(self.bin)
        self.state = os.path.join(self.tmp.name, "state")
        os.makedirs(self.state)
        # systemctl is-active [--quiet] UNIT: the unit's state is in state/UNIT, "active" when absent.
        self.stub("systemctl", 'for unit; do :; done; s=$(cat "$STATE/$unit" 2>/dev/null || echo active); '
                               '[ "$2" = --quiet ] || echo "$s"; [ "$s" = active ]')
        self.stub("nft", '[ ! -e "$STATE/no-filter" ]')
        # The arena answers from the second time it is asked: it is still starting at the first.
        self.stub("curl", '[ ! -e "$STATE/no-arena" ] || exit 7; n=$(( $(cat "$STATE/asked" 2>/dev/null || echo 0) + 1 )); '
                          'echo $n > "$STATE/asked"; [ $n -ge 2 ]')
        self.stub("sleep", "exit 0")
        self.kea_config = os.path.join(self.tmp.name, "kea-dhcp4.conf")

    def stub(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w") as handle:
            handle.write(f"#!/usr/bin/bash\n{body}\n")
        os.chmod(path, 0o755)

    def set(self, name, value="x"):
        with open(os.path.join(self.state, name), "w") as handle:
            handle.write(value)

    def check(self):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", STATE=self.state, FREEZY_BOOT_WAIT="9",
                   FREEZY_BOOT_KEA_CONFIG=self.kea_config)
        done = subprocess.run([CHECK], env=env, capture_output=True, text=True)
        return done.returncode, done.stdout

    def test_a_good_boot_passes_even_when_the_arena_is_still_starting(self):
        self.assertEqual(self.check(), (0, ""))

    def test_a_server_that_never_loaded_a_match_does_not_need_kea(self):
        self.set("freezy-kea.service", "inactive")
        self.assertEqual(self.check()[0], 0)

    def test_kea_must_run_once_it_has_a_configuration(self):
        self.set("freezy-kea.service", "activating")
        open(self.kea_config, "w").close()
        code, said = self.check()
        self.assertEqual(code, 1)
        self.assertIn("Kea", said)

    def test_an_arena_that_never_answers_fails_the_boot(self):
        self.set("no-arena")
        code, said = self.check()
        self.assertEqual(code, 1)
        self.assertIn("the arena did not answer", said)

    def test_a_missing_filter_fails_the_boot(self):
        self.set("no-filter")
        code, said = self.check()
        self.assertEqual(code, 1)
        self.assertIn("filter", said)

    def test_a_failed_boot_step_fails_the_boot_and_is_named(self):
        self.set("freezy-data.service", "failed")
        code, said = self.check()
        self.assertEqual(code, 1)
        self.assertIn("freezy-data.service did not finish: failed", said)

    def test_every_check_is_local(self):
        # A field server with no switch attached and no way out must not roll back a good image.
        with open(CHECK) as handle:
            text = handle.read()
        self.assertIn("http://127.0.0.1:8080/", text)
        self.assertNotRegex(text, r"ping|https://|10\.0\.100\.")

    def test_the_check_is_shipped_runnable_and_greenboot_is_on(self):
        self.assertTrue(os.stat(CHECK).st_mode & stat.S_IXUSR)
        with open(os.path.join(HERE, "install.sh")) as handle:
            install = handle.read()
        self.assertRegex(install, r"dnf [^#]*install [^#]*\bgreenboot\b")
        self.assertRegex(install, r"systemctl enable [^#]*\bgreenboot-healthcheck\.service\b")

    def test_the_rollback_is_armed_at_every_shutdown(self):
        # In a test a bad image stayed for good: greenboot's step that arms the rollback never ran,
        # because nothing stopped its unit at shutdown.
        with open(os.path.join(HERE, "files", "usr", "lib", "systemd", "system",
                               "greenboot-set-rollback-trigger.service.d", "10-freezy.conf")) as handle:
            text = handle.read()
        self.assertRegex(text, r"(?m)^Conflicts=final\.target$")
        self.assertRegex(text, r"(?m)^Before=final\.target$")


if __name__ == "__main__":
    unittest.main()
