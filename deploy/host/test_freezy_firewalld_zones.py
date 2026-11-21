"""Tests for freezy-firewalld-zones against a fake firewalld and NetworkManager.

    python3 -m unittest deploy/host/test_freezy_firewalld_zones.py

At the first event, firewalld's default zone on the field server dropped the driver stations' packets to
the arena while still answering their ping: the driver stations could see the FMS, the arena never saw
them, and firewalld had to be turned off. These check the script moves the team VLANs out of that zone
and opens the arena's ports, without reloading, starting or stopping firewalld.
"""
import json
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "freezy-firewalld-zones")
TEAMS = ["vlan10", "vlan20", "vlan30", "vlan40", "vlan50", "vlan60"]
ARENA_PORTS = {"8080/tcp", "1750/tcp", "1160/udp"}

# One fake for nmcli, firewall-cmd and firewall-offline-cmd, keeping its state in a JSON file and logging
# every call.
FAKE = r'''#!/usr/bin/python3
import json, os, sys
state_path = os.environ["FAKE_STATE"]
with open(state_path) as f:
    s = json.load(f)
tool, args = os.path.basename(sys.argv[0]), sys.argv[1:]
with open(state_path + ".log", "a") as f:
    f.write(json.dumps([tool] + args) + "\n")
def save():
    with open(state_path, "w") as f:
        json.dump(s, f)
def opt(name):
    for a in args:
        if a.startswith("--" + name + "="):
            return a.split("=", 1)[1]
def ports(where, zone):
    return s[where].setdefault(zone, [])
if tool == "nmcli":
    if args[:4] == ["-g", "connection.zone", "connection", "show"]:
        print(s["nm_zone"].get(args[4], ""))
    elif args[:2] == ["connection", "modify"] and args[3] == "connection.zone":
        s["nm_zone"][args[2]] = args[4]
        if s["running"]:
            s["runtime_iface"][args[2]] = args[4] or s["default"]
        save()
    else:
        sys.exit("unexpected nmcli call")
    sys.exit(0)
if tool == "firewall-cmd" and "--state" in args:
    print("running" if s["running"] else "not running")
    sys.exit(0 if s["running"] else 252)
if tool == "firewall-cmd" and not s["running"]:
    sys.exit(252)
if any(a in args for a in ("--reload", "--complete-reload", "--panic-on")):
    sys.exit("firewalld was reloaded")
if "--get-default-zone" in args:
    print(s["default"])
    sys.exit(0)
if opt("get-zone-of-interface"):
    zone = s["runtime_iface"].get(opt("get-zone-of-interface"))
    if not zone:
        print("no zone")
        sys.exit(2)
    print(zone)
    sys.exit(0)
if opt("change-interface"):
    s["runtime_iface"][opt("change-interface")] = opt("zone")
    save()
    sys.exit(0)
where = "permanent_ports" if (tool == "firewall-offline-cmd" or "--permanent" in args) else "runtime_ports"
if opt("query-port"):
    sys.exit(0 if opt("query-port") in ports(where, opt("zone")) else 1)
if opt("add-port"):
    ports(where, opt("zone")).append(opt("add-port"))
    save()
    sys.exit(0)
sys.exit("unexpected call: %s %s" % (tool, args))
'''


class FirewalldZonesTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.bin = os.path.join(self.dir.name, "bin")
        os.mkdir(self.bin)
        fake = os.path.join(self.bin, "fake")
        with open(fake, "w") as f:
            f.write(FAKE)
        os.chmod(fake, 0o755)
        self.state = os.path.join(self.dir.name, "state.json")

    def tearDown(self):
        self.dir.cleanup()

    def fake(self, running=True, installed=True, nm_zone=None, default="FedoraServer"):
        tools = ["nmcli"] + (["firewall-cmd", "firewall-offline-cmd"] if installed else [])
        for tool in tools:
            os.symlink("fake", os.path.join(self.bin, tool))
        # As on the field server: the team VLANs and the FMS macvlan ask for no zone, so they get the
        # default zone, which does not accept the driver station ports.
        with open(self.state, "w") as f:
            json.dump({"running": running, "default": default, "nm_zone": nm_zone or {},
                       "runtime_iface": {c: default for c in TEAMS + ["cheesy_macvlan"]} if running else {},
                       "permanent_ports": {}, "runtime_ports": {}}, f)

    def run_script(self):
        result = subprocess.run(["/usr/bin/bash", SCRIPT, "cheesy_macvlan"] + TEAMS, text=True,
                                capture_output=True, env={"PATH": self.bin, "FAKE_STATE": self.state})
        self.assertEqual(0, result.returncode, result.stderr)
        with open(self.state) as f:
            return result.stdout.split("\n"), json.load(f)

    def calls(self):
        if not os.path.exists(self.state + ".log"):
            return []
        with open(self.state + ".log") as f:
            return [json.loads(line) for line in f]

    def test_team_vlans_leave_the_default_zone_now_and_for_good(self):
        self.fake()
        out, s = self.run_script()
        self.assertIn("changed", out)
        for c in TEAMS:
            self.assertEqual("trusted", s["nm_zone"][c], c)
            self.assertEqual("trusted", s["runtime_iface"][c], c)
        self.assertNotIn("cheesy_macvlan", s["nm_zone"])

    def test_the_fms_zone_accepts_the_arena_ports_now_and_for_good(self):
        self.fake()
        _, s = self.run_script()
        self.assertEqual(ARENA_PORTS, set(s["permanent_ports"]["FedoraServer"]))
        self.assertEqual(ARENA_PORTS, set(s["runtime_ports"]["FedoraServer"]))

    def test_the_ports_go_in_the_zone_the_fms_connection_names(self):
        self.fake(nm_zone={"cheesy_macvlan": "internal"})
        _, s = self.run_script()
        self.assertEqual(ARENA_PORTS, set(s["permanent_ports"]["internal"]))
        self.assertNotIn("FedoraServer", s["permanent_ports"])

    def test_a_second_run_changes_nothing(self):
        self.fake()
        self.run_script()
        out, _ = self.run_script()
        self.assertNotIn("changed", out)

    def test_firewalld_that_is_off_stays_off_and_is_ready_for_when_it_starts(self):
        self.fake(running=False)
        out, s = self.run_script()
        self.assertIn("firewalld is not running; the zones apply when it starts", out)
        self.assertEqual({c: "trusted" for c in TEAMS}, s["nm_zone"])
        self.assertEqual(ARENA_PORTS, set(s["permanent_ports"]["FedoraServer"]))
        self.assertEqual({}, s["runtime_ports"])
        changes = [c for c in self.calls() if c[0] == "firewall-cmd" and c[1:] != ["--state"]]
        self.assertEqual([], changes)

    def test_never_reloads_starts_or_stops_anything(self):
        self.fake()
        self.run_script()
        for call in self.calls():
            self.assertNotIn("systemctl", call[0])
            self.assertFalse({"--reload", "--complete-reload"} & set(call), call)

    def test_nothing_to_do_without_firewalld(self):
        self.fake(installed=False)
        out, s = self.run_script()
        self.assertIn("firewalld is not installed; nothing to do", out)
        self.assertEqual({}, s["nm_zone"])


class HostSetupTest(unittest.TestCase):
    def test_host_setup_runs_the_script_for_every_team_vlan_after_loading_the_filter(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is not installed")
        with open(os.path.join(HERE, "ansible", "host_setup.yaml")) as f:
            tasks = yaml.safe_load(f)[0]["tasks"]
        names = [t["name"] for t in tasks]
        step = tasks[names.index("Let driver stations through firewalld")]
        self.assertIn("freezy-firewalld-zones {{ freezy_fms_connection }}", step["ansible.builtin.command"])
        self.assertIn("freezy_team_vlans | map(attribute='connection')", step["ansible.builtin.command"])
        self.assertLess(names.index("Check the filter is loaded"), names.index("Let driver stations through firewalld"))


if __name__ == "__main__":
    unittest.main()
