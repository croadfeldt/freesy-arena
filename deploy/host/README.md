# Field server network setup

The arena runs as a rootless container, so it cannot change the field server's VLAN interfaces or DHCP
server. This directory holds the root-owned pieces that do it on the arena's behalf, the filter that
limits what a team VLAN can reach, and the playbook that installs them.

## Setting up the field server

Run these as root on the field server, from a checkout of this repository, and again whenever the files
here change:

    ansible-playbook -i localhost, -c local deploy/host/ansible/host_network.yaml
    ansible-playbook -i localhost, -c local deploy/host/ansible/jump_vms.yaml
    podman build -t localhost/freezy-kea:latest deploy/kea
    ansible-playbook -i localhost, -c local deploy/host/ansible/host_setup.yaml

### The network interfaces (`host_network.yaml`)

`NETWORK.md` has the full map. The field server uses one network interface (`freezy_field_interface`
in `ansible/vars.yaml`), which gets no address of its own. On top of it the playbook puts the venue,
transit and admin VLANs (999, 998, 100) with no address, a macvlan on the admin VLAN carrying the FMS
address, an ssh-only address on the transit VLAN (the way in from the jump machine), and the six team
VLANs with no address until a match assigns one.

The playbook creates whatever is missing, so it builds this from a fresh install. What already exists
is checked and never rebuilt: if the macvlan or a VLAN is not what `vars.yaml` describes, the playbook
stops and says so, because rebuilding the connection that carries the FMS address would cut off the
arena and anyone logged in. The one live change it makes is removing addresses from the interface
itself, which leaves the macvlan and the VLANs up.

### The jump virtual machine (`jump_vms.yaml`, `jump_vm.yaml`)

`jump_vms.yaml` runs on the field server and points the jump machine's two network cards at the
transit and venue VLAN interfaces. Set the machine's name in `/etc/freezy-net/vars.yaml`
(`freezy_jump_vms`). The cards keep their MAC addresses. Only the saved definition changes; a running
machine picks it up the next time it is shut down and started, and the playbook says if it is still
waiting for that.

`jump_vm.yaml` runs against the jump machine itself:

    ansible-playbook -i <machine>, -u root deploy/host/ansible/jump_vm.yaml

It sets the machine's firewall: the venue side accepts only ssh and translates the address of
everything leaving through it, the transit side accepts ssh, DNS and DHCP, and nothing is forwarded
inward. It also installs `deploy/jump/freezy-transit-select`, which picks a transit network that does
not overlap the venue's and serves it by DHCP, falling back to a default after two minutes with no
venue network (`NETWORK.md` explains the choice). It needs `dnsmasq` on the machine. A setting that is already right is not touched, so it is safe to run over the
connection it uses. It stops if a zone carries ports, port forwards or rich rules it does not manage,
so a hand-made exception is noticed and not silently removed.

### The helper, the filter and Kea (`host_setup.yaml`)

Kea runs as a container, so the first command builds its image; nothing is installed on the host. The
playbook checks the host first and changes nothing if a check fails: `nmcli`, `nft`, `podman`,
`ansible-playbook` and `python3` must be installed, the Kea image must be built, the arena's account
must exist, the FMS address must be up, and the six team VLAN connections must exist. Then it:

1. installs the files listed below;
2. loads the team VLAN filter and enables it at boot;
3. enables the request watcher (`freezy-net.path`) and installs the Kea container unit.

It installs no packages and does not touch the FMS address, other connections, or any other firewall on
the host. Host-specific values (field interface, VLAN connection names, the arena's account, addresses)
are all in `ansible/vars.yaml`; override them in `/etc/freezy-net/vars.yaml`.

## How the per-match step works

1. When a match is loaded, the arena writes the six team numbers to
   `/run/freezy-net/request/teams.json` (`network/unifiswitch.go`).
2. `freezy-net.path` sees the file change and starts `freezy-net.service`.
3. The service loads the team VLAN filter again, then runs `freezy-net-helper` as root. It validates the request (an id plus six entries, each
   blank or a 1 to 5 digit team number) and runs the per-match playbook with those numbers.
4. The helper writes its verdict to `/run/freezy-net/result/status.json`.
5. The arena waits up to two minutes for a result carrying the same id. The switch status on the match
   play page shows CONFIGURING, then ACTIVE or ERROR. There is no way to skip this step.

The container's only privilege is submitting six team numbers. The request directory belongs to the
arena's user and is treated as untrusted; the result directory and everything the helper runs belong to
root.

## Files and where they install

| File | Installs to |
|---|---|
| `freezy-net-helper` | `/usr/libexec/freezy-net-helper` |
| `freezy-net.path`, `freezy-net.service` | `/usr/lib/systemd/system/` |
| `freezy-net.tmpfiles.conf` | `/usr/lib/tmpfiles.d/freezy-net.conf` |
| `ansible/match_network.yaml`, `ansible/vars.yaml`, `ansible/templates/kea-dhcp4.conf.j2` | `/usr/share/freezy-net/` |
| `freezy-field.nft` | `/usr/share/freezy-net/freezy-field.nft` |
| `freezy-firewall.service` | `/usr/lib/systemd/system/` |
| `freezy-kea.container` | `/usr/share/containers/systemd/freezy-kea.container` |
| Kea configuration, written per match | `/etc/freezy-net/kea/kea-dhcp4.conf` |
| Kea leases | `/var/lib/freezy-net/kea/` |
| filter variables, written by the setup | `/etc/freezy-net/freezy-field-vars.nft` |
| host overrides for `vars.yaml` (optional) | `/etc/freezy-net/vars.yaml` |

The programs and units live under `/usr`, host-specific values under `/etc`, and state under `/run` and
`/var`, so
the same layout works on an image mode host.

The arena's container mounts the two spool directories; see `deploy/freezy-arena.container`.

## What the per-match playbook does

`ansible/match_network.yaml` takes the six team numbers and, for each station:

- puts `10.TE.AM.4/24` on that station's VLAN connection, or removes the address if the station is empty;
- gives Kea one DHCP scope for the team (`10.TE.AM.20` to `.199`, router `.4`), using the team number as
  the subnet id so a team's leases stay valid when it moves stations.

Kea runs as a root-owned container on the host's network (`freezy-kea.service`, generated from
`freezy-kea.container`), because it answers driver stations directly on the team VLAN interfaces. The
playbook has Kea, from the same image, check the new configuration before it replaces the live file, so
a bad one fails the run and leaves the previous match's DHCP serving. The service first starts when the
arena loads a match, and comes back with the last match's configuration after a reboot. The playbook installs nothing, refuses to run if the FMS address is
missing, and touches no connection other than the six team VLANs. Host-specific values (VLAN connection
names, address layout) are in `ansible/vars.yaml`.

It needs `ansible-core`, `podman` and NetworkManager on the host, the Kea image, and the six VLAN
connections to exist.

## What a team VLAN can reach

`freezy-field.nft` reproduces the `DS-FMS` access list from the stock Cisco configuration
(`switch_config.txt`). Traffic arriving on a team VLAN is allowed only if it is:

- UDP 1160 or TCP 1750 to the FMS address (driver station status and control);
- ping to the FMS network or to the team's own gateway (another team's gateway does not answer);
- a DHCP request, broadcast or to the team's own gateway;
- a reply to something the field server started.

The same file guards the field server's transit address: ssh and ping to that address only, and
nothing forwarded to or from the transit network.

Everything else from a team VLAN is dropped: the arena's web pages on port 8080 (on the FMS address and
on the team gateway address), ssh, and any traffic to another team or the rest of the network. Other
interfaces are not filtered, so the rules sit alongside firewalld. `freezy-firewall.service` loads the
rules before the network comes up and has no stop action. `nft list table inet freezy_field` shows them
with a count of dropped packets.

## Troubleshooting

- Switch status stuck on ERROR with "did not answer": `systemctl status freezy-net.path
  freezy-net.service`.
- What the playbook did: `journalctl -u freezy-net.service`.
- DHCP: `systemctl status freezy-kea.service`, `journalctl -u freezy-kea.service`.
- The last request and result: `cat /run/freezy-net/request/teams.json /run/freezy-net/result/status.json`.

## Tests

`python3 -m unittest deploy/host/test_freezy_net_helper.py` runs the helper against a fake playbook
runner, `python3 -m unittest deploy/jump/test_freezy_transit_select.py` covers the choice of transit
network, and `python3 -m unittest deploy/host/test_freezy_vm_interfaces.py` covers the rewrite of a jump
machine's network cards. The arena side is covered by `network/unifiswitch_test.go`.

`deploy/host/test_freezy_firewall.sh` sends real packets through the filter inside a private network
namespace (no root needed, nothing on the machine changes). It checks each path is open without the
rules, then that the allowed ones stay open and the rest are blocked with them.
