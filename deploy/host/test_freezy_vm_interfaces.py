"""Tests for freezy-vm-interfaces. Run: python3 -m unittest deploy/host/test_freezy_vm_interfaces.py"""
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "freezy-vm-interfaces")
loader = importlib.machinery.SourceFileLoader("freezy_vm_interfaces", SCRIPT)
spec = importlib.util.spec_from_loader("freezy_vm_interfaces", loader)
mod = importlib.util.module_from_spec(spec)
sys.dont_write_bytecode = True
loader.exec_module(mod)

# The shape found on the field server: both cards attached straight to physical interfaces.
DOMAIN = """<domain type='kvm'>
  <name>jump</name>
  <devices>
    <disk type='file' device='disk'><source file='/var/lib/libvirt/images/jump.qcow2'/></disk>
    <interface type='direct'>
      <mac address='52:54:00:00:00:01'/>
      <source dev='enp1s0' mode='bridge'/>
      <target dev='macvtap0'/>
      <model type='virtio'/>
    </interface>
    <interface type='bridge'>
      <mac address='52:54:00:00:00:02'/>
      <source bridge='br0'/>
      <virtualport type='openvswitch'/>
      <model type='virtio'/>
    </interface>
  </devices>
</domain>"""


def cards(xml_text):
    out = []
    for card in ET.fromstring(xml_text).findall("./devices/interface"):
        out.append((card.get("type"), dict(card.find("source").attrib), card.find("mac").get("address"),
                    card.find("model").get("type"), card.find("target"), card.find("virtualport")))
    return out


class RewriteTest(unittest.TestCase):
    def test_cards_move_to_the_vlan_interfaces_and_keep_their_identity(self):
        new_xml, changed = mod.rewrite(DOMAIN, ["vlan998", "vlan999"])
        self.assertTrue(changed)
        self.assertEqual(cards(new_xml), [
            ("direct", {"dev": "vlan998", "mode": "bridge"}, "52:54:00:00:00:01", "virtio", None, None),
            ("direct", {"dev": "vlan999", "mode": "bridge"}, "52:54:00:00:00:02", "virtio", None, None),
        ])
        # Nothing else in the machine is touched.
        self.assertIn("/var/lib/libvirt/images/jump.qcow2", new_xml)

    def test_a_machine_that_already_matches_is_left_alone(self):
        new_xml, _ = mod.rewrite(DOMAIN, ["vlan998", "vlan999"])
        again, changed = mod.rewrite(new_xml, ["vlan998", "vlan999"])
        self.assertFalse(changed)

    def test_wrong_number_of_cards_is_refused(self):
        with self.assertRaises(ValueError):
            mod.rewrite(DOMAIN, ["vlan998"])

    def test_command_exit_codes(self):
        def run(args, text):
            return subprocess.run([sys.executable, SCRIPT] + args, input=text, capture_output=True, text=True)
        first = run(["vlan998", "vlan999"], DOMAIN)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(run(["vlan998", "vlan999"], first.stdout).returncode, 3)
        self.assertEqual(run(["vlan998"], DOMAIN).returncode, 2)
        self.assertEqual(run(["vlan998", "vlan999"], "not xml").returncode, 2)


if __name__ == "__main__":
    unittest.main()
