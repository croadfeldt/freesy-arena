"""Tests for freezy-jump-role. Run: python3 -m unittest deploy/jump/test_freezy_jump_role.py"""
import importlib.machinery
import importlib.util
import os
import pathlib
import re
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
loader = importlib.machinery.SourceFileLoader("freezy_jump_role", os.path.join(HERE, "freezy-jump-role"))
mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("freezy_jump_role", loader))
loader.exec_module(mod)

CARDS = {"52:54:00:00:00:01": "enp1s0", "52:54:00:00:00:02": "enp2s0"}
CFG = {"role": "internal", "outside_mac": "52:54:00:00:00:01", "inside_mac": "52:54:00:00:00:02",
       "vars": {"freezy_fms_gateway": "10.0.100.1", "freezy_jump_role": "external"}}


class PlaybookVarsTest(unittest.TestCase):
    def test_cards_are_found_by_mac_whatever_their_names(self):
        got = mod.playbook_vars(CFG, CARDS)
        self.assertEqual(got["freezy_jump_outside"], {"ifname": "enp1s0", "connection": "external"})
        self.assertEqual(got["freezy_jump_inside"], {"ifname": "enp2s0", "connection": "internal"})

    def test_mac_addresses_match_in_any_case(self):
        got = mod.playbook_vars(dict(CFG, inside_mac="52:54:00:00:00:02".upper()), CARDS)
        self.assertEqual(got["freezy_jump_inside"]["ifname"], "enp2s0")

    def test_the_role_given_wins_over_one_in_the_settings(self):
        self.assertEqual(mod.playbook_vars(CFG, CARDS)["freezy_jump_role"], "internal")

    def test_the_field_servers_settings_are_passed_on(self):
        self.assertEqual(mod.playbook_vars(CFG, CARDS)["freezy_fms_gateway"], "10.0.100.1")

    def test_the_image_never_copies_files_into_its_read_only_usr(self):
        self.assertIs(mod.playbook_vars(CFG, CARDS)["freezy_jump_files_installed"], True)

    def test_an_unknown_role_is_refused(self):
        with self.assertRaisesRegex(ValueError, "unknown role"):
            mod.playbook_vars(dict(CFG, role="router"), CARDS)

    def test_a_card_that_is_not_in_the_machine_is_refused(self):
        with self.assertRaisesRegex(ValueError, "inside"):
            mod.playbook_vars(dict(CFG, inside_mac="52:54:00:00:00:09"), CARDS)

    def test_one_card_given_for_both_sides_is_refused(self):
        with self.assertRaisesRegex(ValueError, "same card"):
            mod.playbook_vars(dict(CFG, inside_mac=CFG["outside_mac"]), CARDS)


class KeysTest(unittest.TestCase):
    def test_keys_are_written_for_root_only_and_replaced_whole(self):
        with tempfile.TemporaryDirectory() as home:
            mod.install_keys(["ssh-ed25519 AAAA one", " ssh-ed25519 BBBB two\n"], home)
            path = os.path.join(home, ".ssh", "authorized_keys")
            self.assertEqual(pathlib.Path(path).read_text(), "ssh-ed25519 AAAA one\nssh-ed25519 BBBB two\n")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            mod.install_keys(["ssh-ed25519 CCCC three"], home)
            self.assertEqual(pathlib.Path(path).read_text(), "ssh-ed25519 CCCC three\n")


class ImageTest(unittest.TestCase):
    """What the image must hold for the scripts and the playbook to find each other."""

    def read(self, *parts):
        with open(os.path.join(HERE, *parts)) as handle:
            return handle.read()

    def enabled(self):
        return re.findall(r"(freezy-[a-z-]+\.service)",
                          self.read("Containerfile").split("systemctl enable")[1].split("&&")[0])

    def test_every_unit_the_image_enables_is_copied_into_it(self):
        self.assertTrue(self.enabled())
        for unit in self.enabled():
            self.assertIn("deploy/jump/" + unit, self.read("Containerfile"), unit)

    def test_the_dhcp_server_is_started_by_the_playbook_not_at_early_boot(self):
        # Enabled at boot, dnsmasq started before the inside card existed and did not listen on it,
        # so after a reboot nothing was handed an address.
        self.assertEqual(self.enabled(), ["freezy-jump-role.service"])
        text = self.read("..", "host", "ansible", "jump_vm.yaml")
        task = text.split("- name: Start the DHCP server if it is not running")[1].split("- name:")[0]
        self.assertIn("state: started", task)
        self.assertLess(text.index("Take the admin network's gateway address"),
                        text.index("Start the DHCP server if it is not running"))

    def test_every_script_a_unit_starts_is_copied_into_the_image(self):
        text = self.read("Containerfile")
        for unit in [f for f in os.listdir(HERE) if f.endswith(".service")]:
            for script in re.findall(r"ExecStart=/usr/local/sbin/(\S+)", self.read(unit)):
                self.assertIn("deploy/jump/" + script, text, "%s starts %s" % (unit, script))

    def test_the_role_unit_is_not_ordered_against_units_the_playbook_restarts(self):
        # The playbook restarts the DHCP units, which start after freezy-transit.service and
        # freezy-admin-router.service. Ordering those after this unit hung the first boot for good.
        unit = self.read("freezy-jump-role.service")
        self.assertNotRegex(unit, r"(?m)^Before=")
        self.assertNotIn("freezy-transit.service", self.enabled())
        self.assertNotIn("freezy-admin-router.service", self.enabled())

    def test_a_card_is_moved_onto_the_connection_made_for_it(self):
        # A new machine's cards start on NetworkManager's automatic connections, outside our zones.
        text = self.read("..", "host", "ansible", "jump_vm.yaml")
        self.assertIn("connection up {{ item.item.connection }}", text)
        self.assertIn("connection.autoconnect-priority 10", text)

    def test_the_only_crossing_between_zones_is_inside_to_outside(self):
        # firewalld 2 forwards nothing between zones without a policy; without this one a machine
        # behind the jump machine resolved names and reached nothing.
        text = self.read("..", "host", "ansible", "jump_vm.yaml")
        self.assertIn("--add-ingress-zone internal", text)
        self.assertIn("--add-egress-zone external", text)
        self.assertNotIn("--add-ingress-zone external", text)
        self.assertNotIn("--add-egress-zone internal", text)
        self.assertIn("freezy_zone.changed or freezy_policy.changed", text)

    def test_the_playbook_is_where_the_role_script_looks(self):
        self.assertEqual(os.path.dirname(mod.PLAYBOOK), "/usr/share/freezy-jump/ansible")
        self.assertIn("deploy/host/ansible/jump_vm.yaml deploy/host/ansible/vars.yaml /usr/share/freezy-jump/ansible/",
                      self.read("Containerfile"))

    def test_the_playbook_copies_nothing_when_the_files_are_in_the_image(self):
        text = self.read("..", "host", "ansible", "jump_vm.yaml")
        tasks = re.split(r"\n    - name: ", text)
        copying = [t for t in tasks if "freezy_jump_src }}/" in t]
        self.assertEqual(len(copying), 2)
        for task in copying:
            self.assertIn("not freezy_jump_files_installed", task, task.splitlines()[0])

    def test_a_new_machine_does_not_wait_for_an_address_the_venue_may_never_give(self):
        # Seen in a VM: a field server started with no venue network. Each new jump machine waited
        # 45 seconds for an address on its outside card, and its whole setup failed.
        with open(os.path.join(HERE, "..", "host", "ansible", "jump_vm.yaml")) as handle:
            playbook = handle.read()
        ups = re.findall(r"command: (nmcli .*connection up .*)", playbook)
        self.assertTrue(ups)
        for command in ups:
            self.assertIn("--wait 0", command)

    def test_the_machine_reports_its_setup_where_the_field_server_reads_it(self):
        # freezy-jump on the field server reads these words from the machine's serial console.
        with open(os.path.join(HERE, "freezy-jump-role")) as handle:
            script = handle.read()
        with open(os.path.join(HERE, "..", "host", "freezy-jump")) as handle:
            marker = re.search(r'MARKER = re\.compile\(r"freezy-jump-role: \(([^)]*)\)"\)', handle.read()).group(1)
        self.assertEqual(marker.split("|"), ["setting up", "set up", "FAILED"])
        self.assertIn('"freezy-jump-role: setting up as %s', script)
        self.assertIn('("set up" if code == 0 else "FAILED")', script)
        with open(os.path.join(HERE, "freezy-jump-role.service")) as handle:
            self.assertIn("StandardOutput=journal+console", handle.read())
        with open(os.path.join(HERE, "Containerfile")) as handle:
            self.assertIn("console=ttyS0", handle.read())


if __name__ == "__main__":
    unittest.main()
