#!/usr/bin/bash
# An older arena opens a database this arena wrote. Run from anywhere in a full clone:
#
#   deploy/image/test_older_arena.sh [REF]
#
# REF is the older arena. Without it, it is the commit before the last one that changed what the arena
# stores (model/ or game/, tests aside): the arena a rollback would return to across that change.
#
# This arena writes a database with a record in every table. The older arena's code, in a checkout of
# its own, then reads every table and starts on it as main.go does. It is the check behind "an update
# can be rolled back without restoring the database" in deploy/image/DESIGN.md.
set -euo pipefail
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"

if [ $# -gt 0 ]; then
    ref=$(git rev-parse --verify "$1^{commit}")
else
    last=$(git log -1 --format=%H -- model game ':!*_test.go' ':!*/test_helpers.go')
    ref=$(git rev-parse --verify "$last^") || {
        echo "test_older_arena.sh: the history here does not reach back past $last; this needs a full clone" >&2
        exit 2
    }
fi

work=$(mktemp -d)
trap 'git worktree remove --force "$work/older" 2>/dev/null || true; rm -rf "$work"' EXIT

echo "This arena:  $(git log -1 --format='%h %s')"
echo "Older arena: $(git log -1 --format='%h %s' "$ref")"

FREEZY_DB_WRITE=$work/event.db go test ./field -count=1 -run '^TestWriteDatabaseForAnotherArena$'

git worktree add --quiet --detach "$work/older" "$ref"
cp model/older_arena_open_test.go "$work/older/model/"
cp field/older_arena_open_test.go "$work/older/field/"
cd "$work/older"
FREEZY_DB_OPEN=$work/event.db go test ./model -count=1 -v -run '^TestOpenDatabaseFromAnotherArena$'
# The arena saves settings as it starts, so it gets a copy.
cp "$work/event.db" "$work/start.db"
FREEZY_DB_OPEN=$work/start.db go test ./field -count=1 -v -run '^TestStartArenaOnDatabaseFromAnotherArena$'
echo "OK: the older arena read every table of the newer database and started on it"
