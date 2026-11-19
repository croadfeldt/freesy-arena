// Copyright 2026 Team 254. All Rights Reserved.

package field

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/Team254/cheesy-arena/model"
	"github.com/Team254/cheesy-arena/network"
	"github.com/stretchr/testify/assert"
)

// On the field, killing the arena took all six team networks away twelve seconds later: on start it
// loads the empty test match, and that asked the host for a network with no teams.
func TestArenaStartLeavesTeamNetworksAlone(t *testing.T) {
	model.BaseDir = ".."
	requestDir := t.TempDir()
	originalRequestDir := network.UnifiSwitchRequestDir
	network.UnifiSwitchRequestDir = requestDir
	t.Cleanup(func() { network.UnifiSwitchRequestDir = originalRequestDir })
	requestPath := filepath.Join(requestDir, "teams.json")
	requestWritten := func() bool {
		_, err := os.Stat(requestPath)
		return err == nil
	}

	// An event with network security on, as on a real field.
	dbPath := filepath.Join(t.TempDir(), "test.db")
	arena, err := NewArena(dbPath)
	assert.Nil(t, err)
	arena.EventSettings.NetworkSecurityEnabled = true
	assert.Nil(t, arena.Database.UpdateEventSettings(arena.EventSettings))
	assert.Nil(t, arena.Database.Close())

	// Starting the arena on that event must not ask the host to change the team networks.
	arena, err = NewArena(dbPath)
	assert.Nil(t, err)
	t.Cleanup(func() { arena.Database.Close() })
	assert.True(t, arena.EventSettings.NetworkSecurityEnabled)
	time.Sleep(200 * time.Millisecond)
	assert.False(t, requestWritten(), "the arena asked for a team network change while starting")

	// An operator loading a match afterwards still does.
	assert.Nil(t, arena.LoadTestMatch())
	assert.Eventually(t, requestWritten, 2*time.Second, 10*time.Millisecond)
}
