"""Tests for freezy-admin-router. Run: python3 -m unittest deploy/jump/test_freezy_admin_router.py"""
import importlib.machinery
import importlib.util
import os
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "freezy-admin-router")
loader = importlib.machinery.SourceFileLoader("freezy_admin_router", SCRIPT)
mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("freezy_admin_router", loader))
loader.exec_module(mod)

CFG = {"inside_connection": "internal", "inside_interface": "enp2s0", "address": "10.0.100.1/24",
       "dhcp_first": "10.0.100.100", "dhcp_last": "10.0.100.199", "reserved": ["10.0.100.5"]}


class PlanTest(unittest.TestCase):
    def test_the_defaults_give_the_gateway_and_the_range(self):
        self.assertEqual(mod.plan(CFG), {"address": "10.0.100.1/24", "gateway": "10.0.100.1",
                                         "netmask": "255.255.255.0", "first": "10.0.100.100",
                                         "last": "10.0.100.199"})

    def test_a_range_that_would_hand_out_the_fms_address_is_refused(self):
        with self.assertRaisesRegex(ValueError, "10.0.100.5"):
            mod.plan(dict(CFG, dhcp_first="10.0.100.2"))

    def test_a_range_that_would_hand_out_the_gateway_is_refused(self):
        with self.assertRaisesRegex(ValueError, "the gateway"):
            mod.plan(dict(CFG, dhcp_first="10.0.100.1", reserved=[]))

    def test_a_range_outside_the_admin_network_is_refused(self):
        with self.assertRaisesRegex(ValueError, "not inside"):
            mod.plan(dict(CFG, dhcp_last="10.0.101.20"))

    def test_a_backwards_range_is_refused(self):
        with self.assertRaisesRegex(ValueError, "backwards"):
            mod.plan(dict(CFG, dhcp_first="10.0.100.199", dhcp_last="10.0.100.100"))


class DhcpConfigTest(unittest.TestCase):
    def test_it_serves_dns_and_dhcp_on_the_inside_card_only(self):
        lines = mod.dhcp_config(CFG, mod.plan(CFG)).splitlines()
        self.assertIn("interface=enp2s0", lines)
        self.assertIn("except-interface=lo", lines)
        self.assertNotIn("port=0", lines)
        self.assertIn("dhcp-range=10.0.100.100,10.0.100.199,255.255.255.0,12h", lines)
        self.assertIn("dhcp-option=option:router,10.0.100.1", lines)
        self.assertIn("dhcp-option=option:dns-server,10.0.100.1", lines)


class MainTest(unittest.TestCase):
    """main() against a fake machine: the settings file, nmcli and arping are stood in for."""

    def run_main(self, now, config_on_disk, someone_answers, on_the_card=None):
        calls = []
        if on_the_card is None:
            on_the_card = now.startswith("manual")

        def fake_run(*cmd):
            calls.append(cmd)
            if cmd[0] == "ip":
                return "2: enp2s0    inet 10.0.100.1/24 brd 10.0.100.255 scope global enp2s0\n" if on_the_card else ""
            return now if cmd[:2] == ("nmcli", "-g") else ""

        files = {mod.CONFIG: __import__("json").dumps(CFG)}
        if config_on_disk is not None:
            files[mod.DHCP_CONFIG] = config_on_disk
        written = {}

        def fake_open(path, mode="r"):
            if "w" in mode:
                handle = mock.mock_open()()
                handle.write.side_effect = lambda text: written.__setitem__(path, text)
                return handle
            if path not in files:
                raise FileNotFoundError(path)
            return mock.mock_open(read_data=files[path])()

        with mock.patch.object(mod, "run", fake_run), mock.patch("builtins.open", fake_open), \
                mock.patch.object(mod, "answered", return_value=someone_answers) as probe, \
                mock.patch("builtins.print"):
            code = mod.main(["freezy-admin-router"])
        return code, calls, written, probe

    def test_a_free_address_is_taken(self):
        code, calls, written, probe = self.run_main("disabled\n\n", None, someone_answers=False)
        self.assertEqual(code, 0)
        probe.assert_called_once_with("enp2s0", "10.0.100.1")
        self.assertIn(mod.DHCP_CONFIG, written)
        self.assertTrue(any(c[:3] == ("nmcli", "connection", "modify") and "10.0.100.1/24" in c for c in calls))
        self.assertIn(tuple(mod.DHCP_RESTART), calls)

    def test_an_address_a_router_already_holds_is_left_alone(self):
        code, calls, written, _ = self.run_main("disabled\n\n", None, someone_answers=True)
        self.assertEqual(code, 1)
        self.assertEqual(written, {})
        self.assertFalse(any(c[:3] == ("nmcli", "connection", "modify") for c in calls))

    def test_its_own_address_is_not_probed_again(self):
        # Once the machine holds the address, the answer it would hear is its own.
        wanted = mod.dhcp_config(CFG, mod.plan(CFG))
        code, calls, written, probe = self.run_main("manual\n10.0.100.1/24\n", wanted, someone_answers=True)
        self.assertEqual(code, 0)
        probe.assert_not_called()
        self.assertEqual(written, {})

    def test_an_address_it_held_before_and_a_router_holds_now_is_left_alone(self):
        # Seen in a VM: the internal machine was turned off, a router took the gateway address, and
        # the machine was started again from its kept disk. Its connection still named the address,
        # so it skipped the question, and failed later at a check that had nothing to do with it.
        wanted = mod.dhcp_config(CFG, mod.plan(CFG))
        code, calls, written, probe = self.run_main("manual\n10.0.100.1/24\n", wanted, someone_answers=True,
                                                    on_the_card=False)
        self.assertEqual(code, 1)
        probe.assert_called_once_with("enp2s0", "10.0.100.1")
        self.assertFalse(any(c[:3] == ("nmcli", "connection", "up") for c in calls))

    def test_an_address_it_held_before_and_nobody_holds_now_is_taken_back(self):
        wanted = mod.dhcp_config(CFG, mod.plan(CFG))
        code, calls, _, _ = self.run_main("manual\n10.0.100.1/24\n", wanted, someone_answers=False,
                                          on_the_card=False)
        self.assertEqual(code, 0)
        self.assertTrue(any(c[:3] == ("nmcli", "connection", "up") for c in calls))

    def test_networkmanager_is_told_to_check_the_address_before_using_it(self):
        _, calls, _, _ = self.run_main("disabled\n\n", None, someone_answers=False)
        modify = next(c for c in calls if c[:3] == ("nmcli", "connection", "modify"))
        self.assertEqual(modify[modify.index("ipv4.dad-timeout") + 1], "3000")


if __name__ == "__main__":
    unittest.main()
