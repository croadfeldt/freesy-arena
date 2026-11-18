#!/bin/sh
# Container entrypoint for Freezy Arena.
#
# static/img holds both the images shipped in the repo and the logos and team avatars added at an event.
# It lives in the /data volume so the event's files survive an image rebuild. Refresh the shipped
# images from the image's own copy on every start, so they still update with the image; files that
# exist only in the volume (uploads, downloaded avatars) are left alone.
set -e
mkdir -p /data/img /data/db /data/logs
# Copy contents, modes and times only. `cp -a` would also copy each file's SELinux label, and inside a
# container that label is private to this one container: the next container (after a restart or a
# reboot) could not read the directory and would fail to start.
cp -r --preserve=mode,timestamps /app/static/img.dist/. /data/img/
exec /app/cheesy-arena "$@"
