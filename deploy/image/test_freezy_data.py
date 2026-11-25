"""The kept data: what freezy-data moves, what it leaves, and that the image's units point at it.

Run: python3 -m unittest deploy/image/test_freezy_data.py
"""
import importlib.machinery
import importlib.util
import os
import re
import stat
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM = os.path.join(HERE, "files", "usr", "lib", "systemd", "system")


def load():
    path = os.path.join(HERE, "freezy-data")
    loader = importlib.machinery.SourceFileLoader("freezy_data", path)
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("freezy_data", loader))
    loader.exec_module(module)
    return module


data = load()


def read(*parts):
    with open(os.path.join(*parts)) as handle:
        return handle.read()


def put(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


class MoveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = os.path.join(self.tmp.name, "old")
        self.new = os.path.join(self.tmp.name, "new")

    def test_data_moves_into_an_empty_folder(self):
        put(os.path.join(self.old, "event.db"), "the event")
        put(os.path.join(self.old, "db", "backups", "one.db"))
        os.makedirs(self.new)
        self.assertEqual(data.move_in(self.old, self.new), ["db", "event.db"])
        self.assertEqual(read(self.new, "event.db"), "the event")
        self.assertTrue(os.path.exists(os.path.join(self.new, "db", "backups", "one.db")))
        self.assertEqual(os.listdir(self.old), [])

    def test_data_already_there_is_never_overwritten(self):
        # A reinstall finds last event's database on the partition. Whatever sits in an old place must
        # not replace it.
        put(os.path.join(self.old, "event.db"), "stale")
        put(os.path.join(self.new, "event.db"), "the event")
        self.assertEqual(data.move_in(self.old, self.new), [])
        self.assertEqual(read(self.new, "event.db"), "the event")
        self.assertEqual(read(self.old, "event.db"), "stale")

    def test_a_missing_or_empty_old_place_is_fine(self):
        self.assertEqual(data.move_in(self.old, self.new), [])
        os.makedirs(self.old)
        self.assertEqual(data.move_in(self.old, self.new), [])

    def test_only_the_named_files_move(self):
        put(os.path.join(self.old, "last-request.json"), "{}")
        put(os.path.join(self.old, "kea", "leases.csv"))
        self.assertEqual(data.move_in(self.old, self.new, ["last-request.json"]), ["last-request.json"])
        self.assertTrue(os.path.exists(os.path.join(self.old, "kea", "leases.csv")))

    def test_a_partition_added_later_takes_the_root_disks_data(self):
        root_disk = os.path.join(self.tmp.name, "root")
        partition = os.path.join(self.tmp.name, "partition")
        put(os.path.join(root_disk, "arena", "event.db"), "the event")
        put(os.path.join(root_disk, "vm", "freezy-jump-external.qcow2"))
        os.makedirs(os.path.join(root_disk, "kea"))
        put(os.path.join(partition, "vm", "freezy-jump-external.qcow2"), "already here")
        moved = data.adopt(root_disk, partition)
        self.assertEqual(moved, {"arena": ["event.db"]})
        self.assertEqual(read(partition, "arena", "event.db"), "the event")
        self.assertEqual(read(partition, "vm", "freezy-jump-external.qcow2"), "already here")

    def test_the_places_the_image_used_before_are_brought_in(self):
        root = os.path.join(self.tmp.name, "freezy")
        volume = os.path.join(self.tmp.name, "volume")
        net = os.path.join(self.tmp.name, "freezy-net")
        put(os.path.join(volume, "event.db"), "the event")
        put(os.path.join(net, "last-request.json"), "{}")
        put(os.path.join(net, "kea", "kea-leases4.csv"), "lease")
        moved = data.bring_in_old_places(root, {"arena": volume, "kea": os.path.join(net, "kea"), "net": net})
        self.assertEqual(moved, {"arena": ["event.db"], "kea": ["kea-leases4.csv"], "net": ["last-request.json"]})
        self.assertEqual(read(root, "net", "last-request.json"), "{}")
        self.assertEqual(os.listdir(os.path.join(root, "net")), ["last-request.json"])
        # A second boot finds nothing left to move.
        self.assertEqual(data.bring_in_old_places(root, {"arena": volume, "kea": os.path.join(net, "kea"), "net": net}), {})

    def test_the_folders_get_their_modes(self):
        root = os.path.join(self.tmp.name, "freezy")
        me = (os.getuid(), os.getgid())
        data.lay_out(root, {"root": me, data.ARENA_USER: me})
        modes = {name: stat.S_IMODE(os.stat(os.path.join(root, name)).st_mode) for name in os.listdir(root)}
        self.assertEqual(modes, {"arena": 0o750, "kea": 0o755, "net": 0o755, "vm": 0o711})


class ImageUsesKeptDataTest(unittest.TestCase):
    """Each thing a reinstall must keep is read and written under /var/lib/freezy in the image."""

    def setUp(self):
        self.install = read(HERE, "install.sh")

    def rewritten(self, unit_text):
        """The unit as install.sh leaves it: its `sed -i 's|FROM|TO|'` lines applied."""
        for old, new in re.findall(r"sed -i 's\|\^([^|]+)\|([^|]+)\|'", self.install):
            unit_text = re.sub("^" + re.escape(old), new, unit_text, flags=re.M)
        return unit_text

    def test_the_arenas_data_is_bound_from_the_kept_folder(self):
        unit = self.rewritten(read(HERE, "..", "freezy-arena.container"))
        self.assertIn("Volume=/var/lib/freezy/arena:/data:z", unit)
        self.assertNotIn("freezy-arena-data", unit.split("[Container]")[1])

    def test_keas_leases_are_in_the_kept_folder(self):
        unit = self.rewritten(read(HERE, "..", "host", "freezy-kea.container"))
        self.assertIn("Volume=/var/lib/freezy/kea:/var/lib/kea:Z", unit)
        self.assertNotIn("/var/lib/freezy-net", unit.split("[Container]")[1])

    def test_the_last_request_is_in_the_kept_folder(self):
        helper = read(HERE, "..", "host", "freezy-net-helper")
        self.assertIn('os.environ.get("FREEZY_NET_STATE"', helper)
        drop_in = read(SYSTEM, "freezy-net.service.d", "10-image.conf")
        self.assertIn("Environment=FREEZY_NET_STATE=/var/lib/freezy/net", drop_in)

    def test_the_jump_machines_disks_are_in_the_kept_folder(self):
        self.assertIn('DISKS = "/var/lib/freezy/vm"', read(HERE, "..", "host", "freezy-jump"))

    def test_every_folder_in_use_is_one_freezy_data_makes(self):
        made = {name for name, _, _ in data.FOLDERS}
        self.assertEqual(made, {"arena", "kea", "net", "vm"})
        self.assertEqual(data.ROOT, "/var/lib/freezy")

    def test_whatever_uses_kept_data_starts_after_it_is_mounted(self):
        for drop_in in (os.path.join(SYSTEM, "freezy-net.service.d", "10-image.conf"),
                        os.path.join(SYSTEM, "freezy-jump.service.d", "10-image.conf"),
                        os.path.join(HERE, "files", "usr", "share", "containers", "systemd",
                                     "freezy-kea.container.d", "10-image.conf")):
            with self.subTest(drop_in=os.path.relpath(drop_in, HERE)):
                text = read(drop_in)
                self.assertRegex(text, r"(?m)^Requires=.*\bfreezy-data\.service\b")
                self.assertRegex(text, r"(?m)^After=.*\bfreezy-data\.service\b")

    def test_libvirt_starts_after_the_data_is_in_place(self):
        # libvirt starts the jump machines on its own when it comes up. It once did so while their disks
        # were still being moved onto a new partition, and the machines ran on files that no longer
        # existed.
        before = re.search(r"(?m)^Before=(.*)$", read(SYSTEM, "freezy-data.service")).group(1).split()
        self.assertIn("virtqemud.service", before)

    def test_the_arena_waits_for_the_data_step(self):
        # The arena runs in its account's own systemd, which cannot depend on a system unit. It checks
        # for the file the data step writes last, and its unit retries until it is there.
        self.assertIn(f"ExecStartPre=/usr/bin/test -e {data.READY}",
                      read(HERE, "freezy-arena.container.d", "10-image.conf"))
        self.assertIn("Restart=on-failure", read(HERE, "..", "freezy-arena.container"))

    def test_the_step_is_installed_and_enabled(self):
        self.assertIn('"$src/deploy/image/freezy-data" /usr/libexec/freezy-data', self.install)
        self.assertIn("ExecStart=/usr/libexec/freezy-data", read(SYSTEM, "freezy-data.service"))
        self.assertRegex(self.install, r"systemctl enable [^#]*\bfreezy-data\.service\b")


if __name__ == "__main__":
    unittest.main()
