"""The arena's database backups are copied off the server, and a copy that did not happen is a failure.

Run: python3 -m unittest deploy/image/test_freezy_backup.py
"""
import datetime
import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def load():
    loader = importlib.machinery.SourceFileLoader("freezy_backup", os.path.join(HERE, "freezy-backup"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("freezy_backup", loader))
    loader.exec_module(module)
    module.say = lambda message: None
    return module


backup = load()
WHEN = datetime.datetime(2026, 3, 14, 15, 9, 26, tzinfo=datetime.timezone.utc)


class Done:
    def __init__(self, returncode=0, stdout=""):
        self.returncode, self.stdout = returncode, stdout


class Machine:
    """Stands in for mount, umount, findmnt, sync and rsync. rsync really copies, into `disk` when the
    destination is under the mount point, so a test can look at what landed."""

    def __init__(self, folder, already_mounted=None, fail=()):
        self.disk = os.path.join(folder, "disk")
        self.mount = os.path.join(folder, "mnt")
        self.labels = os.path.join(folder, "by-label")
        os.makedirs(self.disk)
        os.makedirs(self.labels)
        self.already_mounted, self.fail, self.ran, self.is_mounted = already_mounted, fail, [], False

    def plug_in(self, label):
        open(os.path.join(self.labels, label), "w").close()

    def __call__(self, command, **_):
        self.ran.append(command[0])
        if command[0] in self.fail:
            return Done(1)
        if command[0] == "findmnt":
            return Done(0, (self.already_mounted or "") + "\n")
        if command[0] == "mount":
            # The stand-in for mounting: the mount point becomes the disk.
            os.rmdir(self.mount)
            os.symlink(self.disk, self.mount)
            self.is_mounted = True
        if command[0] == "umount":
            os.unlink(self.mount)
            self.is_mounted = False
        if command[0] == "rsync":
            source, destination = command[-2], command[-1]
            for name in os.listdir(source):
                shutil.copy2(os.path.join(source, name), destination)
        return Done(0)


class Case(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder)
        self.source = os.path.join(self.folder, "backups")
        self.last = os.path.join(self.folder, "backup.last")
        os.makedirs(self.source)
        self.machine = Machine(self.folder)

    def arena_writes(self, name):
        with open(os.path.join(self.source, name), "w") as handle:
            handle.write(name)

    def copy(self, target):
        return backup.copy({"freezy_backup_target": target}, source=self.source, last=self.last,
                           run=self.machine, now=WHEN, labels=self.machine.labels, mount=self.machine.mount)

    def on_disk(self):
        folder = os.path.join(self.machine.disk, "freezy-backups")
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


class OffTest(Case):
    def test_with_no_target_nothing_runs_and_nothing_fails(self):
        self.arena_writes("Event_20260314150000_post_qualification_match_Q1.db")
        self.assertIn("stay on this server only", self.copy(""))
        self.assertEqual(self.machine.ran, [])
        self.assertFalse(os.path.exists(self.last))

    def test_the_shipped_default_is_off(self):
        import yaml
        with open(os.path.join(HERE, "..", "host", "ansible", "vars.yaml")) as handle:
            self.assertEqual(backup.target(yaml.safe_load(handle)), (None, None))

    def test_no_backups_yet_is_not_a_failure(self):
        self.machine.plug_in("FREEZYBAK")
        self.assertIn("no backups yet", self.copy("label:FREEZYBAK"))
        self.assertEqual(self.machine.ran, [])


class DiskTest(Case):
    def test_backups_land_on_the_labelled_disk_and_it_is_unmounted_after(self):
        self.machine.plug_in("FREEZYBAK")
        self.arena_writes("Event_20260314150000_post_qualification_match_Q1.db")
        self.arena_writes("Event_20260314150700_post_qualification_match_Q2.db")
        said = self.copy("label:FREEZYBAK")
        self.assertEqual(self.on_disk(), ["Event_20260314150000_post_qualification_match_Q1.db",
                                          "Event_20260314150700_post_qualification_match_Q2.db"])
        self.assertEqual(self.machine.ran, ["findmnt", "mount", "rsync", "umount"])
        self.assertFalse(self.machine.is_mounted)
        self.assertIn("Copied 2 backups to the disk labelled FREEZYBAK", said)
        with open(self.last) as handle:
            self.assertEqual(handle.read(), "2026-03-14T15:09:26+00:00 2 "
                                            "Event_20260314150700_post_qualification_match_Q2.db\n")

    def test_a_disk_that_is_not_plugged_in_is_a_failure(self):
        # The point of the timer's unit failing: a backup disk that walked off shows in `systemctl --failed`.
        self.arena_writes("Event_20260314150000_post_qualification_match_Q1.db")
        with self.assertRaisesRegex(backup.Failed, "no disk labelled FREEZYBAK is plugged in"):
            self.copy("label:FREEZYBAK")
        self.assertFalse(os.path.exists(self.last))

    def test_a_failed_copy_is_a_failure_and_the_disk_is_still_unmounted(self):
        self.machine.plug_in("FREEZYBAK")
        self.machine.fail = ("rsync",)
        self.arena_writes("Event_20260314150000_post_qualification_match_Q1.db")
        with self.assertRaisesRegex(backup.Failed, "the copy to the disk labelled FREEZYBAK failed"):
            self.copy("label:FREEZYBAK")
        self.assertEqual(self.machine.ran[-1], "umount")
        self.assertFalse(os.path.exists(self.last), "a failed copy must not be recorded as the last good one")

    def test_a_disk_that_will_not_mount_is_a_failure(self):
        self.machine.plug_in("FREEZYBAK")
        self.machine.fail = ("mount",)
        self.arena_writes("Event_20260314150000_post_qualification_match_Q1.db")
        with self.assertRaisesRegex(backup.Failed, "could not mount"):
            self.copy("label:FREEZYBAK")
        self.assertNotIn("rsync", self.machine.ran)

    def test_a_disk_somebody_already_mounted_is_used_there_and_left_mounted(self):
        self.machine.plug_in("FREEZYBAK")
        self.machine.already_mounted = self.machine.disk
        self.arena_writes("Event_20260314150000_post_qualification_match_Q1.db")
        self.copy("label:FREEZYBAK")
        self.assertEqual(self.on_disk(), ["Event_20260314150000_post_qualification_match_Q1.db"])
        self.assertEqual(self.machine.ran, ["findmnt", "rsync", "sync"])

    def test_nothing_is_deleted_at_the_target(self):
        # A database restored or cleared on the server must not take the copies with it.
        self.machine.plug_in("FREEZYBAK")
        self.arena_writes("Event_20260314150000_post_qualification_match_Q1.db")
        self.copy("label:FREEZYBAK")
        os.unlink(os.path.join(self.source, "Event_20260314150000_post_qualification_match_Q1.db"))
        self.arena_writes("Event_20260314160000_pre_clear.db")
        self.copy("label:FREEZYBAK")
        self.assertEqual(len(self.on_disk()), 2)
        self.assertFalse(any(word.startswith("--del") or word == "--remove-source-files"
                             for word in backup.rsync_command("/a", "/b")))

    def test_a_label_that_could_name_another_path_is_refused(self):
        for label in ("../sda1", "a/b", "", "-x", "two words"):
            with self.subTest(label=label), self.assertRaises(backup.Failed):
                backup.target({"freezy_backup_target": "label:" + label})


class RsyncTest(Case):
    def test_an_rsync_destination_gets_the_folder_and_the_key_when_there_is_one(self):
        key = os.path.join(self.folder, "backup_key")
        open(key, "w").close()
        ran = []
        backup.to_rsync("backup@host:/srv/freezy", source=self.source, key=key,
                        run=lambda command, **_: ran.append(command) or Done())
        self.assertEqual(ran[0][-2:], [self.source + "/", "backup@host:/srv/freezy/"])
        self.assertIn(f"ssh -i {key} -o BatchMode=yes", ran[0][ran[0].index("-e") + 1])

    def test_without_a_key_file_ssh_is_left_to_its_own_settings(self):
        ran = []
        backup.to_rsync("backup@host:/srv/freezy", source=self.source, key=os.path.join(self.folder, "none"),
                        run=lambda command, **_: ran.append(command) or Done())
        self.assertNotIn("-e", ran[0])

    def test_a_failed_rsync_is_a_failure(self):
        self.arena_writes("Event_20260314150000_post_qualification_match_Q1.db")
        self.machine.fail = ("rsync",)
        with self.assertRaisesRegex(backup.Failed, "the copy to backup@host:/srv/freezy failed"):
            backup.copy({"freezy_backup_target": "backup@host:/srv/freezy"}, source=self.source,
                        last=self.last, run=self.machine, key=os.path.join(self.folder, "none"))
        self.assertFalse(os.path.exists(self.last))

    def test_a_destination_that_would_be_read_as_an_option_is_refused(self):
        for value in ("--delete /", "-e sh"):
            with self.subTest(value=value), self.assertRaises(backup.Failed):
                backup.target({"freezy_backup_target": value})

    @unittest.skipUnless(shutil.which("rsync"), "rsync is not installed here")
    def test_the_real_rsync_takes_the_command(self):
        self.arena_writes("Event_20260314150000_post_qualification_match_Q1.db")
        destination = os.path.join(self.folder, "there")
        os.makedirs(destination)
        backup.to_rsync(destination, source=self.source, key=os.path.join(self.folder, "none"))
        self.assertEqual(os.listdir(destination), ["Event_20260314150000_post_qualification_match_Q1.db"])


class StatusTest(Case):
    def test_it_says_when_the_newest_backup_has_not_left_the_server(self):
        self.machine.plug_in("FREEZYBAK")
        self.arena_writes("Event_20260314150000_post_qualification_match_Q1.db")
        self.copy("label:FREEZYBAK")
        settings = {"freezy_backup_target": "label:FREEZYBAK"}
        self.assertNotIn("The newest backup on this server has not been copied yet.",
                         backup.status(settings, source=self.source, last=self.last))
        self.arena_writes("Event_20260314150700_post_qualification_match_Q2.db")
        lines = backup.status(settings, source=self.source, last=self.last)
        self.assertEqual(lines[0], "Backups go to: the disk labelled FREEZYBAK")
        self.assertIn("The newest backup on this server has not been copied yet.", lines)

    def test_before_any_copy_it_says_never(self):
        lines = backup.status({}, source=self.source, last=self.last)
        self.assertEqual(lines[0], "Backups go to: nowhere (freezy_backup_target is empty)")
        self.assertEqual(lines[-1], "Last copy: never")


class CommandTest(Case):
    def test_exit_status_is_1_only_when_a_set_target_was_not_reached(self):
        self.arena_writes("Event_20260314150000_post_qualification_match_Q1.db")
        places = dict(source=self.source, last=self.last, run=self.machine, labels=self.machine.labels,
                      mount=self.machine.mount)
        self.assertEqual(backup.main([], settings={}, **places), 0)
        with open(os.devnull, "w") as quiet:
            stderr, backup.sys.stderr = backup.sys.stderr, quiet
            try:
                self.assertEqual(backup.main([], settings={"freezy_backup_target": "label:FREEZYBAK"}, **places), 1)
            finally:
                backup.sys.stderr = stderr
        self.machine.plug_in("FREEZYBAK")
        self.assertEqual(backup.main([], settings={"freezy_backup_target": "label:FREEZYBAK"}, **places), 0)


class ImageTest(unittest.TestCase):
    def read(self, *path):
        with open(os.path.join(HERE, *path)) as handle:
            return handle.read()

    def test_the_image_installs_the_command_and_turns_the_timer_on(self):
        install = self.read("install.sh")
        self.assertIn('"$src/deploy/image/freezy-backup" /usr/libexec/freezy-backup', install)
        self.assertRegex(install, r"systemctl enable [^\n]*(\\\n[^\n]*)*freezy-backup\.timer")
        self.assertIn(" rsync ", install)

    def test_the_unit_runs_the_command_after_the_kept_data_is_mounted(self):
        unit = self.read("files", "usr", "lib", "systemd", "system", "freezy-backup.service")
        self.assertIn("ExecStart=/usr/libexec/freezy-backup\n", unit)
        self.assertIn("After=freezy-data.service", unit)

    def test_the_command_reads_the_arenas_backups_where_the_image_keeps_them(self):
        self.assertIn("Volume=/var/lib/freezy/arena:/data:", self.read("install.sh"))
        self.assertEqual(backup.SOURCE, "/var/lib/freezy/arena/db/backups")
        # The arena's own folder name, under its data folder.
        self.assertIn('const backupsDir = "db/backups"', self.read("..", "..", "model", "database.go"))


if __name__ == "__main__":
    unittest.main()
