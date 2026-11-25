# The field server as an image

**Accepted.** 2026-11-24. Built so far: the draft already in this folder and
the two fixes named below.

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
both containers into one image. I built it and booted it in a throwaway virtual
machine. It did not come up to a working arena, for two reasons, and two more
things are missing:

- **Its boot-time setup failed.** `freezy-host-setup.service` runs
  `host_setup.yaml`, whose step "Let driver stations through firewalld" runs
  `freezy-firewalld-zones` from beside the playbooks. `install.sh` never
  installed that file.
- **The arena never started on a fresh install.** Its container takes the
  host's time zone, and podman will not start it without `/etc/localtime`,
  which `bootc install` does not make.
- **No CI builds it.** `.github/workflows/images.yml` builds only the arena and
  Kea containers.
- **Its README is missing.** The `Containerfile` points at
  `deploy/image/README.md`.

The first two are fixed ("Make the field-server image boot to a working
arena"). With those fixes, an image installed to an empty disk answers
on 8080 about 30 seconds after power-on.

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
| Jump machine disks and definitions | made by hand, outside the repo | kept data, copied from the image when a machine is first turned on |
| Secrets (switch, access point and admin passwords) | in the event database | kept data, with the database |

## Kept storage

An update never touches `/var`, so the database already survives updates. What
it does not survive is a reinstall. So:

- **One partition, labelled `freezy-data`, mounted at `/var/lib/freezy`.** A
  step at every boot (`freezy-data`) mounts it by label when it is there.
  Without it the image runs the same way on the root disk, so a quick test
  install needs no special layout.
- **What is on it:**
  - `arena/`: the arena's `/data`. In the image the Quadlet binds this folder;
    outside the image it stays the named volume `freezy-arena-data`.
  - `kea/`: the leases.
  - `net/`: the last network request, replayed at boot.
  - `vm/`: the jump machines' disks.
- **Data in an older place is moved in once**, and only into a folder that is
  still empty, so nothing on the partition is ever overwritten:
  - from the root disk under `/var/lib/freezy`, when a partition is added to a
    server that ran without one;
  - from `/var/lib/freezy-net` and the named volume, where the image kept
    things before this.
- **The arena waits for that step.** If the partition cannot be mounted the
  arena does not start, so an operator sees no arena and never an empty event.
- **The install keeps it.** An installer that finds the label leaves the
  partition alone and makes it when it is missing. The standalone path does
  this in its own kickstart. The fleet manager path needs the manager to learn
  it (see "Two ways to deploy").
- **Backups of the event database leave the box.** The arena writes a copy of
  its database to `arena/db/backups` after every committed match, on the same
  disk as the database, so a dead disk loses the event. `freezy-backup` copies
  that folder to the place `freezy_backup_target` in the server's settings
  names, every five minutes (`freezy-backup.timer`):
  - **Empty, the default:** nothing is copied.
  - **`label:NAME`:** a disk whose filesystem has that label, a USB stick for
    one. It is mounted for the copy and unmounted after, so it can be pulled
    at any other moment. Owners and modes are not copied, so a FAT stick takes
    it.
  - **Anything else:** an rsync destination.
- **Nothing is deleted at the target**, so clearing or restoring the database
  on the server leaves the copies.
- **A copy that did not happen is a failed unit.** With a target set and the
  disk gone, `freezy-backup.service` shows in `systemctl --failed`.
  `freezy-backup --status` says when the last copy succeeded and whether the
  newest backup has left the server.
- **It copies during a match.** A backup is a few megabytes and the copy runs
  at idle priority. The update hold does not apply to it.

## The `cheesy` account

The draft gives `cheesy` uid 1001, and the uid is in three places: `sysusers.d`,
the Quadlet folder `/etc/containers/systemd/users/1001`, and the subuid files.
The fleet site I'll deploy this through already has a person at 1001.

`cheesy` moves to one fixed uid, 880, set by one build argument that fills all
three places. 880 is free in the base image, sits below the range systemd hands
out on its own (it counts down from 999) and is well away from where sites
number their people. The build fails if the base already uses it. The number
stays fixed, not picked at boot, because the kept partition holds files it
owns. An existing server's data is re-owned once at cutover.

The account stays what it is today: no sudo rule, and the only thing it can ask
of root is six team numbers through the spool folder (`DESIGN.md`, "No sudo
rule for the arena user").

## Updates and rollback

- **One image carries everything**, so an update replaces the operating system,
  the host pieces, the arena and Kea together, and `bootc rollback` puts all of
  them back together.
- **A boot is good when** the boot's own steps finished (kept data, network
  interfaces, host setup), the team VLAN filter is loaded, the arena answers on
  8080, and Kea runs once a match has ever been loaded. greenboot runs that
  check at every boot (`/usr/lib/greenboot/check/required.d/50-freezy.sh`). A
  new image that fails it is restarted, and after a few failed tries (four in
  my test, about 14 minutes) the
  bootloader goes back to the image before. Every check is local, so a server
  with no switch attached and no way out does not roll back a good image.
- **The install must keep `/boot` mounted.** On a disk made by `bootc install
  to-disk` with no other setting, `/boot` is unmounted whenever it is idle for
  two minutes. That stops a boot check still waiting, and in one test it left
  a staged update unapplied at the restart. With `/boot` kept mounted (its own
  partition, or the kernel argument `systemd.gpt_auto=0`) both work. The
  installer in step 9 gives `/boot` its own partition, and I'll repeat the
  rollback proof on a server it installed.
- **Never during a match.** `freezy-os-update` is the image's update command:
  it stages the newest build, moves to another image, or rolls back, and it
  refuses while a match is running or its results are not committed, the rule
  `deploy/freezy-update` keeps for the arena alone. Anything else that updates
  the server asks `freezy-os-update --check` first.
- **Updates are by hand.** Nothing updates itself at an event.
- **`freezy-update` stays** for package mode and as the way to try an arena
  build on an image-mode server without rebuilding the image. Its kept
  versions and `--rollback` are unchanged.
- **Rolling back across a database change.** The database is bbolt with JSON
  records and no migration step (`model/database.go`). An older arena opens a
  newer database and ignores what it does not know. Two tests hold that:
  - `model/older_arena_test.go` adds an unknown field to every record and an
    unknown table, and reads every table. It runs with `go test`.
  - `deploy/image/test_older_arena.sh` has this arena write an event and the
    arena from before the last change to the stored records read every table
    and start on it. CI runs it.
- **What a rollback costs.** A record the older arena saves loses the fields
  only the newer arena knows; one it only reads keeps them. A field whose type
  changed, or a change in what a value means, is not covered: the script
  catches the first when it happens, nothing catches the second. So the how-to
  still says to take a backup before an update.

## Jump machines and who routes the admin network

Two problems sit between a venue and a field. The venue's subnets can overlap
the field's, and the admin network (FMS and field gear) needs a gateway and
DNS. `deploy/host/NETWORK.md` maps the layout. A server answers each with one
setting in `/etc/freezy-net/vars.yaml`:

- **`freezy_venue_isolation`, on by default.** The external jump machine. It
  has one card on the venue VLAN and one on the transit VLAN, takes ssh only
  from outside, translates addresses on the way out, and picks a transit
  network that does not overlap the venue's. It is also the way in to the
  field server.
- **`freezy_admin_router`: `internal`, `gateway` or `none`.** Who is gateway
  and DNS for the admin VLAN.
  - `internal`, the default: the internal jump machine. It takes its outside
    address from the transit network, holds the gateway address on the admin
    VLAN, translates addresses out, answers DNS and hands out addresses over a
    range the settings name.
  - `gateway`: a hardware router does that job, as on my field.
  - `none`: a router in bridge mode. Rare.

| Venue isolation | Admin router | What you get |
|---|---|---|
| on | `internal` | The default. Needs only switches that carry tagged VLANs, of any brand |
| on | `gateway` | The router takes its outside address from the transit network |
| off | `internal` | A field on its own, with no venue link |
| off | `gateway` | A field on its own; the router does everything |
| off | `none` | Nothing here routes the admin network |
| on | `none` | The admin network has no way out. Allowed, with a warning |

- **The settings stay and can change at any time.** `freezy-jump` writes a
  setting and applies it, and the same step runs at every boot. Turning a
  machine on defines it, gives it a disk if it has none, and starts it. Turning
  it off stops it and keeps its disk.
- **One disk image serves both roles.** It is built with this repository,
  carried inside the server's image already installed, and copied to the kept
  partition the first time a machine is turned on. So this works with no
  network. The machine is told its role when it starts.
- **The internal machine will not fight a router.** Whenever it does not hold
  the gateway address it checks that nothing already answers there, and
  refuses if something does. `freezy-jump status` shows the refusal and
  `freezy-jump log internal` the reason.
- **An update replaces a machine's disk, and nothing else about it.** The
  server's image says which jump disk it carries, and each machine's disk has
  the one it was copied from noted beside it. When they differ, at the first
  start after an update or a rollback, the machine is stopped and given the
  disk the server now carries. Nothing is lost with the old disk:
  - which machines run, their role and their settings come from the server's
    `/etc/freezy-net/vars.yaml` at every start;
  - each machine's ssh host key is made once on the server, kept beside its
    disk on the kept partition, and handed to the machine at every start, so
    ssh sees the same machine.
- **VLAN numbers come from the settings.** Each machine attaches to whatever
  the venue, transit and admin VLANs are set to (`freezy_uplink_vlans`).
- **Team VLANs are not part of this.** The field server stays gateway, DHCP
  server and filter for the six team VLANs in every row of the table. Other
  VLANs a site's router carries, such as switch management, are the site's.
- **Keys, not passwords.** A jump machine takes the ssh keys in the server's
  `/etc/freezy-net/jump_authorized_keys`, or root's own `authorized_keys`
  when that file is missing.

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

## Decided on 2026-11-24

1. **The `cheesy` uid** is 880, fixed at build.
2. **A jump machine's disk** is carried in the server's image, already
   installed.
3. **One jump disk image serves both roles**, and the two settings above
   choose what runs. The default is venue isolation on and the internal
   machine as the admin router.
4. **Backups** are of the event database. The timer copies nothing until a
   server's settings name where they go.

## The work, in order

1. Make the draft boot to a working arena: the missing `freezy-firewalld-zones`
   and the missing time zone link, each with a test. Done.
2. CI: build the image, lint it, run the deployment tests. Done.
3. One uid for `cheesy`, 880, from a build argument. Done.
4. The data partition: the mount, the arena's data folder bound from it, Kea's
   leases and the last request on it, and a one-time move from the old
   locations. Done. The installer that makes and keeps the partition is step 9.
5. The boot check and the no-update-during-a-match hold. Done.
6. Jump machines: the one disk image, the two settings, `freezy-jump`, and the
   internal role. Done.
7. The backup timer. Done.
8. A test that an older arena opens a newer database.
9. The standalone installer: the kickstart and the ISO step.
10. The how-to, `deploy/image/README.md`: build, install, first boot, settings,
    update, roll back, back up, reinstall.
11. The fleet manager path, once the manager can take a server.
12. Moving the real field server over, with a backup taken first.
