# freesy-arena — Fork Design Notes

**Status:** Living document (fork notes)
**Last updated:** 2026-11-16
**Upstream:** [`Freezy-Arena/freezy-arena`](https://github.com/Freezy-Arena/freezy-arena) (successor to `cpapplefamily/freesy-arena`; itself a fork of [Team254/cheesy-arena](https://github.com/Team254/cheesy-arena), the official Cheesy Arena FMS)
**Active branch:** `Freezy-Arena-2026` (2026 game). `Freezy-Arena-2025` remains for 2025 Reefscape rules.
**README:** retains upstream Cheesy Arena content; this document captures what *this fork* changes.

This document records the design intent of the freesy-arena fork — what it adds on top of upstream Cheesy Arena and why. Update it whenever a new fork-specific feature lands or an upstream feature is reverted/disabled.

## Why fork?

Off-season and small-venue MN FRC operations needed capabilities upstream Cheesy Arena doesn't provide out of the box — specifically:

- Small-bracket double-elimination playoffs (smaller than the official 8-team)
- Switching from FMS-managed Cisco switches to UniFi-managed switches
- Local DHCP for team networks (vs. upstream's static-IP-only assumption)
- Operational ergonomics (FTA monitor, quick-keys)

Forking with upstream's permission lets these changes ship without round-trips through Team254 review.

## Fork-specific features (on top of upstream Cheesy Arena)

### Tournament

- **3-8 team double eliminations** — upstream supports 8-team only; this fork adds 3, 4, 5, 6, 7-team double-elimination bracket generators in `playoff/`.

### Operator UX

- **FTA Monitor (Alliance)** — color-coded field-status interface for the Field Technical Advisor; auto-switches to the Game Score display during a match.
- **Quick keys** — keyboard shortcuts for common team / match control actions.

### Networking — UniFi switch path

- **`network/unifiswitch.go`** — UniFi switch driver as an alternative to upstream's Cisco-only `sccswitch.go`. Provisioned via SSH/REST against the UniFi controller.
- **`deploy/host/ansible/host_setup.yaml`** — one-time Ansible setup of the field server: installs the host helper and per-match playbook, creates the six team VLAN connections, and loads the team VLAN filter. It replaced `create_vlans.yaml`, which assumed a different interface layout, and the unused `unifi_cycle_switch_ports.yaml`.
- **`deploy/host/freezy-field.nft`** — what a team VLAN may reach on the field server: the stock `DS-FMS` access list (driver station traffic to the FMS address, ping, DHCP). The arena's web pages are not reachable from a driver station. Tested by `deploy/host/test_freezy_firewall.sh`.
- **Cisco switch architecture fully disabled** — `sccswitch.go` code paths are not exercised in fork builds; the build is UniFi-first.

### Networking — local DHCP

- **`deploy/host/ansible/match_network.yaml`** — the per-match playbook. For each station it sets `10.TE.AM.4/24` on the station's VLAN and gives Kea a DHCP scope for the team; empty stations get neither. It replaced `config_dhcp.yaml` (ISC dhcpd, end-of-life upstream) on 2026-11-17. Host-specific values live in `deploy/host/ansible/vars.yaml`.
- **`deploy/kea/Containerfile`, `deploy/host/freezy-kea.container`** — Kea runs as a root-owned container on the host's network rather than a host package, so the field server needs nothing installed beyond podman and Ansible. The per-match playbook checks each new configuration with the same image before replacing the live file.

### Operational

- **No sudo rule for the arena user.** An earlier version let the `cheesy` user run `ansible-playbook` as root without a password, which amounts to root. The host network helper replaced it; the arena can now only submit six team numbers.

## Running as a rootless container

- **`Containerfile`** builds a static binary and an image that carries `templates/`, `static/`, `schedules/` and `font/`. Everything the server writes (event database, backups, match logs, uploaded logos, team avatars) is redirected into one volume at `/data`. `static/img` lives in the volume; the entrypoint refreshes the shipped images from the image's own copy at every start, so they still update with the image.
- **`deploy/freezy-arena.container`** is a Quadlet unit that runs the image rootless under the field-server user, with host networking (the driver-station listener binds 10.0.100.5 and the server talks to the field VLANs directly).
- **`deploy/host/`** is the root-owned host network helper. A rootless container cannot change the host's VLAN interfaces or DHCP server, so the arena hands the six team numbers to this helper through a spool directory and waits for its verdict. The step cannot be skipped: no answer, or a failed playbook, shows as a switch ERROR. See `deploy/host/README.md`. Logos uploaded through the Setup menu land in `static/img` inside the container and do not survive an image rebuild.

## Branch model

- `Freezy-Arena-2026` — **current fork branch**: `Freezy-Arena/freezy-arena` `main` (2026 game) with the fork-specific commits replayed on top. Created 2026-11-16; needs a field-server test of the UniFi/DHCP path before it replaces `Freezy-Arena-2025` at events.
- `Freezy-Arena-2025` — the 2025 Reefscape branch, built on the old `cpapplefamily/freesy-arena` history. Kept for events still running 2025 rules and as the rollback.
- `main` — an older, parallel attempt at the UniFi/DHCP work. Superseded by the branches above; left as-is.
- `Works` — historical "known-good" branch used during early fork stabilization.

### Taking upstream updates

`Freezy-Arena/freezy-arena` was rebuilt on Team254's `cheesy-arena`, so it only shares history with the old `cpapplefamily` lineage up to May 2025. Merging it into `Freezy-Arena-2025` produces 59 conflicts. The fork-specific work is small (the commits after upstream's tip on this branch), so the update method is: branch from upstream `main` and cherry-pick those commits. The Go touch points are three places in `field/arena.go` and one in `field/arena_notifiers.go`.

## Design choices

- **Fork rather than upstream PR.** UniFi support and local DHCP are MN-specific operational needs; upstream serves the larger FRC community where Cisco + static IPs is the convention. Keeping these in a fork avoids putting upstream maintainers on the hook for hardware they don't have.
- **Ansible for network provisioning, not Go.** Switch and DHCP configuration is delegated to Ansible playbooks, run by the root-owned host helper when the arena asks. Easier to debug at-event (run the playbook by hand) and easier for the next operator to extend without recompiling.
- **Keep upstream README authoritative for setup/operation.** Operators read the upstream README to install and use Cheesy Arena, and refer here only to understand what's different in this fork.

## Known limitations / future work

- **Switch type is hard-coded.** `field/arena.go` calls the UniFi path unconditionally. A setting to choose Cisco or UniFi is planned for the next round of changes.
- **No CI for fork-specific code paths.** Upstream test suite runs; UniFi driver and Ansible playbooks have no automated coverage. Adding `network/unifiswitch_test.go` parity with `sccswitch_test.go` is the obvious next step.
- **Documentation gap** — the fork-specific features above are not surfaced in the upstream-derived README. End users find them by reading the bracket-size dropdown or the FTA monitor UI directly. A `docs/fork-features.md` walkthrough with screenshots would help operators new to the fork.
- **Upstream merge cadence** — currently periodic (`Merge pull request #1/#2 from joshzcold/master`-style flow). Decide whether to track every upstream release or only ones that affect game rules / scoring.
- **3-team and 5-team / 7-team brackets** — verify the bracket-generation correctness with a structured test rather than the spot-check used during initial dev.
- **UniFi controller credential handling** — currently in Ansible vars. Migrate to a secrets store (ansible-vault or HashiCorp Vault) before the fork is used at events beyond MN off-season.
- **Cisco switch code** — disabled but still present. Decide whether to remove it entirely (smaller surface, cleaner reads) or keep it for future option-value (Cisco hardware comes back).
