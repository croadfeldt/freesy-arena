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
| 998 | Transit: the link between the two jump machines | external and internal jump machines |
| 100 | Admin network, 10.0.100.0/24 (FMS, switch, access point) | internal jump machine, the field server |
| 10, 20, 30, 40, 50, 60 | Team networks for red 1 to 3 and blue 1 to 3 | the field server; one team's driver station and robot each |

```
venue internet
     │ VLAN 999
┌────┴─────────────────┐
│ external jump machine│  NAT out to the venue; ssh in
└────┬─────────────────┘
     │ VLAN 998 (transit)
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

These settings live inside the virtual machines and are not yet built by a playbook.

| | External | Internal |
|---|---|---|
| Card 1 | VLAN 998, 192.168.254.254/29 | VLAN 100, 10.0.100.1/24 |
| Card 2 | VLAN 999, address from the venue (DHCP) | VLAN 998, 192.168.254.253/29, default route to .254 |
| Firewall zones | card 2 `external` (NAT, ssh only); card 1 `internal` | card 2 `external` (NAT, ssh only); card 1 `internal` |
| Forwarding | on | on |
| DNS | `dnscrypt-proxy` on the transit address | `dnscrypt-proxy` on the admin and transit addresses |
| Inbound port forwards | none | none |

Neither machine serves DHCP. Devices on the admin network have fixed addresses.

## What the field switch has to provide

The port the field server plugs into must carry VLANs 999, 998, 100 and 10 to 60, all tagged. The venue's
uplink goes into a port on VLAN 999. The switch's own configuration is not managed from this repository.

## Which playbook builds what

Run as root on the field server, in this order (details in `README.md`):

| Step | Playbook | Builds |
|---|---|---|
| 1 | `ansible/host_network.yaml` | the address-free interface, VLANs 999, 998, 100 and 10 to 60, and the macvlan with the FMS address |
| 2 | `ansible/jump_vms.yaml` | each jump machine's two cards attached to its VLANs |
| 3 | `ansible/host_setup.yaml` | the host network helper, the team VLAN filter and the Kea container unit |
| every match | `ansible/match_network.yaml` | team gateway addresses and DHCP scopes for the six teams on the field |

Not yet in a playbook: creating the jump machines themselves and the settings inside them, the arena's
account and container, and turning off libvirt's `default` network (its DHCP server holds the port Kea
needs).

All names, VLAN numbers and addresses above are defaults in `ansible/vars.yaml`; a host overrides them
in `/etc/freezy-net/vars.yaml`.
