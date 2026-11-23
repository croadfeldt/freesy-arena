# The field server as an image

**Proposed.** 2026-11-23. Nothing here is built yet beyond the draft already in
this folder.

This settles how a field server is installed, updated and rebuilt as one
Fedora image mode (bootc) image, so that someone other than me can stand one up.
It covers what goes in the image, what is kept across a reinstall, how updates
and rollbacks work, and the two ways to deploy it. It ends with the decisions I
still owe and the work in order.

Today the field server is a Fedora install set up by hand-run Ansible plays
(`deploy/host/README.md`). That works, and it stays supported, but the steps
that are in no playbook (the arena's account, its linger, the jump machine's
creation) live only in `deploy/host/NETWORK.md` and in my head.

## Where this starts

`deploy/image/` already holds a draft: a `Containerfile`, `install.sh` and an
overlay under `files/`. It builds the operating system, the host pieces and
both containers into one image. Three things are wrong with it today:

- **No CI builds it.** `.github/workflows/images.yml` builds only the arena and
  Kea containers.
- **Its README is missing.** The `Containerfile` points at
  `deploy/image/README.md`.
- **Its boot-time setup fails.** `freezy-host-setup.service` runs
  `host_setup.yaml`, whose step "Let driver stations through firewalld"
  (`host_setup.yaml:170`) runs `freezy-firewalld-zones` from beside the
  playbooks. `install.sh` never installs that file. I found this by reading the
  code and have not run the image.

## Where each thing lives

Three places: **the image** (replaced whole by an update), **a server's
settings** (differ per server, survive updates), and **kept data** (survives a
reinstall).

| Thing | Today | In the image design |
|---|---|---|
| Packages: libvirt, Ansible, nftables, firewalld, tools | assumed present, checked by `host_setup.yaml` | image (`install.sh`) |
| Host network helper, its units, the team VLAN filter, the playbooks | copied by `host_setup.yaml` | image |
| Arena and Kea containers | arena pulled or built by `freezy-update`; Kea built on the host | image: both carried inside and loaded at boot, so a server needs no network at the venue |
| Arena Quadlet, Kea Quadlet | copied by hand or by `freezy-update` | image |
| firewalld ports 8080/tcp, 1750/tcp, 1160/udp | `firewall-cmd` | image |
| The `cheesy` account, its linger and subuids | by hand | image (`sysusers.d`, `tmpfiles.d`, `/etc/subuid`) |
| NIC name, VLAN ids, FMS address, team DHCP ranges, jump machines | `deploy/host/ansible/vars.yaml`, overridden by `/etc/freezy-net/vars.yaml` | a server's settings: `/etc/freezy-net/vars.yaml`, unchanged |
| Network connections (trunk, VLANs, the FMS macvlan, the transit link) | `host_network.yaml`, run by hand | made at every boot from the settings (`freezy-host-network.service`, in the draft) |
| Team addresses and Kea's config for the current match | written per match by the helper | runtime, rebuilt from the last request at boot |
| The event database, its backups, match logs, uploaded logos | the named volume `freezy-arena-data` in `cheesy`'s home | kept data |
| Kea leases, the last network request | `/var/lib/freezy-net` | kept data |
| Jump machine disks and definitions | made by hand, outside the repo | kept data, made at first boot |
| Secrets (switch, access point and admin passwords) | in the event database | kept data, with the database |

## Kept storage

An update never touches `/var`, so the database already survives updates. What
it does not survive is a reinstall. So:

- **One partition, labelled `freezy-data`, mounted at `/var/lib/freezy`.** The
  image mounts it by label when it is there. Without it the image runs the same
  way on the root disk, so a quick test install needs no special layout.
- **What moves onto it:**
  - `arena/`: the arena's `/data`. The Quadlet binds this folder where it uses
    a named volume today (`deploy/freezy-arena.container:27`).
  - `kea/`: the leases.
  - `net/`: the last network request, replayed at boot.
  - `vm/`: the jump machines' disks.
- **The install keeps it.** An installer that finds the label leaves the
  partition alone and makes it when it is missing. The standalone path does
  this in its own kickstart. The fleet manager path needs the manager to learn
  it (see "Two ways to deploy").
- **Backups leave the box.** Today the arena backs its database up only to its
  own data folder, and I download a copy by hand. A timer in the image copies
  `arena/db/backups` to a place the server's settings name (a USB disk by
  label, or an rsync target). It is off until that setting is filled in.

## The `cheesy` account

The draft gives `cheesy` uid 1001, and the uid is in three places: `sysusers.d`,
the Quadlet folder `/etc/containers/systemd/users/1001`, and the subuid files.
The fleet site I'll deploy this through already has a person at 1001.

I'll move `cheesy` to one fixed uid well away from where sites number their
people, as one build argument that fills all three places. An existing server's
data is re-owned once at cutover.

The account stays what it is today: no sudo rule, and the only thing it can ask
of root is six team numbers through the spool folder (`DESIGN.md`, "No sudo
rule for the arena user").

## Updates and rollback

- **One image carries everything**, so an update replaces the operating system,
  the host pieces, the arena and Kea together, and `bootc rollback` puts all of
  them back together.
- **A boot is good when** the arena answers on 8080, Kea is active, and the
  team VLAN filter is loaded. A boot check in the image tests those. A new
  image that fails it rolls back on its own.
- **Never during a match.** `freezy-update` already refuses while a match is in
  progress (`deploy/freezy-update`). The image keeps that rule as a hold the
  update step asks before it stages anything.
- **Updates are by hand.** Nothing updates itself at an event.
- **`freezy-update` stays** for package mode and as the way to try an arena
  build on an image-mode server without rebuilding the image. Its kept
  versions and `--rollback` are unchanged.
- **Rolling back across a database change.** The database is bbolt with JSON
  records and no migration step (`model/database.go`), so I expect an older
  arena to open a newer database and ignore fields it does not know. That is an
  expectation, not a tested fact. The work below adds a test, and until it
  passes the how-to says to take a backup before every update.

## Jump machines

A jump machine is a small virtual machine on the field server that gives a way
in from outside the field network. `deploy/host/NETWORK.md` describes the
layout.

- **The external jump machine is on by default.** It has one card on the
  venue's network and one on the transit link to the field server, takes ssh
  only, and is the way I reach a server at an event.
- **An internal jump machine is an option.** It sits between the transit link
  and the admin network and acts as that network's gateway and DNS, for a site
  whose field network has no router of its own. Off by default.
- **Both come from one list.** `freezy_jump_vms` in the server's settings is
  already a list (`deploy/host/ansible/vars.yaml:18`), with one entry today. A
  site sets it to no entries, one, or both. Each entry names its role
  (`external` or `internal`) and the VLAN interfaces its cards attach to.
- **The image creates them.** Today the machine is made by hand and only its
  inside is configured by a playbook (`deploy/jump/`, `jump_vm.yaml`). At first
  boot the image will define each listed machine and make its disk on the kept
  partition from a disk image carried in the server's image, so this too works
  with no network. A machine that already exists is left alone.
- **Keys, not passwords.** A jump machine takes the ssh keys the site put in
  its image.

## Two ways to deploy

**Standalone, from this repository.** For anyone with one server and no fleet
tooling.

1. Build: `podman build -f deploy/image/Containerfile .`, with the site's files
   (host name, ssh keys, `/etc/freezy-net/vars.yaml`) in `deploy/image/site/`.
   CI also publishes the image without site files.
2. Install: an installer ISO made from the image with `bootc-image-builder`,
   and a kickstart from this folder that makes or keeps the data partition.
3. Update: `bootc upgrade` from a registry, or `bootc switch` to an image
   carried in on a disk.

**Through the fleet manager.** For a site that already manages machines with
it. The manager builds, installs over the network, tracks which build each
server runs, and promotes builds. The site's image line uses the image this
repository publishes as its base, pinned by digest, and adds the site's
accounts and settings on top. Taking a new arena means moving that pin,
building, and promoting.

The manager cannot do this yet. It assumes every machine is a desktop laptop
and its install wipes every disk. Its decision record ADR-058 (the fleet manager
owns a device's lifecycle and assumes nothing about what a site deploys) and
the plan beside it cover that work. The standalone path does not wait for it.

## Testing

- **A throwaway virtual machine, never the live field server.** The run:
  install, bring up the network from settings, load a match and see the team
  VLANs and Kea follow, connect a driver station, update, roll back, reinstall
  and find the database still there.
- **The deployment tests go into CI.** The Python tests under `deploy/` and
  `deploy/host/test_freezy_firewall.sh` exist and run only by hand today
  (`test.yml` runs `go test` alone).
- **CI builds the image** and runs `bootc container lint`, which the
  `Containerfile` already ends with.

## Decisions I still owe

1. **The `cheesy` uid.** Which number.
2. **How a jump machine's disk gets into the image.** Carried as a disk image
   (bigger server image, no network needed), or built at first boot from a
   container (smaller, needs a registry).
3. **Where backups go by default.** A labelled USB disk is the simplest thing
   to explain in a how-to.
4. **Whether the internal jump machine's setup comes back into this
   repository.** Only the external one's is here now.

## The work, in order

1. Fix the missing `freezy-firewalld-zones` in `install.sh`, with a test that
   every file a boot-time playbook runs is installed.
2. CI: build the image, lint it, run the deployment tests.
3. One uid for `cheesy` from a build argument.
4. The data partition: the mount, the arena's data folder bound from it, Kea's
   leases and the last request moved onto it, and a one-time move for a server
   that has the old locations.
5. The boot check and the no-update-during-a-match hold.
6. Jump machines made at first boot from the list; the internal role.
7. The backup timer.
8. A test that an older arena opens a newer database.
9. The standalone installer: the kickstart and the ISO step.
10. The how-to, `deploy/image/README.md`: build, install, first boot, settings,
    update, roll back, back up, reinstall.
11. The fleet manager path, once the manager can take a server.
12. Moving the real field server over, with a backup taken first.
