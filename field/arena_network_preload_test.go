// Copyright 2026 Team 254. All Rights Reserved.

package field

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Team254/cheesy-arena/model"
	"github.com/Team254/cheesy-arena/network"
	"github.com/stretchr/testify/assert"
)

// Plays the host helper: answers every team request with the given state, and counts the requests.
func fakeHostHelper(t *testing.T, state *atomic.Value) *atomic.Int32 {
	requestDir, resultDir := network.UnifiSwitchRequestDir, t.TempDir()
	originalResultDir := network.UnifiSwitchResultDir
	network.UnifiSwitchResultDir = resultDir
	requests := new(atomic.Int32)
	stop := make(chan struct{})
	done := make(chan struct{})
	go func() {
		defer close(done)
		for {
			select {
			case <-stop:
				return
			case <-time.After(5 * time.Millisecond):
			}
			path := filepath.Join(requestDir, "teams.json")
			data, err := os.ReadFile(path)
			if err != nil {
				continue
			}
			os.Remove(path)
			var request struct{ Id string }
			if json.Unmarshal(data, &request) != nil {
				continue
			}
			requests.Add(1)
			result, _ := json.Marshal(map[string]string{"id": request.Id, "state": state.Load().(string),
				"message": "fake helper"})
			os.WriteFile(filepath.Join(resultDir, "status.json"), result, 0644)
		}
	}()
	t.Cleanup(func() {
		close(stop)
		<-done
		network.UnifiSwitchResultDir = originalResultDir
	})
	return requests
}

func TestFailedPreloadIsConfiguredAgainAtLoad(t *testing.T) {
	arena, _ := setupSwitchTypeTest(t, model.SwitchTypeFieldServer)
	var state atomic.Value
	state.Store("failed")
	requests := fakeHostHelper(t, &state)
	teams := [6]*model.Team{{Id: 254}, {Id: 1114}, nil, {Id: 2056}, nil, {Id: 148}}

	// The preload for the next match fails, so the switch goes red.
	arena.setupNetwork(teams, true)
	assert.Eventually(t, func() bool { return arena.teamSwitchStatus() == "ERROR" }, 2*time.Second, 5*time.Millisecond)
	assert.Equal(t, int32(1), requests.Load())

	// Loading that match with the same teams configures the network again instead of trusting the preload.
	state.Store("ok")
	arena.setupNetwork(teams, false)
	assert.Eventually(t, func() bool { return arena.teamSwitchStatus() == "ACTIVE" }, 2*time.Second, 5*time.Millisecond)
	assert.Equal(t, int32(2), requests.Load())
}

func TestSuccessfulPreloadIsNotRepeatedAtLoad(t *testing.T) {
	arena, _ := setupSwitchTypeTest(t, model.SwitchTypeFieldServer)
	var state atomic.Value
	state.Store("ok")
	requests := fakeHostHelper(t, &state)
	teams := [6]*model.Team{{Id: 254}, {Id: 1114}, nil, {Id: 2056}, nil, {Id: 148}}

	arena.setupNetwork(teams, true)
	assert.Eventually(t, func() bool { return arena.teamSwitchStatus() == "ACTIVE" }, 2*time.Second, 5*time.Millisecond)
	arena.setupNetwork(teams, false)
	time.Sleep(100 * time.Millisecond)
	assert.Equal(t, int32(1), requests.Load())

	// Different teams at load are always configured.
	arena.setupNetwork(teams, true)
	assert.Eventually(t, func() bool { return requests.Load() == 2 }, 2*time.Second, 5*time.Millisecond)
	other := teams
	other[2] = &model.Team{Id: 971}
	arena.setupNetwork(other, false)
	assert.Eventually(t, func() bool { return requests.Load() == 3 }, 2*time.Second, 5*time.Millisecond)
}
