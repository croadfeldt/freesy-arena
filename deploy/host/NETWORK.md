# Field server network map

How the field server, its two jump virtual machines and the field switch fit together, and which
playbook builds each part. Everything here runs over one network interface on the field server, as
VLANs on the field switch.

## Why there are two jump machines

The venue's network and the field's networks can use overlapping addresses. Two small virtual machines
on the field server sit between them, each translating addresses (NAT) on the way out, so neither side
ever sees the other's addresses. They are also the only way in from the venue side: ssh to the external
machine, from there to the internal one, from there to the field server.

## The VLANs

| VLAN | What it is | Who is on it |
|---|---|---|
| 999 | Venue internet | external jump machine |
| 998 | Transit, 192.168.254.248/29: the field side's "internet" | external and internal jump machines, the UniFi gateway's WAN port |
| 100 | Admin network, 10.0.100.0/24 (FMS, switch, access point) | internal jump machine, the field server |
| 10, 20, 30, 40, 50, 60 | Team networks for red 1 to 3 and blue 1 to 3 | the field server; one team's driver station and robot each |
| UniFi management | 10.0.0.0/24, the network the UniFi switches and access points are managed on | the UniFi gateway's LAN side and the UniFi devices |

```
venue internet
     │ VLAN 999
┌────┴─────────────────┐
│ external jump machine│  NAT out to the venue; ssh in
└────┬─────────────────┘
     │ VLAN 998 (transit) ───── UniFi gateway WAN ── UniFi management, 10.0.0.0/24
┌────┴─────────────────┐
│ internal jump machine│  NAT out to transit; gateway and DNS for the admin network
└────┬─────────────────┘
     │ VLAN 100 (admin, 10.0.100.0/24)
┌────┴─────────────────┐
│ field server         │  10.0.100.5: arena, team gateways, DHCP, team VLAN filter
└────┬─────────────────┘
     │ VLANs 10 to 60, one per driver station position
   teams
```

## The UniFi management network

The UniFi switches and access points are managed on 10.0.0.0/24, behind the UniFi gateway. That
gateway's WAN port is on the transit VLAN, so the management network reaches the internet the same way
the admin network does: out through the external jump machine, which translates its address. This is
what lets the UniFi gear reach its controller and updates.

For that to work the gateway's WAN port needs a fixed address in the transit network (192.168.254.249
to .252 are free), with 192.168.254.254 as its gateway and DNS server; nothing on the transit network
hands out addresses. The external jump machine already accepts DNS on that side and passes traffic
outward.

A venue may itself use 10.0.0.0/24. That is fine: the venue only ever sees the external jump machine's
own address, which is the reason the jump machines exist.

## On the field server

The physical interface has no address. Everything sits on top of it:

| Connection | Type | Address on the field server | Used by |
|---|---|---|---|
| the interface | ethernet | none | carries all the VLANs |
| `vlan999` | VLAN 999 | none | external jump machine, card 2 |
| `vlan998` | VLAN 998 | none | external jump machine, card 1; internal jump machine, card 2 |
| `vlan100` | VLAN 100 | none | internal jump machine, card 1; parent of the macvlan |
| `cheesy_macvlan` | macvlan on `vlan100` | 10.0.100.5/24, gateway and DNS 10.0.100.1 | the arena |
| `vlan10` to `vlan60` | VLANs 10 to 60 | `10.TE.AM.4/24` while that team is on the field, otherwise none | Kea DHCP, team VLAN filter |

The jump machines attach to their VLAN interfaces directly (macvtap). The field server's address is on a
macvlan on the same `vlan100` interface as the internal jump machine's card, which is what lets the two
talk to each other inside the field server: traffic between two different interfaces of one network
card would have to leave and re-enter on the same switch port, and switches do not do that.

The field server has no address on the venue or transit VLANs, so it cannot be reached from the venue
except through the jump machines.

## Inside the jump machines

Built by `ansible/jump_vm.yaml`, run once against each machine.

| | External | Internal |
|---|---|---|
| Outside card (nearer the venue) | VLAN 999, address from the venue (DHCP) | VLAN 998, 192.168.254.253/29, default route and DNS 192.168.254.254 |
| Inside card (nearer the field) | VLAN 998, 192.168.254.254/29 | VLAN 100, 10.0.100.1/24 |
| Outside card accepts | ssh only | ssh only |
| Inside card accepts | ssh, DNS | ssh, DNS |
| Passing through | inside to outside only, address translated | inside to outside only, address translated |
| Inbound port forwards | none | none |

Neither machine serves DHCP; devices on the admin network have fixed addresses. Each machine also runs
`dnscrypt-proxy` on its inside address, which the playbook does not configure yet.

## The FRC field rules, and where each is enforced

The rules are the ones FIRST describes for its own fields (the FMS whitepaper) and the access list in
the stock Cheesy Arena switch configuration (`switch_config.txt`).

| Rule | Enforced by |
|---|---|
| A team VLAN holds only that team's robot and driver station, plus the FMS | the switch (one VLAN per station); the field server is the only other member |
| A driver station reaches the FMS only for driver station traffic: UDP 1160 and TCP 1750 to 10.0.100.5, ping, DHCP | team VLAN filter on the field server (`freezy-field.nft`) |
| The admin network is not reachable from robots and driver stations | team VLAN filter: everything else to the field server is dropped, and nothing is forwarded off a team VLAN |
| Teams cannot reach each other | team VLAN filter: no forwarding between team VLANs |
| Only the admin and UniFi management networks reach the venue's internet | team VLAN filter (teams are never forwarded), then the internal jump machine, which only passes traffic arriving on its admin card |
| Nothing from the venue reaches the field | both jump machines: ssh to the machine itself is the only thing accepted from outside, and nothing is forwarded inward |
| Between a driver station and its robot, only the published ports are open (below) | not the field server: that traffic stays inside the team's VLAN and never passes through it. On a FIRST field the field access point does this; here it is the job of the access point or radio configuration |

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

## What the field switch has to provide

The port the field server plugs into must carry VLANs 999, 998, 100 and 10 to 60, all tagged. The venue's
uplink goes into a port on VLAN 999, and the UniFi gateway's WAN port into a port on VLAN 998. The switch's own configuration is not managed from this repository.

## Which playbook builds what

Run as root on the field server, in this order (details in `README.md`):

| Step | Playbook | Builds |
|---|---|---|
| 1 | `ansible/host_network.yaml` | the address-free interface, VLANs 999, 998, 100 and 10 to 60, and the macvlan with the FMS address |
| 2 | `ansible/jump_vms.yaml` | each jump machine's two cards attached to its VLANs |
| 3 | `ansible/jump_vm.yaml`, once per jump machine | the addresses and firewall inside each jump machine |
| 4 | `ansible/host_setup.yaml` | the host network helper, the team VLAN filter and the Kea container unit |
| every match | `ansible/match_network.yaml` | team gateway addresses and DHCP scopes for the six teams on the field |

Not yet in a playbook: creating the jump machines themselves and their `dnscrypt-proxy` settings, the arena's
account and container, and turning off libvirt's `default` network (its DHCP server holds the port Kea
needs).

All names, VLAN numbers and addresses above are defaults in `ansible/vars.yaml`; a host overrides them
in `/etc/freezy-net/vars.yaml`.
