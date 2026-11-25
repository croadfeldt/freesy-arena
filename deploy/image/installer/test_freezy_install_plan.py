"""The installer keeps the freezy-data partition, and never erases a disk that is not a field server's
without being told to.

Run: python3 -m unittest deploy/image/installer/test_freezy_install_plan.py
"""
import importlib.machinery
import importlib.util
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GIB = 1024 ** 3


def load():
    loader = importlib.machinery.SourceFileLoader("freezy_install_plan", os.path.join(HERE, "freezy-install-plan"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("freezy_install_plan", loader))
    loader.exec_module(module)
    return module


plan = load()


def part(name, gib, label=None, fstype="xfs", mountpoints=None):
    return {"name": name, "type": "part", "ro": False, "size": gib * GIB, "label": label, "fstype": fstype,
            "mountpoints": mountpoints or [None]}


def disk(name, gib, *children, fstype=None, ro=False):
    device = {"name": name, "type": "disk", "ro": ro, "size": gib * GIB, "label": None, "fstype": fstype,
              "mountpoints": [None]}
    if children:
        device["children"] = list(children)
    return device


FIELD_SERVER = disk("sda", 240, part("sda1", 1, fstype="vfat"), part("sda2", 1), part("sda3", 16, "freezy-data"),
                    part("sda4", 222))
INSTALLER_STICK = disk("sdb", 8, part("sdb1", 7, "FREEZY-INSTALL", "iso9660", ["/run/install/repo"]),
                       part("sdb2", 1, fstype="vfat"))


class KeepTest(unittest.TestCase):
    def test_a_reinstall_keeps_the_data_partition_and_erases_the_rest(self):
        lines, said = plan.plan([FIELD_SERVER, INSTALLER_STICK], {})
        self.assertIn("part /var/lib/freezy --onpart=sda3 --noformat", lines)
        self.assertIn("clearpart --list=sda1,sda2,sda4", lines)
        self.assertIn("ignoredisk --only-use=sda", lines)
        self.assertIn("keeping sda3", said)

    def test_nothing_in_a_reinstall_can_reach_the_kept_partition(self):
        # No command that formats, relabels or clears whole disks may appear beside a kept partition.
        lines, _ = plan.plan([FIELD_SERVER], {})
        text = "\n".join(lines)
        for word in ("zerombr", "--all", "--initlabel", "--label=freezy-data"):
            self.assertNotIn(word, text)
        cleared = re.search(r"clearpart --list=(\S+)", text).group(1).split(",")
        self.assertNotIn("sda3", cleared)

    def test_the_system_goes_on_the_disk_that_holds_the_data_whatever_else_is_there(self):
        other = disk("nvme0n1", 500)
        lines, _ = plan.plan([other, FIELD_SERVER], {})
        self.assertIn("ignoredisk --only-use=sda", lines)
        with self.assertRaisesRegex(plan.Refused, "the freezy-data partition is on sda"):
            plan.plan([other, FIELD_SERVER], {"disk": "nvme0n1"})

    def test_a_disk_holding_only_the_data_partition_is_kept_too(self):
        lines, _ = plan.plan([disk("sda", 240, part("sda1", 16, "freezy-data"))], {})
        self.assertIn("clearpart --none", lines)
        self.assertIn("part /var/lib/freezy --onpart=sda1 --noformat", lines)

    def test_two_data_partitions_are_refused(self):
        second = disk("sdc", 240, part("sdc1", 16, "freezy-data"))
        with self.assertRaisesRegex(plan.Refused, "more than one partition is labelled freezy-data: sda3, sdc1"):
            plan.plan([FIELD_SERVER, second], {})

    def test_too_little_room_beside_the_data_partition_is_refused(self):
        with self.assertRaisesRegex(plan.Refused, "too little room beside"):
            plan.plan([disk("sda", 30, part("sda1", 16, "freezy-data"))], {})


class NewTest(unittest.TestCase):
    def test_an_empty_disk_gets_the_system_and_a_new_data_partition(self):
        lines, said = plan.plan([disk("vda", 64), INSTALLER_STICK], {})
        self.assertIn("part /var/lib/freezy --fstype=xfs --label=freezy-data --size=16384 --ondisk=vda", lines)
        self.assertIn("clearpart --all --initlabel --drives=vda", lines)
        self.assertIn("which is empty", said)

    def test_boot_has_its_own_partition_either_way(self):
        # Without it a health check that runs for minutes is cut short (DESIGN.md, "The install must keep /boot mounted").
        for devices in ([disk("vda", 64)], [FIELD_SERVER]):
            lines, _ = plan.plan(devices, {})
            self.assertTrue(any(line.startswith("part /boot --fstype=xfs") for line in lines))
            self.assertIn("reqpart", lines)

    def test_a_disk_that_holds_something_else_is_not_erased_unasked(self):
        windows = disk("sda", 240, part("sda1", 1, fstype="vfat"), part("sda2", 239, "Windows", "ntfs"))
        with self.assertRaisesRegex(plan.Refused, r"sda2 \(Windows, 239 GiB\).*freezy.wipe=yes"):
            plan.plan([windows], {})
        with self.assertRaisesRegex(plan.Refused, "freezy.wipe=yes"):
            plan.plan([disk("sda", 240, fstype="ext4")], {})
        with self.assertRaises(plan.Refused):
            plan.plan([windows], {"wipe": "no"})

    def test_it_is_erased_when_asked(self):
        windows = disk("sda", 240, part("sda1", 239, "Windows", "ntfs"))
        lines, said = plan.plan([windows], {"wipe": "yes"})
        self.assertIn("clearpart --all --initlabel --drives=sda", lines)
        self.assertIn("erasing it", said)

    def test_wipe_does_not_reach_a_kept_partition(self):
        lines, _ = plan.plan([FIELD_SERVER], {"wipe": "yes"})
        self.assertIn("part /var/lib/freezy --onpart=sda3 --noformat", lines)
        self.assertNotIn("zerombr", lines)

    def test_two_disks_and_no_data_partition_need_a_choice(self):
        two = [disk("sda", 240), disk("sdb", 500)]
        with self.assertRaisesRegex(plan.Refused, r"freezy.disk=NAME.*sda \(240 GiB\); sdb \(500 GiB\)"):
            plan.plan(two, {})
        lines, _ = plan.plan(two, {"disk": "sdb"})
        self.assertIn("ignoredisk --only-use=sdb", lines)
        with self.assertRaisesRegex(plan.Refused, "no such disk"):
            plan.plan(two, {"disk": "sdz"})

    def test_the_installers_own_disk_is_never_a_choice(self):
        with self.assertRaisesRegex(plan.Refused, "no disk to install on"):
            plan.plan([INSTALLER_STICK], {})
        with self.assertRaisesRegex(plan.Refused, "no such disk"):
            plan.plan([disk("sda", 240), INSTALLER_STICK], {"disk": "sdb"})

    def test_the_installers_compressed_memory_is_not_a_disk(self):
        # The installer has a zram0 that lsblk lists as a disk. Counted as one, every machine had two
        # disks to choose from and no install started.
        lines, _ = plan.plan([disk("zram0", 8), disk("vda", 64), disk("loop0", 1), disk("sr0", 4)], {})
        self.assertIn("ignoredisk --only-use=vda", lines)

    def test_a_read_only_disk_is_never_a_choice(self):
        with self.assertRaisesRegex(plan.Refused, "no disk to install on"):
            plan.plan([disk("sda", 240, ro=True)], {})

    def test_a_disk_too_small_is_refused(self):
        with self.assertRaisesRegex(plan.Refused, "too small"):
            plan.plan([disk("vda", 30)], {})

    def test_the_data_partitions_size_can_be_set(self):
        lines, _ = plan.plan([disk("vda", 240)], {"data_gb": "64"})
        self.assertIn("part /var/lib/freezy --fstype=xfs --label=freezy-data --size=65536 --ondisk=vda", lines)
        for bad in ("lots", "1"):
            with self.assertRaises(plan.Refused):
                plan.plan([disk("vda", 240)], {"data_gb": bad})


class SettingsTest(unittest.TestCase):
    def test_only_the_freezy_words_are_read(self):
        line = "BOOT_IMAGE=/images/pxeboot/vmlinuz inst.ks=hd:LABEL=FREEZY-INSTALL:/freezy.ks freezy.disk=sda freezy.wipe=yes quiet"
        self.assertEqual(plan.settings(line), {"disk": "sda", "wipe": "yes"})


class KickstartTest(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(HERE, name)) as handle:
            return handle.read()

    def test_the_kickstart_and_the_iso_agree_on_where_things_are(self):
        kickstart, build = self.read("freezy.ks"), self.read("build-iso")
        self.assertIn("python3 /run/install/repo/freezy/freezy-install-plan > /tmp/freezy-storage.ks", kickstart)
        self.assertIn("%include /tmp/freezy-storage.ks", kickstart)
        self.assertIn("--url=/run/install/repo/freezy/image ", kickstart)
        self.assertIn('"$work/freezy/freezy-install-plan"', build)
        self.assertIn('-C "$work/freezy/image"', build)
        self.assertIn('-a "$work/freezy"', build)
        self.assertEqual(plan.MEDIA, "/run/install/repo")

    def test_a_refusal_stops_the_install(self):
        kickstart = self.read("freezy.ks")
        self.assertIn("%pre --erroronfail", kickstart)
        self.assertIn("exit $status", kickstart)

    def test_the_machine_powers_off_and_does_not_restart_into_the_installer(self):
        commands = [line.strip() for line in self.read("freezy.ks").split("%pre")[0].splitlines()]
        self.assertIn("poweroff", commands)
        self.assertNotIn("reboot", commands)

    def test_the_kept_partition_is_mounted_by_the_image_alone(self):
        # The image's label is the one the installer makes and looks for.
        self.assertIn('LABEL = "freezy-data"', self.read(os.path.join("..", "freezy-data")))
        self.assertEqual(plan.LABEL, "freezy-data")
        self.assertIn("/var/lib/freezy", self.read("freezy.ks").split("%post --erroronfail")[1])

    def test_the_kickstart_is_one_the_installer_accepts(self):
        try:
            from pykickstart.parser import KickstartParser
            from pykickstart.version import makeVersion
        except ImportError:
            self.skipTest("pykickstart is not installed here")
        import tempfile
        lines, _ = plan.plan([FIELD_SERVER], {})
        text = self.read("freezy.ks").replace("%include /tmp/freezy-storage.ks", "\n".join(lines))
        with tempfile.NamedTemporaryFile("w", suffix=".ks") as handle:
            handle.write(text)
            handle.flush()
            KickstartParser(makeVersion()).readKickstart(handle.name)


if __name__ == "__main__":
    unittest.main()
