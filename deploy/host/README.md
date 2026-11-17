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
| the per-match playbook | `/usr/share/freezy-net/match_network.yaml` |

All of it lives under `/usr` and all state under `/run`, so the same layout works on an image mode
host. Enable it with `systemctl enable --now freezy-net.path`.

The arena's container mounts the two spool directories; see `deploy/freezy-arena.container`.

## Troubleshooting

- Switch status stuck on ERROR with "did not answer": `systemctl status freezy-net.path
  freezy-net.service`.
- What the playbook did: `journalctl -u freezy-net.service`.
- The last request and result: `cat /run/freezy-net/request/teams.json /run/freezy-net/result/status.json`.

## Tests

`python3 -m unittest deploy/host/test_freezy_net_helper.py` runs the helper against a fake playbook
runner. The arena side is covered by `network/unifiswitch_test.go`.
