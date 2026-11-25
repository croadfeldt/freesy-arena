#!/usr/bin/bash
# Did this boot come up able to run a field? greenboot runs this at every boot.
#
# While a new image is on trial, a failure here restarts the server, and after the tries greenboot allows
# the bootloader goes back to the image before. On any other boot a failure is only reported
# (`journalctl -u greenboot-healthcheck`).
#
# Every check is local. A field server is often set up with no switch attached and no way out, and a
# check that needed either would roll back a good image. What must hold:
#   - the boot's own steps did not fail: kept data, the network interfaces, host setup;
#   - the team VLAN filter is loaded, because without it teams reach each other;
#   - Kea runs, once a match has ever been loaded (before that it has no configuration and stays off);
#   - the arena answers on its web port.
set -u
WAIT=${FREEZY_BOOT_WAIT:-180}
ARENA=${FREEZY_BOOT_ARENA:-http://127.0.0.1:8080/}
KEA_CONFIG=${FREEZY_BOOT_KEA_CONFIG:-/etc/freezy-net/kea/kea-dhcp4.conf}
STEPS="freezy-data.service freezy-host-network.service freezy-host-setup.service"

settled() {
    local unit
    for unit in $STEPS; do
        case $(systemctl is-active "$unit") in active|failed) ;; *) return 1 ;; esac
    done
}
filter() { nft list table inet freezy_field >/dev/null 2>&1; }
kea() { [ ! -e "$KEA_CONFIG" ] || systemctl is-active --quiet freezy-kea.service; }
arena() { curl -s -o /dev/null -m 3 "$ARENA"; }

# None of these is ordered before this check, and after an update the arena's container image is made
# again from the copy the new image carries. Give them time.
for ((i = 0; i < WAIT; i += 3)); do
    settled && filter && kea && arena && break
    sleep 3
done

bad=0
for unit in $STEPS; do
    systemctl is-active --quiet "$unit" || { echo "$unit did not finish: $(systemctl is-active "$unit")"; bad=1; }
done
filter || { echo "the team VLAN filter is not loaded"; bad=1; }
kea || { echo "Kea has a configuration and is not running"; bad=1; }
arena || { echo "the arena did not answer at $ARENA within ${WAIT}s"; bad=1; }
exit $bad
