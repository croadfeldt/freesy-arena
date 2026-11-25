// Starts the arena on a database written by another version of it, the way main.go does.
// deploy/image/test_older_arena.sh copies this file into an older checkout and runs it there.

package field

import (
	"os"
	"testing"
)

func TestStartArenaOnDatabaseFromAnotherArena(t *testing.T) {
	path := os.Getenv("FREEZY_DB_OPEN")
	if path == "" {
		t.Skip("FREEZY_DB_OPEN is not set")
	}
	arena, err := NewArena(path)
	if err != nil {
		t.Fatalf("starting the arena: %v", err)
	}
	defer arena.Database.Close()
	if arena.EventSettings == nil || arena.EventSettings.Name != "Newer Event" {
		t.Errorf("the event settings did not load: %+v", arena.EventSettings)
	}
}
