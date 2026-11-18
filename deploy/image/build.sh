#!/usr/bin/bash
# Build the field server's image mode (bootc) image. Run from anywhere in the repository:
#
#   deploy/image/build.sh [--site DIR] [--tag NAME]
#
# --site DIR  a directory laid out like / with this field server's own files: /etc/hostname, ssh keys,
#             sudo rules, /etc/freezy-net/vars.yaml. Without it the image has no way to log in.
# --tag NAME  the image name (default localhost/freezy-field-server:latest).
#
# It builds the arena and Kea container images from this checkout, packs them into the operating system
# image, and builds that.
#
# Build as root, or on a build store that is not ZFS: a rootless build on ZFS loses package database
# and SELinux policy updates (the Containerfile checks for this and stops). PODMAN overrides the podman
# command, for example PODMAN="podman --root /var/tmp/build/storage".
set -euo pipefail
cd "$(dirname "$0")/../.."
site= tag=localhost/freezy-field-server:latest
podman=${PODMAN:-podman}
while [ $# -gt 0 ]; do
    case "$1" in
        --site) site=$2; shift 2 ;;
        --tag) tag=$2; shift 2 ;;
        *) echo "usage: $0 [--site DIR] [--tag NAME]" >&2; exit 2 ;;
    esac
done
out=deploy/image/build
rm -rf "$out" && mkdir -p "$out/site"
[ -z "$site" ] || cp -a "$site"/. "$out/site/"

$podman build -t localhost/freezy-arena:latest -f Containerfile .
$podman build -t localhost/freezy-kea:latest deploy/kea
$podman save -o "$out/freezy-arena.tar" localhost/freezy-arena:latest
$podman save -o "$out/freezy-kea.tar" localhost/freezy-kea:latest

$podman build -t "$tag" --ignorefile deploy/image/containerignore -f deploy/image/Containerfile .
echo "built $tag"
