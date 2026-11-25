# Field network map

How the venue, the jump virtual machine, the UniFi gear and the field server fit together, which rules
apply where, and which playbook builds each part. The field server uses one network interface; everything
runs over it as VLANs on the UniFi switches.

## The idea

- **The UniFi configuration never changes during an event.** The team VLANs are plain VLANs on the
  switches, with no addresses or DHCP on the UniFi side. The field server is the gateway and DHCP server
  for whichever six teams are on the field, and it is the only thing reconfigured per match.
- **One jump virtual machine separates the venue from the field.** A venue's network can use the same
  addresses as the field's (the UniFi management network is 10.0.0.0/24, and so are plenty of venues).
  The jump machine translates addresses on the way out, so the UniFi gateway's WAN side only ever sees
  the small transit network, never the venue.
- **Everything else sits behind the UniFi gateway**, which routes the admin and management networks.

## The networks

| VLAN | Network | What it is | Routed by |
|---|---|---|---|
| 999 | from the venue (DHCP) | venue internet | the venue |
| 998 | 192.168.254.248/29 unless the venue uses it | transit: the field side's "internet", served by DHCP | jump machine (last address) |
| 100 | 10.0.100.0/24 | admin: FMS, field equipment | UniFi gateway (10.0.100.1) |
| UniFi management | 10.0.0.0/24 | UniFi switches and access points | UniFi gateway |
| 10, 20, 30, 40, 50, 60 | `10.TE.AM.0/24` per match | red 1 to 3, blue 1 to 3: one team's driver station and robot | field server (`10.TE.AM.4`); VLAN-only on UniFi |

```
venue internet
     │ VLAN 999
┌────┴───────────┐
│ jump machine   │ NAT out, ssh in · DHCP and DNS for the transit network
└────┬───────────┘
     │ VLAN 998 (transit) ──────────────── field server (ssh only)
┌────┴───────────┐
│ UniFi gateway  │ WAN on transit · routes admin and management · NAT out
└────┬───────────┘
     ├── UniFi management, 10.0.0.0/24 ── switches, access points
     └── VLAN 100 (admin), 10.0.100.0/24
              │
        ┌─────┴────────┐
        │ field server │ 10.0.100.5: arena · team gateways, DHCP and filter
        └─────┬────────┘
              │ VLANs 10 to 60 (plain VLANs on the switches)
            teams
```

## On the field server

The physical interface has no address. Everything sits on top of it:

| Connection | Type | Address | Used for |
|---|---|---|---|
| the interface | ethernet | none | carries all the VLANs |
| `vlan999` | VLAN 999 | none | jump machine, card 2 |
| `vlan998` | VLAN 998 | none | jump machine, card 1; parent of `cheesy_transit` |
| `cheesy_transit` | macvlan on `vlan998` | by DHCP from the jump machine, always the address just below the jump machine's; no default route | the way in: ssh from the jump machine |
| `vlan100` | VLAN 100 | none | parent of `cheesy_macvlan` |
| `cheesy_macvlan` | macvlan on `vlan100` | 10.0.100.5/24, gateway and DNS 10.0.100.1 | the arena |
| `vlan10` to `vlan60` | VLANs 10 to 60 | `10.TE.AM.4/24` while that team is on the field, otherwise none | team gateway, Kea DHCP |

Getting in from the venue is two hops: ssh to the jump machine, then ssh to the field server's transit
address (192.168.254.253 unless the transit network had to move). That path
does not pass through the UniFi gateway, so the field server stays reachable when the UniFi side is
down or misconfigured. The transit address accepts ssh and ping only, and the field server never passes
traffic between the transit network and anything else.

## Inside the jump machine

Built by `ansible/jump_vm.yaml`.

| | |
|---|---|
| Outside card, VLAN 999 | address from the venue (DHCP); accepts ssh only |
| Inside card, VLAN 998 | the last address of the transit network; accepts ssh, DNS and DHCP; hands out addresses by DHCP |
| Passing through | inside to outside only, address translated; nothing forwarded inward, no port forwards |

It also runs `dnscrypt-proxy` on its inside address, which the playbook does not configure yet.

### The internal role

The same playbook, with `freezy_jump_role: internal`, sets a second machine up in the place of the
UniFi gateway, for a field with no router of its own.

| | |
|---|---|
| Outside card, transit VLAN | address by DHCP from the external jump machine; accepts ssh only |
| Inside card, admin VLAN | the admin network's gateway address (`freezy_fms_gateway`); accepts ssh, DNS and DHCP; answers DNS and hands out `freezy_admin_dhcp_first` to `freezy_admin_dhcp_last` |
| Passing through | inside to outside only, address translated; nothing forwarded inward |

Whenever its inside card does not hold the gateway address, `freezy-admin-router` asks the admin network
whether something already answers there. If something does, it takes no address and fails, so it
never runs beside a router that holds the same address.

`deploy/jump/Containerfile` builds one image that serves both roles, and `deploy/jump/build-disk`
turns it into a disk image. A machine started from that disk is told its role by the field server
and runs the playbook on itself at every boot.

### Which jump machines run

On a field server installed from the image (`deploy/image/`), two settings decide, and
`freezy-jump` changes them. Each is kept in `/etc/freezy-net/vars.yaml`, survives updates, and can be
changed at any time, also during an event.

| Setting | Values | What it does |
|---|---|---|
| `freezy_venue_isolation` | `true` (default), `false` | `true` runs the external machine, between the venue's VLAN and the transit VLAN. It keeps the venue's subnets apart from the field's and is the way in |
| `freezy_admin_router` | `internal` (default), `gateway`, `none` | who is gateway and DNS for the admin network |

| Venue isolation | Admin router | Machines running | Gateway and DNS for the admin network |
|---|---|---|---|
| on | `internal` | external, internal | the internal machine. **The default.** It needs only switches that carry tagged VLANs, of any brand |
| on | `gateway` | external | a hardware router with its WAN port on the transit VLAN (the layout at the top of this page) |
| off | `internal` | internal | the internal machine. The field has no way out and nothing is reachable from the venue |
| off | `gateway` | none | the hardware router |
| off | `none` | none | nothing on the field server; a router in bridge mode |
| on | `none` | external | nothing. Allowed, with a warning: the admin network has no way out, and the way in still works |

```
freezy-jump status                           # the settings, each machine, its addresses, its setup
freezy-jump venue-isolation on|off
freezy-jump admin-router internal|gateway|none
freezy-jump log external|internal            # what a machine logged while setting itself up
freezy-jump restart                          # restart the machines that should run
```

- **Turning a machine on** copies the disk the image carries to `/var/lib/freezy/vm` if the machine
  has none, defines it, and starts it. Its cards attach to the VLAN interfaces named `venue`,
  `transit` and `admin` in `freezy_uplink_vlans`, whatever their VLAN numbers are.
- **Turning it off** shuts it down and removes its definition. Its disk stays.
- **The same step runs at every boot** (`freezy-jump.service`), so the machines always match the
  settings.
- **ssh keys** for both machines come from `/etc/freezy-net/jump_authorized_keys`, or from root's
  own `authorized_keys` when that file is missing. There are no passwords.
- **A machine sets itself up when it starts, and says how it went.** `status` shows each card's
  address (the external machine's venue address is the one to ssh to) and whether its setup
  finished. When it failed, `log` shows why, read from the machine's serial console, which the field
  server logs in `/var/log/libvirt/qemu/`. `restart` has it try again.
- **Team VLANs are not part of this.** The field server is their gateway and DHCP server in every
  row of the table.

Changing `freezy_admin_router` away from a hardware router, or to one, moves the gateway address
between two devices. Unplug or reconfigure the router first: the internal machine refuses to take an
address that something already answers on. `status` then shows its setup failed; once the router is
out of the way, `freezy-jump restart`.

### How the transit network is chosen

The transit network must not overlap the venue's, or the jump machine could not tell them apart.
`freezy-transit-select` on the jump machine decides:

1. It looks at every network the venue side uses: the address the venue handed out and any routes that
   came with it.
2. It takes the first of three candidates that overlaps none of them: 192.168.254.248/29, then
   172.31.254.248/29, then 100.64.254.248/29. They are in three different private ranges, so one is
   always clear.
3. It keeps the current choice for as long as it is clear, so the field side is not reshuffled at
   every lease renewal or every new venue.
4. If the venue hands out no address within two minutes of boot, it settles anyway, on the current
   choice or the first candidate. The field then runs with no venue network at all, and if a venue
   network turns up later and collides, the transit network moves then.

Within the chosen network the jump machine takes the last address, the field server always gets the one
below it (recognised by the client id it sends), and the rest are handed out, which is how the UniFi
gateway gets its WAN address. Leases are five minutes, so if the network ever has to move the gateway
follows within minutes.

## On the UniFi side

Not managed from this repository. It is set once and left alone:

- **Gateway WAN**: a port on VLAN 998, set to DHCP. The jump machine gives it an address, gateway and
  DNS server.
- **Admin network**: VLAN 100, 10.0.100.0/24, gateway 10.0.100.1, no DHCP range that includes
  10.0.100.5.
- **Team VLANs 10 to 60**: VLAN-only networks. No gateway address, no DHCP, no DHCP guarding that would
  block the field server's answers, no routes to team networks. If the gateway routed them, teams would
  have a way out that bypasses the field server's filter.
- **Field server port**: VLANs 999, 998, 100 and 10 to 60, all tagged. Venue uplink on a VLAN 999 port.
- **Firewall rules on the gateway**: the WAN side keeps the default (nothing inbound). Between its own
  networks the only rule the field needs is that the management network is not reachable from the admin
  network except by whoever administers the UniFi gear. Team traffic never reaches the gateway, so it
  needs no team rules.
- **Driver station to robot ports**: see below. This is the one field rule that has to live on the
  UniFi or radio side.

## The FRC field rules, and where each is enforced

The rules are the ones FIRST describes for its own fields (the FMS whitepaper) and the access list in
the stock Cheesy Arena switch configuration (`switch_config.txt`).

| Rule | Enforced by |
|---|---|
| A team VLAN holds only that team's robot and driver station, plus the FMS | the switches (one VLAN per station); the field server is the only other member |
| A driver station reaches the FMS only for driver station traffic: UDP 1160 and TCP 1750 to 10.0.100.5, ping, DHCP | team VLAN filter on the field server (`freezy-field.nft`) |
| The admin network is not reachable from robots and driver stations | team VLAN filter: everything else to the field server is dropped, and nothing but ping to the admin network is forwarded off a team VLAN |
| Teams cannot reach each other | team VLAN filter: no forwarding between team VLANs, and a team's gateway address answers only its own VLAN |
| Only the admin and UniFi management networks reach the venue's internet | team VLAN filter (teams are never forwarded); the UniFi gateway routes only its own networks |
| Nothing from the venue reaches the field | jump machine: ssh to the machine itself is all it accepts from outside, nothing is forwarded inward; then the UniFi gateway's WAN firewall |
| The way in cannot be used as a way around | team VLAN filter: the transit address answers ssh and ping only, and nothing is forwarded to or from the transit network |
| Between a driver station and its robot, only the published ports are open (below) | not the field server: that traffic stays inside the team's VLAN. On a FIRST field the field access point does this; here it is the access point or radio configuration |

Ports open between a driver station and its robot, all both ways, everything else blocked. This is
the list in the FMS whitepaper; the season's game manual has the authoritative one.

| Port | Protocol | Use |
|---|---|---|
| 1180 to 1190 | UDP and TCP | camera data |
| 1735 | TCP | SmartDashboard |
| 1130 | UDP | driver station to robot control |
| 1140 | UDP | robot to driver station status |
| 80, 443 | TCP | camera and web interfaces |
| 554 | UDP and TCP | camera streaming (RTSP) |
| 1250 | UDP and TCP | CTRE diagnostics |
| 5800 to 5810 | UDP and TCP | team use |

## Which playbook builds what

| Step | Playbook | Where it runs | Builds |
|---|---|---|---|
| 1 | `ansible/host_network.yaml` | field server | the address-free interface, VLANs 999, 998, 100 and 10 to 60, the FMS macvlan and the transit address |
| 2 | `ansible/jump_vms.yaml` | field server | the jump machine's two cards attached to VLANs 998 and 999 |
| 3 | `ansible/jump_vm.yaml` | against the jump machine | its firewall, the transit network chooser and the transit DHCP server |
| 4 | `ansible/host_setup.yaml` | field server | the host network helper, the team VLAN filter and the Kea container unit |
| every match | `ansible/match_network.yaml` | field server, started by the arena | team gateway addresses and DHCP scopes for the six teams on the field |

Not yet in a playbook: creating the jump machine itself and its `dnscrypt-proxy` settings, the arena's
account and container, and turning off libvirt's `default` network (its DHCP server holds the port Kea
needs).

All names, VLAN numbers and addresses above are defaults in `ansible/vars.yaml`; a host overrides them
in `/etc/freezy-net/vars.yaml`.
