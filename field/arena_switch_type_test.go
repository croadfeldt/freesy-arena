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

// Sets up an arena with network security on, the given switch type, and the field server's request
// directory in a temporary place. Returns the arena and a check for whether a request was written there.
func setupSwitchTypeTest(t *testing.T, switchType string) (*Arena, func() bool) {
	model.BaseDir = ".."
	requestDir := t.TempDir()
	originalRequestDir := network.UnifiSwitchRequestDir
	network.UnifiSwitchRequestDir = requestDir
	t.Cleanup(func() { network.UnifiSwitchRequestDir = originalRequestDir })

	arena, err := NewArena(filepath.Join(t.TempDir(), "test.db"))
	assert.Nil(t, err)
	t.Cleanup(func() { arena.Database.Close() })
	arena.EventSettings.NetworkSecurityEnabled = true
	arena.EventSettings.SwitchType = switchType
	// A Cisco switch address where nothing listens, so the Cisco path fails straight away.
	arena.EventSettings.SwitchAddress = "127.0.0.1"
	assert.Nil(t, arena.Database.UpdateEventSettings(arena.EventSettings))
	assert.Nil(t, arena.LoadSettings())

	requestWritten := func() bool {
		_, err := os.Stat(filepath.Join(requestDir, "teams.json"))
		return err == nil
	}
	return arena, requestWritten
}

func TestFieldServerSwitchTypeAsksTheHost(t *testing.T) {
	// An empty type is an event saved before the setting existed, which always used the field server.
	for _, switchType := range []string{model.SwitchTypeFieldServer, ""} {
		arena, requestWritten := setupSwitchTypeTest(t, switchType)
		assert.Nil(t, arena.LoadTestMatch())
		assert.Eventually(t, requestWritten, 2*time.Second, 10*time.Millisecond, "switch type %q", switchType)
		assert.Equal(t, "UNKNOWN", arena.networkSwitch.Status)
		assert.Equal(t, arena.UnifiSwitch.Status, arena.teamSwitchStatus())
	}
}

func TestCiscoSwitchTypeUsesTheSwitchAndNotTheHost(t *testing.T) {
	arena, requestWritten := setupSwitchTypeTest(t, model.SwitchTypeCisco)
	assert.Nil(t, arena.LoadTestMatch())
	// Nothing listens at the switch address, so the Cisco path ends in ERROR, and the arena reports it.
	assert.Eventually(t, func() bool { return arena.networkSwitch.Status == "ERROR" }, 5*time.Second,
		10*time.Millisecond)
	assert.Equal(t, "ERROR", arena.teamSwitchStatus())
	assert.False(t, requestWritten(), "the Cisco switch type asked the host for a network change")
	assert.Equal(t, "UNKNOWN", arena.UnifiSwitch.Status)
}

func TestNewEventsUseTheFieldServer(t *testing.T) {
	model.BaseDir = ".."
	database, err := model.OpenDatabase(filepath.Join(t.TempDir(), "fresh.db"))
	assert.Nil(t, err)
	defer database.Close()
	settings, err := database.GetEventSettings()
	assert.Nil(t, err)
	assert.Equal(t, model.SwitchTypeFieldServer, settings.SwitchType)
}
