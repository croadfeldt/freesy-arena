"""Tests for freezy-transit-select. Run: python3 -m unittest deploy/jump/test_freezy_transit_select.py"""
import importlib.machinery
import importlib.util
import os
import sys
import unittest

sys.dont_write_bytecode = True
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "freezy-transit-select")
loader = importlib.machinery.SourceFileLoader("freezy_transit_select", SCRIPT)
mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("freezy_transit_select", loader))
loader.exec_module(mod)

CANDIDATES = ["192.168.254.248/29", "172.31.254.248/29", "100.64.254.248/29"]


class ChooseTest(unittest.TestCase):
    def pick(self, venue, current=None):
        return str(mod.choose(venue, CANDIDATES, current))

    def test_ordinary_venue_gets_the_first_candidate(self):
        self.assertEqual(self.pick(["10.0.0.198/24"]), "192.168.254.248/29")

    def test_venue_on_the_first_candidate_moves_to_the_second(self):
        self.assertEqual(self.pick(["192.168.254.20/24"]), "172.31.254.248/29")

    def test_venue_covering_a_candidate_with_a_wide_network_moves_on(self):
        self.assertEqual(self.pick(["192.168.1.5/16"]), "172.31.254.248/29")
        self.assertEqual(self.pick(["192.168.1.5/16", "172.16.0.0/12"]), "100.64.254.248/29")

    def test_a_route_on_the_venue_side_counts_as_in_use(self):
        self.assertEqual(self.pick(["10.0.0.198/24", "192.168.254.0/24"]), "172.31.254.248/29")

    def test_current_choice_is_kept_while_it_is_clear(self):
        # The second candidate was picked at an earlier venue; do not shuffle back to the first.
        self.assertEqual(self.pick(["10.0.0.198/24"], current="172.31.254.254/29"), "172.31.254.248/29")

    def test_current_choice_is_dropped_when_the_venue_overlaps_it(self):
        self.assertEqual(self.pick(["172.31.0.9/16"], current="172.31.254.254/29"), "192.168.254.248/29")

    def test_a_current_network_that_is_not_a_candidate_is_replaced(self):
        self.assertEqual(self.pick(["10.0.0.198/24"], current="192.168.50.1/24"), "192.168.254.248/29")

    def test_no_clear_candidate_is_an_error(self):
        with self.assertRaises(ValueError):
            self.pick(["192.168.0.1/16", "172.16.0.1/12", "100.64.0.1/10"])

    def test_no_venue_address_keeps_the_current_choice_or_takes_the_first(self):
        # No venue network at all (the two-minute fallback): still usable, and stable.
        self.assertEqual(self.pick([]), "192.168.254.248/29")
        self.assertEqual(self.pick([], current="172.31.254.254/29"), "172.31.254.248/29")

    def test_addresses_within_the_network(self):
        import ipaddress
        got = mod.plan(ipaddress.ip_network("192.168.254.248/29"))
        self.assertEqual(got["jump"], "192.168.254.254/29")
        self.assertEqual(got["field_server"], "192.168.254.253")
        self.assertEqual((got["pool_first"], got["pool_last"]), ("192.168.254.249", "192.168.254.252"))
        with self.assertRaises(ValueError):
            mod.plan(ipaddress.ip_network("192.168.254.252/30"))

    def test_dhcp_settings(self):
        import ipaddress
        cfg = {"inside_interface": "eth0", "field_server_client_id": "freezy-field-server"}
        text = mod.dhcp_config(cfg, mod.plan(ipaddress.ip_network("172.31.254.248/29")))
        for line in ["port=0", "interface=eth0",
                     "dhcp-range=172.31.254.249,172.31.254.252,255.255.255.248,5m",
                     "dhcp-option=option:router,172.31.254.254",
                     "dhcp-host=id:00:66:72:65:65:7a:79:2d:66:69:65:6c:64:2d:73:65:72:76:65:72,172.31.254.253"]:
            self.assertIn(line + "\n", text)


if __name__ == "__main__":
    unittest.main()
