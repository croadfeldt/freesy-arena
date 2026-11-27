# Install and run a field server from the image

This is how to put a Freezy Arena field server on a machine, change its settings, update it, go
back, back it up and reinstall it. It is for someone with one server and no fleet tooling. You need
to be at home with Linux, `podman` and ssh.

One image carries the operating system (Fedora image mode), the arena, Kea and the field's network
setup, so the server is installed and updated as a whole and needs no network at the venue.
`DESIGN.md` says why it is built this way. `../host/NETWORK.md` maps the field network and says what
the switches need.

## What you need

- **The server:** an x86_64 machine with one disk of 64 GB or more, virtualization turned on in the
  firmware (the jump machines are virtual machines), and one network card connected to a switch port
  that carries the field's VLANs tagged.
- **A build machine:** Fedora with `podman`, `lorax`, `xorriso` and root. About 20 GB free.
- **A USB stick** of 8 GB or more for the installer.

## 1. Put your settings in the image

Files under `deploy/image/site/` are copied to `/` in the image. Nothing in that folder is kept in
git but its README, so keys stay out of the repository. A server needs three things from you:

- **A way in.** There are no passwords, and root's is locked. Give root an ssh key:

      mkdir -p deploy/image/site/usr/ssh deploy/image/site/etc/ssh/sshd_config.d
      cp ~/.ssh/id_ed25519.pub deploy/image/site/usr/ssh/root.keys
      echo 'AuthorizedKeysFile /usr/ssh/%u.keys .ssh/authorized_keys' \
          > deploy/image/site/etc/ssh/sshd_config.d/30-site-keys.conf

- **Keys for the jump machines**, one per line:

      mkdir -p deploy/image/site/etc/freezy-net
      cp ~/.ssh/id_ed25519.pub deploy/image/site/etc/freezy-net/jump_authorized_keys

- **Its settings**, in `deploy/image/site/etc/freezy-net/vars.yaml`. Every setting and its default
  is in `../host/ansible/vars.yaml`; put only what differs in yours. The one you almost certainly
  need is the network card's name:

      freezy_field_interface: eno1

  The network is built from these at the first boot, and what exists is never rebuilt. So set the
  card's name, the VLAN numbers and the FMS address here, before you install.

A host name goes in `deploy/image/site/etc/hostname`.

## 2. Build the image and the installer

From the top of the repository, as root:

    deploy/jump/build-disk deploy/image/carried/freezy-jump.qcow2
    podman build -t localhost/freezy-field-server -f deploy/image/Containerfile .
    deploy/image/installer/build-iso freezy.iso

- The first line builds the jump machines' disk, which the image carries. Leave it out and the
  server runs without jump machines.
- `build-iso` downloads Fedora's installer once (1.2 GB) and adds the image to it. The result is
  about 4 GB.
- If the server will take updates from a registry, say which:
  `build-iso --update-from quay.io/NAMESPACE/freezy-field-server:latest freezy.iso`.

Write `freezy.iso` to the USB stick with Fedora Media Writer or `dd`.

## 3. Install

Start the server from the stick. It installs with nobody at the keyboard, takes about 15 minutes,
and **powers the machine off** when it is done. Take the stick out, then power on.

Which disk it uses, and what it erases:

| The disk | What happens |
|---|---|
| Empty | Installed on. A 16 GiB partition labelled `freezy-data` is made for the data that must outlive a reinstall |
| Holds a `freezy-data` partition | Installed on. That partition is kept and everything else on the disk is erased |
| Holds anything else | **Refused.** The reason is on the screen and nothing is changed |
| More than one disk, none with `freezy-data` | Refused until you say which |

To answer a refusal, press `e` on the installer's first menu entry and add to the line that starts
with `linux`:

- `freezy.wipe=yes` to erase a disk that holds something else
- `freezy.disk=sda` to choose the disk
- `freezy.data_gb=64` for a bigger data partition

## 4. First boot

- The arena answers on port 8080 of the FMS address (`http://10.0.100.5:8080` by default) about half
  a minute after power-on.
- The jump machines take about three minutes more. `freezy-jump status` shows each one, its
  addresses and whether its setup finished.
- The time zone is UTC. Change it with `timedatectl set-timezone America/Chicago`.

To check the server: `systemctl --failed` lists nothing, and
`journalctl -b -u greenboot-healthcheck` ends in `health-check passed`.

## 5. Change settings on a running server

The server's settings are in `/etc/freezy-net/vars.yaml`. An update leaves that file alone, and a
reinstall puts it back (see "Reinstall").

- **Which jump machines run**, and who routes the admin network: `freezy-jump venue-isolation on|off`
  and `freezy-jump admin-router internal|gateway|none`. They write the file and apply the change.
  `../host/NETWORK.md`, "Which jump machines run", has the table of setups.
- **Where backups go:** see "Back up" below.
- **The arena's own settings** (teams, schedule, access point, passwords) are in the arena, under
  Setup, and live in its database.

## 6. Update

Take a backup first (see below), and update between matches. `freezy-os-update` refuses while a
match is running or its results are not committed.

- **From a registry**, when the installer was built with `--update-from`:

      freezy-os-update

- **From an image you carry in.** On the build machine, `podman save -o field.tar
  localhost/freezy-field-server`. On the server:

      podman load -i field.tar
      freezy-os-update --image localhost/freezy-field-server:latest --transport containers-storage

Either way the new image takes effect at the next restart. Add `--apply` to restart at once.

An update replaces the operating system, the arena and Kea together. It also replaces the jump
machines' disks when the new image carries a newer one; their settings and ssh host keys are kept.
The database, the leases and `/etc/freezy-net/vars.yaml` are not touched.

## 7. Go back

- **By itself.** A new image must pass a check at boot: the network steps finished, the team VLAN
  filter is loaded, Kea runs, and the arena answers. If it fails, the server restarts and tries
  again, and after four failed boots it goes back to the image before. That takes about 15 minutes.
- **By hand:** `freezy-os-update --rollback`, then restart.

The older arena opens the newer database. A record it saves while you are back loses any field only
the newer arena knew, which is why the backup comes first.

## 8. Back up

The arena writes a copy of its database after every committed match, beside the database. To have
those copied off the server every five minutes, name a target in `/etc/freezy-net/vars.yaml`:

    freezy_backup_target: label:FREEZYBAK

- `label:NAME` is a disk whose filesystem has that label, a USB stick for one. It is mounted only
  during a copy, so you can pull it at any other moment.
- Anything else is an rsync destination, such as `backup@host:/srv/freezy`. A key in
  `/etc/freezy-net/backup_key` is used when it exists.

`freezy-backup --status` says when the last copy succeeded and whether the newest backup has left
the server. A copy that did not happen shows in `systemctl --failed` as `freezy-backup.service`.

To restore, upload a backup file in the arena under Setup, Settings.

## 9. Reinstall

Start the server from the installer again. It finds the `freezy-data` partition, keeps it, and
replaces everything else. The event database, Kea's leases and the jump machines' disks are on that
partition, so the arena comes back with the event it had.

The server's settings come back too. A copy of `/etc/freezy-net/vars.yaml` and of the backup key is
kept on that partition each time one changes, and the first boot after a reinstall puts them back.
If the new image holds different settings, the server's own win and the image's are left beside
them as `/etc/freezy-net/vars.yaml.from-image`. To take the image's, copy that file over
`vars.yaml` and restart.

Anything else you changed on the server by hand is lost: the time zone, and keys you added outside
the image. Keep those in `deploy/image/site/`.

## What I have and have not run

Each step here was run in virtual machines, under BIOS and UEFI: the build, the install, the
reinstall that keeps its data and its settings, an update carried in, the automatic and manual way
back, and the backup to a labelled disk. I have not yet run it on real hardware or from a real USB
stick, updated from a registry, or backed up to an rsync destination on another machine.
