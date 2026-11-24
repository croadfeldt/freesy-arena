"""Tests for freezy-jump. Run: python3 -m unittest deploy/host/test_freezy_jump.py"""
import base64
import importlib.machinery
import importlib.util
import json
import os
import sys
import unittest
from unittest import mock

import yaml

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
loader = importlib.machinery.SourceFileLoader("freezy_jump", os.path.join(HERE, "freezy-jump"))
mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("freezy_jump", loader))
loader.exec_module(mod)

with open(os.path.join(HERE, "ansible", "vars.yaml")) as handle:
    DEFAULTS = yaml.safe_load(handle)
KEYS = ["ssh-ed25519 AAAA someone"]


def settings(**changes):
    return dict(DEFAULTS, **changes)


class WantedTest(unittest.TestCase):
    def test_the_default_runs_both_machines(self):
        # Needs only switches that carry tagged VLANs, whatever their brand.
        self.assertEqual(mod.wanted(DEFAULTS), (["external", "internal"], None))
        self.assertEqual(mod.wanted({}), (["external", "internal"], None))

    def test_a_hardware_router_takes_the_internal_machines_place(self):
        self.assertEqual(mod.wanted(settings(freezy_admin_router="gateway"))[0], ["external"])

    def test_a_field_on_its_own_can_still_have_the_internal_machine(self):
        self.assertEqual(mod.wanted(settings(freezy_venue_isolation=False))[0], ["internal"])

    def test_everything_can_be_off(self):
        got = mod.wanted(settings(freezy_venue_isolation=False, freezy_admin_router="none"))
        self.assertEqual(got, ([], None))

    def test_isolation_with_nothing_routing_the_admin_network_warns_and_is_allowed(self):
        roles, warning = mod.wanted(settings(freezy_admin_router="none"))
        self.assertEqual(roles, ["external"])
        self.assertIn("no way out", warning)

    def test_a_misspelt_setting_is_refused_not_guessed(self):
        with self.assertRaises(mod.Refused):
            mod.wanted(settings(freezy_admin_router="router"))
        with self.assertRaises(mod.Refused):
            mod.wanted(settings(freezy_venue_isolation="yes"))


class DefinitionTest(unittest.TestCase):
    def told(self, role, **changes):
        xml = mod.domain_xml(role, settings(**changes), KEYS)
        return json.loads(base64.b64decode(mod.told(xml)))

    def test_each_role_attaches_to_its_two_networks(self):
        external = mod.cards_of(mod.domain_xml("external", DEFAULTS, KEYS))
        internal = mod.cards_of(mod.domain_xml("internal", DEFAULTS, KEYS))
        self.assertEqual([dev for _, dev in external], ["vlan999", "vlan998"])
        self.assertEqual([dev for _, dev in internal], ["vlan998", "vlan100"])

    def test_vlan_interfaces_come_from_the_settings(self):
        moved = settings(freezy_uplink_vlans=[
            {"name": "venue", "vlan": 7, "connection": "vlan7"},
            {"name": "transit", "vlan": 8, "connection": "vlan8"},
            {"name": "admin", "vlan": 9, "connection": "vlan9"}])
        self.assertEqual([dev for _, dev in mod.cards_of(mod.domain_xml("internal", moved, KEYS))],
                         ["vlan8", "vlan9"])

    def test_a_network_missing_from_the_settings_is_refused(self):
        with self.assertRaisesRegex(mod.Refused, "admin"):
            mod.domain_xml("internal", settings(freezy_uplink_vlans=DEFAULTS["freezy_uplink_vlans"][:2]), KEYS)

    def test_the_machine_is_told_the_cards_it_was_given(self):
        xml = mod.domain_xml("external", DEFAULTS, KEYS)
        told = json.loads(base64.b64decode(mod.told(xml)))
        self.assertEqual([told["outside_mac"], told["inside_mac"]], [m for m, _ in mod.cards_of(xml)])
        self.assertEqual(told["role"], "external")
        self.assertEqual(told["ssh_keys"], KEYS)

    def test_the_two_machines_never_share_a_mac_address(self):
        macs = [m for role in mod.ROLES for m, _ in mod.cards_of(mod.domain_xml(role, DEFAULTS, KEYS))]
        self.assertEqual(len(set(macs)), 4)

    def test_the_servers_settings_reach_the_machine(self):
        told = self.told("internal", freezy_admin_dhcp_first="10.0.100.50")
        self.assertEqual(told["vars"]["freezy_admin_dhcp_first"], "10.0.100.50")
        self.assertEqual(told["vars"]["freezy_fms_gateway"], DEFAULTS["freezy_fms_gateway"])
        self.assertIs(told["vars"]["freezy_transit_dns"], True)

    def test_every_setting_passed_on_is_one_the_defaults_know(self):
        for key in mod.PASSED_ON:
            self.assertIn(key, DEFAULTS, key)

    def test_a_changed_key_changes_what_the_machine_is_told(self):
        before = mod.told(mod.domain_xml("external", DEFAULTS, KEYS))
        after = mod.told(mod.domain_xml("external", DEFAULTS, KEYS + ["ssh-ed25519 BBBB another"]))
        self.assertNotEqual(before, after)


class SetSettingTest(unittest.TestCase):
    def test_an_existing_line_is_replaced_and_the_rest_left_alone(self):
        text = "# mine\nfreezy_field_interface: eno1\nfreezy_admin_router: internal  # default\nother: 1\n"
        self.assertEqual(mod.set_setting(text, "freezy_admin_router", "gateway"),
                         "# mine\nfreezy_field_interface: eno1\nfreezy_admin_router: gateway\nother: 1\n")

    def test_a_missing_line_is_added(self):
        self.assertEqual(mod.set_setting("a: 1", "freezy_venue_isolation", "false"),
                         "a: 1\nfreezy_venue_isolation: false\n")
        self.assertEqual(mod.set_setting("", "freezy_venue_isolation", "false"), "freezy_venue_isolation: false\n")

    def test_what_it_writes_reads_back_as_the_right_type(self):
        text = mod.set_setting(mod.set_setting("", "freezy_venue_isolation", "false"), "freezy_admin_router", "none")
        self.assertEqual(yaml.safe_load(text), {"freezy_venue_isolation": False, "freezy_admin_router": "none"})
        self.assertEqual(mod.wanted(yaml.safe_load(text)), ([], None))


class ApplyTest(unittest.TestCase):
    """apply() against a fake libvirt: which machines get turned on and which off."""

    def run_apply(self, **changes):
        on, off = [], []
        with mock.patch.object(mod, "turn_on", lambda role, *rest: on.append(role)), \
                mock.patch.object(mod, "turn_off", lambda role, say: off.append(role)), \
                mock.patch.object(mod, "read_keys", return_value=KEYS):
            said = []
            code = mod.apply(settings(**changes), say=said.append)
        return code, on, off, said

    def test_the_default_turns_both_on(self):
        self.assertEqual(self.run_apply()[:3], (0, ["external", "internal"], []))

    def test_switching_to_a_hardware_router_turns_the_internal_machine_off(self):
        self.assertEqual(self.run_apply(freezy_admin_router="gateway")[:3], (0, ["external"], ["internal"]))

    def test_one_machine_failing_does_not_stop_the_other(self):
        def turn_on(role, *rest):
            if role == "external":
                raise mod.Refused("no venue interface")
            started.append(role)
        started = []
        with mock.patch.object(mod, "turn_on", turn_on), mock.patch.object(mod, "read_keys", return_value=KEYS):
            code = mod.apply(DEFAULTS, say=lambda line: None)
        self.assertEqual((code, started), (1, ["internal"]))

    def test_no_keys_is_said_out_loud(self):
        with mock.patch.object(mod, "turn_on", lambda *a: None), mock.patch.object(mod, "read_keys", return_value=[]):
            said = []
            mod.apply(DEFAULTS, say=said.append)
        self.assertTrue(any("no ssh keys" in line for line in said))


class StatusTest(unittest.TestCase):
    """What `freezy-jump status` says about a running machine, from its guest agent's answers."""
    FACES = [{"name": "lo", "hardware-address": "00:00:00:00:00:00",
              "ip-addresses": [{"ip-address-type": "ipv4", "ip-address": "127.0.0.1", "prefix": 8}]},
             {"name": "enp1s0", "hardware-address": mod.mac("freezy-jump-internal", "outside"),
              "ip-addresses": [{"ip-address-type": "ipv4", "ip-address": "192.168.254.250", "prefix": 29},
                               {"ip-address-type": "ipv6", "ip-address": "fe80::1", "prefix": 64}]},
             {"name": "enp2s0", "hardware-address": mod.mac("freezy-jump-internal", "inside")}]

    def test_each_card_is_named_by_its_network_with_its_address(self):
        line = mod.describe("internal", mod.addresses(self.FACES), "active")
        self.assertEqual(line, "transit 192.168.254.250/29, admin no address; set up")

    def test_a_machine_whose_setup_failed_says_so_and_where_to_look(self):
        # Seen in a VM: the internal machine refused the gateway address and nothing on the field
        # server showed it; the machine was simply "running".
        line = mod.describe("internal", mod.addresses(self.FACES), "failed")
        self.assertIn("ITS SETUP FAILED", line)
        self.assertIn("freezy-jump log internal", line)

    def test_a_machine_that_is_still_starting_is_not_called_broken(self):
        self.assertEqual(mod.describe("external", None, ""), "not answering yet")
        self.assertIn("setting itself up", mod.describe("external", {}, "activating"))


class ConsoleTest(unittest.TestCase):
    """A machine reports on its own setup on its serial console, which libvirt logs on the field
    server. Its guest agent cannot: SELinux inside the machine keeps the agent away from systemd."""
    CONSOLE = (
        "[    9.1] freezy-jump-role[801]: freezy-jump-role: setting up as internal\r\n"
        "[   20.0] freezy-jump-role[801]: freezy-jump-role: set up\r\n"
        "[    8.7] freezy-jump-role[790]: freezy-jump-role: setting up as internal\r\n"
        "[   12.0] freezy-jump-role[790]: ok: [localhost]\r\n"
        "[   13.0] audit: type=1334 audit(1795554468.173:93): prog-id=67 op=UNLOAD\r\n"
        "[   15.5] freezy-jump-role[790]: freezy-admin-router: something on the admin network already answers at 10.0.100.1.\r\n"
        "[   15.6] freezy-jump-role[790]: freezy-jump-role: FAILED\r\n")

    def test_the_last_thing_a_machine_said_is_its_state(self):
        self.assertEqual(mod.setup_state(self.CONSOLE), "failed")
        self.assertEqual(mod.setup_state(self.CONSOLE.split("[    8.7]")[0]), "active")
        self.assertEqual(mod.setup_state("[    9.1] x: freezy-jump-role: setting up as external\n"), "activating")
        self.assertIsNone(mod.setup_state(""))

    def test_the_log_is_the_latest_setup_and_says_why_it_failed(self):
        log = mod.setup_log(self.CONSOLE)
        self.assertEqual(log[0], "freezy-jump-role: setting up as internal")
        self.assertEqual(log[-1], "freezy-jump-role: FAILED")
        self.assertTrue(any("already answers at 10.0.100.1" in line for line in log))
        self.assertFalse(any(line.startswith("ok: [") for line in log))
        self.assertFalse(any("audit" in line for line in log), "the kernel's console lines are not the setup's")

    def test_a_machine_is_defined_with_its_console_logged(self):
        xml = mod.domain_xml("internal", DEFAULTS, KEYS)
        self.assertEqual(mod.console_log_of(xml), "/var/log/libvirt/qemu/freezy-jump-internal-console.log")


if __name__ == "__main__":
    unittest.main()
