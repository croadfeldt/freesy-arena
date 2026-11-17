# Field server network setup

The arena runs as a rootless container, so it cannot change the field server's VLAN interfaces or DHCP
server. This directory holds the root-owned pieces that do it on the arena's behalf, the filter that
limits what a team VLAN can reach, and the playbook that installs them.

## Setting up the field server

Run this once as root on the field server, from a checkout of this repository, and again whenever the
files here change:

    ansible-playbook -i localhost, -c local deploy/host/ansible/host_setup.yaml

It checks the host first and changes nothing if a check fails: `nmcli`, `nft`, `kea-dhcp4`,
`ansible-playbook` and `python3` must be installed, the arena's account must exist, and the FMS address
must be up. Then it:

1. installs the files listed below;
2. loads the team VLAN filter and enables it at boot;
3. creates any of the six team VLAN connections that do not exist yet, with no address. A connection
   that already exists is left as it is, after checking it is the VLAN `ansible/vars.yaml` says it is;
4. enables the request watcher (`freezy-net.path`) and Kea.

It installs no packages and does not touch the FMS address, other connections, or any other firewall on
the host. Host-specific values (field interface, VLAN connection names, the arena's account, addresses)
are all in `ansible/vars.yaml`; override them in `/etc/freezy-net/vars.yaml`.

## How the per-match step works

1. When a match is loaded, the arena writes the six team numbers to
   `/run/freezy-net/request/teams.json` (`network/unifiswitch.go`).
2. `freezy-net.path` sees the file change and starts `freezy-net.service`.
3. The service runs `freezy-net-helper` as root. It validates the request (an id plus six entries, each
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
| `kea-dhcp4-freezy.conf` | `/usr/lib/systemd/system/kea-dhcp4.service.d/freezy.conf` |
| filter variables, written by the setup | `/etc/freezy-net/freezy-field-vars.nft` |
| host overrides for `vars.yaml` (optional) | `/etc/freezy-net/vars.yaml` |

The programs and units live under `/usr`, host-specific values under `/etc`, and state under `/run`, so
the same layout works on an image mode host.

The arena's container mounts the two spool directories; see `deploy/freezy-arena.container`.

## What the per-match playbook does

`ansible/match_network.yaml` takes the six team numbers and, for each station:

- puts `10.TE.AM.4/24` on that station's VLAN connection, or removes the address if the station is empty;
- gives Kea one DHCP scope for the team (`10.TE.AM.20` to `.199`, router `.4`), using the team number as
  the subnet id so a team's leases stay valid when it moves stations.

Kea checks the new configuration before it replaces the live file, so a bad one fails the run and leaves
the previous match's DHCP serving. The playbook installs nothing, refuses to run if the FMS address is
missing, and touches no connection other than the six team VLANs. Host-specific values (VLAN connection
names, address layout) are in `ansible/vars.yaml`.

It needs `ansible-core`, `kea` and NetworkManager on the host, and the six VLAN connections to exist.

## What a team VLAN can reach

`freezy-field.nft` reproduces the `DS-FMS` access list from the stock Cisco configuration
(`switch_config.txt`). Traffic arriving on a team VLAN is allowed only if it is:

- UDP 1160 or TCP 1750 to the FMS address (driver station status and control);
- ping to the FMS network or to the team's own gateway;
- a DHCP request;
- a reply to something the field server started.

Everything else from a team VLAN is dropped: the arena's web pages on port 8080 (on the FMS address and
on the team gateway address), ssh, and any traffic to another team or the rest of the network. Other
interfaces are not filtered, so the rules sit alongside firewalld. `freezy-firewall.service` loads the
rules before the network comes up and has no stop action. `nft list table inet freezy_field` shows them
with a count of dropped packets.

## Troubleshooting

- Switch status stuck on ERROR with "did not answer": `systemctl status freezy-net.path
  freezy-net.service`.
- What the playbook did: `journalctl -u freezy-net.service`.
- The last request and result: `cat /run/freezy-net/request/teams.json /run/freezy-net/result/status.json`.

## Tests

`python3 -m unittest deploy/host/test_freezy_net_helper.py` runs the helper against a fake playbook
runner. The arena side is covered by `network/unifiswitch_test.go`.

`deploy/host/test_freezy_firewall.sh` sends real packets through the filter inside a private network
namespace (no root needed, nothing on the machine changes). It checks each path is open without the
rules, then that the allowed ones stay open and the rest are blocked with them.
