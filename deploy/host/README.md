# Host network helper

The arena runs as a rootless container, so it cannot change the field server's VLAN interfaces or DHCP
server. This directory holds the small root-owned piece that does it on the arena's behalf.

## How it works

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
| `ansible/match_network.yaml`, `ansible/vars.yaml`, `ansible/templates/` | `/usr/share/freezy-net/` |
| host overrides for `vars.yaml` (optional) | `/etc/freezy-net/vars.yaml` |

All of it lives under `/usr` and all state under `/run`, so the same layout works on an image mode
host. Enable it with `systemctl enable --now freezy-net.path`.

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

## Troubleshooting

- Switch status stuck on ERROR with "did not answer": `systemctl status freezy-net.path
  freezy-net.service`.
- What the playbook did: `journalctl -u freezy-net.service`.
- The last request and result: `cat /run/freezy-net/request/teams.json /run/freezy-net/result/status.json`.

## Tests

`python3 -m unittest deploy/host/test_freezy_net_helper.py` runs the helper against a fake playbook
runner. The arena side is covered by `network/unifiswitch_test.go`.
