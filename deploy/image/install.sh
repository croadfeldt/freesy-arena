#!/usr/bin/bash
# Turn a Fedora image mode (bootc) base into the field server. Run inside an image build:
#
#   install.sh SOURCE IMAGES
#
# SOURCE  a checkout of this repository
# IMAGES  a directory holding freezy-arena-rootfs.tar and freezy-kea-rootfs.tar, and freezy-jump.qcow2
#         (the jump machines' disk, from deploy/jump/build-disk) when the field server is to run them
#
# CHEESY_UID in the environment is the uid of the arena's account. The Containerfile sets it.
#
# deploy/image/Containerfile uses it, and so can any other image build that starts from the same base
# (a fleet site's, for example), so the list of what a field server needs lives in one place.
set -euo pipefail
src=$1 images=$2
host=$src/deploy/host

# The arena account's uid. It names the folder the arena's container unit lives in, so it is settled
# here, once, and must not belong to anything in the base image or to an account a site added.
uid=${CHEESY_UID:?set CHEESY_UID to the uid for the cheesy account}
case $uid in ''|*[!0-9]*) echo "install.sh: CHEESY_UID must be a number, got '$uid'" >&2; exit 1 ;; esac
taken=$( { getent passwd "$uid"; getent group "$uid"; \
    grep -rhE "^[ug][[:space:]]+[^[:space:]]+[[:space:]]+$uid([[:space:]:]|\$)" /usr/lib/sysusers.d /etc/sysusers.d 2>/dev/null; } || true)
if [ -n "$taken" ]; then
    echo "install.sh: uid $uid is already in use in this image; pick another CHEESY_UID:" >&2
    echo "$taken" >&2
    exit 1
fi

# Virtual machines (the jump machine), Ansible for the network playbooks, the firewall, a few tools.
# greenboot runs the boot check and rolls back an image that fails it; only greenboot itself, because
# its default checks need a way out and a field server often has none.
# libvirt's `default` network is not installed: its DHCP server would hold the port Kea needs. Weak
# dependencies are left out: they pull in storage and network back ends the field server never uses.
dnf -y --setopt=install_weak_deps=False install libvirt-daemon-kvm libvirt-daemon-config-nwfilter \
    libvirt-client qemu-img ansible-core nftables firewalld python3 tmux vim-enhanced rsync \
    policycoreutils-python-utils greenboot
dnf clean all
rm -rf /var/cache/* /var/log/dnf* /var/lib/dnf /run/dnf

# Prove the install really landed. On some build stores (rootless podman on ZFS is one) the package
# database and the SELinux policy store lose their updates while the files still arrive, which gives an
# image that looks fine and is not.
rpm -q libvirt-daemon-kvm ansible-core firewalld nftables python3-pyyaml greenboot >/dev/null
test ! -e /etc/selinux/targeted/tmp && test ! -e /etc/selinux/targeted/previous

# The host network helper, the team VLAN filter, the playbooks and the units, in the places
# deploy/host/README.md lists.
install -D -m 0755 "$host/freezy-net-helper" /usr/libexec/freezy-net-helper
install -D -m 0755 "$host/freezy-vm-interfaces" /usr/share/freezy-vm-interfaces
install -D -m 0755 "$host/freezy-firewalld-zones" /usr/share/freezy-firewalld-zones
install -D -m 0755 "$src/deploy/image/freezy-image-import" /usr/libexec/freezy-image-import
install -D -m 0755 "$src/deploy/image/freezy-data" /usr/libexec/freezy-data
install -D -m 0755 "$host/freezy-jump" /usr/libexec/freezy-jump
# The image's own update command, and freezy-update, whose arena client it uses to ask about the match.
install -D -m 0755 "$src/deploy/image/freezy-os-update" /usr/libexec/freezy-os-update
install -D -m 0755 "$src/deploy/freezy-update" /usr/libexec/freezy-update
ln -s ../libexec/freezy-os-update /usr/bin/freezy-os-update
# Copies the arena's database backups off the server, when a server's settings say where to.
install -D -m 0755 "$src/deploy/image/freezy-backup" /usr/libexec/freezy-backup
ln -s ../libexec/freezy-backup /usr/bin/freezy-backup
ln -s ../libexec/freezy-jump /usr/bin/freezy-jump
install -m 0644 "$host/freezy-net.path" "$host/freezy-net.service" "$host/freezy-firewall.service" \
    "$host/freezy-jump.service" /usr/lib/systemd/system/
install -D -m 0644 "$host/freezy-net.tmpfiles.conf" /usr/lib/tmpfiles.d/freezy-net.conf
mkdir -p /usr/share/freezy-net
cp -r "$host/ansible/." /usr/share/freezy-net/
install -m 0644 "$host/freezy-field.nft" /usr/share/freezy-net/freezy-field.nft
install -D -m 0644 "$host/freezy-kea.container" /usr/share/containers/systemd/freezy-kea.container
install -D -m 0644 "$src/deploy/freezy-arena.container" "/etc/containers/systemd/users/$uid/freezy-arena.container"
install -D -m 0644 "$src/deploy/image/freezy-arena.container.d/10-image.conf" \
    "/etc/containers/systemd/users/$uid/freezy-arena.container.d/10-image.conf"

# Kept data. Outside the image the arena's data is a named volume in its account's home and Kea's leases
# are in /var/lib/freezy-net. Here both are folders under /var/lib/freezy, which freezy-data mounts from
# the data partition, so a reinstall that keeps the partition keeps them. Each line must change exactly
# one mount, or the build stops.
arena_unit=/etc/containers/systemd/users/$uid/freezy-arena.container
kea_unit=/usr/share/containers/systemd/freezy-kea.container
sed -i 's|^Volume=freezy-arena-data:/data:|Volume=/var/lib/freezy/arena:/data:|' "$arena_unit"
sed -i 's|^Volume=/var/lib/freezy-net/kea:/var/lib/kea:|Volume=/var/lib/freezy/kea:/var/lib/kea:|' "$kea_unit"
test "$(grep -c '^Volume=/var/lib/freezy/arena:/data:' "$arena_unit")" = 1
test "$(grep -c '^Volume=/var/lib/freezy/kea:/var/lib/kea:' "$kea_unit")" = 1
if grep -q 'freezy-arena-data\|/var/lib/freezy-net' "$arena_unit" "$kea_unit"; then
    echo "install.sh: a container still keeps data outside /var/lib/freezy" >&2
    exit 1
fi

# The arena's account, the boot-time units and their settings.
cp -r "$src/deploy/image/files/." /
sed -i "s/@CHEESY_UID@/$uid/" /usr/lib/sysusers.d/freezy.conf
grep -qE "^u cheesy $uid " /usr/lib/sysusers.d/freezy.conf

# The Kea and arena containers, carried inside this image and turned into container images at boot.
# The stamp changes with every build, so an updated operating system image replaces them.
install -d /usr/share/freezy-images
install -m 0644 "$images/freezy-arena-rootfs.tar" "$images/freezy-kea-rootfs.tar" /usr/share/freezy-images/
date -u +%Y%m%d%H%M%S-$RANDOM > /usr/share/freezy-images/stamp

# The jump machines' disk image (deploy/jump/build-disk), when the build was given one. A field server
# without it runs, and `freezy-jump` says the disk is missing when asked to start a machine.
if [ -f "$images/freezy-jump.qcow2" ]; then
    install -m 0644 "$images/freezy-jump.qcow2" /usr/share/freezy-images/freezy-jump.qcow2
    # Which disk this is, so a server updated to this image gives its jump machines the new one.
    sha256sum < "$images/freezy-jump.qcow2" | cut -d' ' -f1 > /usr/share/freezy-images/freezy-jump.qcow2.id
else
    echo "install.sh: no freezy-jump.qcow2 given; this image cannot start jump machines" >&2
fi

# Nothing shipped may be group- or world-writable.
chmod -R go-w /usr/libexec/freezy-net-helper /usr/libexec/freezy-image-import /usr/libexec/freezy-data /usr/libexec/freezy-os-update /usr/libexec/freezy-backup /usr/libexec/freezy-update /usr/lib/greenboot/check/required.d/50-freezy.sh /usr/libexec/freezy-jump /usr/share/freezy-net \
    /usr/share/freezy-vm-interfaces /usr/share/freezy-firewalld-zones /usr/share/freezy-images /usr/share/containers/systemd \
    /etc/containers/systemd /usr/lib/sysusers.d/freezy.conf /usr/lib/tmpfiles.d/freezy-net.conf \
    /usr/lib/tmpfiles.d/freezy-image.conf /etc/subuid /etc/subgid /etc/sysconfig/libvirt-guests

# firewalld keeps its defaults plus the arena's ports; the team VLAN filter decides what a team reaches.
firewall-offline-cmd --add-port=8080/tcp --add-port=1750/tcp --add-port=1160/udp
systemctl enable firewalld sshd virtqemud.socket virtnetworkd.socket virtstoraged.socket \
    libvirt-guests.service freezy-data.service freezy-images.service freezy-host-network.service freezy-host-setup.service \
    freezy-firewall.service freezy-net.path freezy-jump.service freezy-backup.timer greenboot-healthcheck.service
systemctl --global enable freezy-arena-image.service
