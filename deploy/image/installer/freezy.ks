# Installs the Freezy Arena field server from the installer ISO that build-iso makes, with nobody at the
# keyboard and no network. The image and freezy-install-plan are on the ISO, under freezy/.
#
# The disk: freezy-install-plan chooses it, keeps a partition labelled freezy-data and makes one when
# there is none. It refuses a disk that holds something else unless the installer was started with
# freezy.wipe=yes. /boot gets a partition of its own (deploy/image/DESIGN.md, "The install must keep
# /boot mounted").
#
# When it is done the machine powers off. It does not restart, because a machine that starts from the
# installer again would install again. Take the installer out, then power on.
text
lang en_US.UTF-8
keyboard us
timezone UTC --utc
rootpw --lock
bootloader
%include /tmp/freezy-storage.ks
ostreecontainer --transport=oci --url=/run/install/repo/freezy/image --no-signature-verification
poweroff

%pre --erroronfail
# What the plan says goes to every console, so it is on the screen and on a serial line.
python3 /run/install/repo/freezy/freezy-install-plan > /tmp/freezy-storage.ks 2> /tmp/freezy-plan.log
status=$?
for console in /dev/tty1 /dev/ttyS0 /dev/console; do cat /tmp/freezy-plan.log > "$console" 2>/dev/null; done
if [ -e /run/install/repo/freezy/update-from ]; then cp /run/install/repo/freezy/update-from /tmp/freezy-update-from; fi
exit $status
%end

%post --nochroot --erroronfail
# The installed system's root, as the installer names it for scripts that run outside it.
if [ -e /tmp/freezy-update-from ]; then cp /tmp/freezy-update-from "${ANA_INSTALL_PATH:?}/etc/freezy-update-from"; fi
%end

%post --erroronfail
# The image mounts the kept partition itself, by label (freezy-data.service). With a line in fstab as
# well, a partition that cannot be mounted would stop the boot; without it the server comes up and only
# the arena waits.
sed -i '\|[[:space:]]/var/lib/freezy[[:space:]]|d' /etc/fstab
if grep -q '[[:space:]]/var/lib/freezy[[:space:]]' /etc/fstab; then exit 1; fi

# The server was installed from the ISO, so that is where it would look for updates. Point it at the
# registry the ISO was built with, when it was built with one.
if [ -s /etc/freezy-update-from ]; then
    bootc switch --mutate-in-place --transport registry "$(cat /etc/freezy-update-from)"
fi
rm -f /etc/freezy-update-from
%end
