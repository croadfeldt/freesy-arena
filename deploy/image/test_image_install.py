"""Every script a boot-time playbook runs must be in the image.

Run: python3 -m unittest deploy/image/test_image_install.py

In the image the playbooks live in /usr/share/freezy-net, so a playbook's `{{ playbook_dir }}/../NAME`
is /usr/share/NAME. deploy/image/install.sh has to put NAME there. The image's first build left one out
(freezy-firewalld-zones), and host setup failed at every boot.
"""
import glob
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLAYBOOKS = os.path.join(HERE, "..", "host", "ansible")
# jump_vm.yaml runs inside the jump machine, not on the field server.
NOT_ON_THE_HOST = {"jump_vm.yaml"}
# `{{ freezy_src }}/NAME` or `{{ playbook_dir }}/../NAME`, where NAME is a file beside the playbooks' folder.
RUNS = re.compile(r"\{\{\s*(?:freezy_src\s*\}\}|playbook_dir\s*\}\}/\.\.)/([A-Za-z0-9][A-Za-z0-9._-]*)")


def scripts_run():
    found = {}
    for path in sorted(glob.glob(os.path.join(PLAYBOOKS, "*.yaml"))):
        if os.path.basename(path) in NOT_ON_THE_HOST:
            continue
        with open(path) as handle:
            for name in RUNS.findall(handle.read()):
                found.setdefault(name, os.path.basename(path))
    return found


class ImageInstallTest(unittest.TestCase):
    def test_the_playbooks_do_run_scripts(self):
        # Guards the pattern above: if it stops matching, the next test passes for the wrong reason.
        self.assertIn("freezy-firewalld-zones", scripts_run())
        self.assertIn("freezy-vm-interfaces", scripts_run())

    def test_every_script_a_playbook_runs_is_installed(self):
        with open(os.path.join(HERE, "install.sh")) as handle:
            install = handle.read()
        for name, playbook in scripts_run().items():
            with self.subTest(script=name, playbook=playbook):
                self.assertTrue(os.path.exists(os.path.join(HERE, "..", "host", name)),
                                f"{playbook} runs {name}, which is not in deploy/host")
                installed = re.search(rf'"\$host/{re.escape(name)}" /usr/share/{re.escape(name)}\b', install)
                self.assertTrue(installed, f"{playbook} runs {name}; install.sh does not put it in /usr/share")

    def test_a_container_that_takes_the_hosts_time_zone_has_one_to_take(self):
        # Timezone=local makes podman read /etc/localtime, which a fresh `bootc install` does not have.
        # The arena then failed to start, over and over. The image's tmpfiles must make the link.
        with open(os.path.join(HERE, "..", "freezy-arena.container")) as handle:
            if "Timezone=local" not in handle.read():
                self.skipTest("the arena's container no longer takes the host's time zone")
        with open(os.path.join(HERE, "files", "usr", "lib", "tmpfiles.d", "freezy-image.conf")) as handle:
            links = [line.split() for line in handle if line.startswith("L ")]
        self.assertTrue(any(fields[1] == "/etc/localtime" and fields[-1].startswith("../usr/share/zoneinfo/")
                            for fields in links),
                        "nothing in the image's tmpfiles makes /etc/localtime")


class JumpMachinesTest(unittest.TestCase):
    """The image starts the jump machines the settings ask for (deploy/host/freezy-jump)."""

    def setUp(self):
        with open(os.path.join(HERE, "install.sh")) as handle:
            self.install = handle.read()
        with open(os.path.join(HERE, "..", "host", "freezy-jump")) as handle:
            self.command = handle.read()

    def constant(self, name):
        return re.search(rf'^{name} = "([^"]+)"', self.command, re.M).group(1)

    def test_the_unit_runs_the_command_where_the_image_puts_it(self):
        with open(os.path.join(HERE, "..", "host", "freezy-jump.service")) as handle:
            started = re.search(r"^ExecStart=(\S+)", handle.read(), re.M).group(1)
        self.assertIn(f'"$host/freezy-jump" {started}\n', self.install)
        self.assertIn('"$host/freezy-jump.service"', self.install)
        self.assertRegex(self.install, r"systemctl enable [^\n]*(\\\n[^\n]*)*freezy-jump\.service")

    def test_the_carried_disk_goes_where_the_command_looks_for_it(self):
        self.assertIn(f'"$images/freezy-jump.qcow2" {self.constant("BASE_DISK")}\n', self.install)

    def test_a_build_without_the_disk_still_builds(self):
        # CI and a quick local build have no disk; only starting a jump machine needs it.
        self.assertIn('if [ -f "$images/freezy-jump.qcow2" ]', self.install)

    def test_the_folder_for_the_machines_disks_exists_at_boot(self):
        with open(os.path.join(HERE, "files", "usr", "lib", "tmpfiles.d", "freezy-image.conf")) as handle:
            made = [line.split()[1] for line in handle if line.startswith("d ")]
        self.assertIn(self.constant("DISKS"), made)

    def test_the_settings_file_the_command_reads_is_the_one_the_image_installs(self):
        # install.sh copies deploy/host/ansible to /usr/share/freezy-net.
        self.assertEqual(self.constant("DEFAULTS"), "/usr/share/freezy-net/vars.yaml")
        self.assertIn('cp -r "$host/ansible/." /usr/share/freezy-net/', self.install)


if __name__ == "__main__":
    unittest.main()
