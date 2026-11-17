// Copyright 2025 Freezy Arena contributors. All Rights Reserved.

package network

import (
	"encoding/json"
	"github.com/Team254/cheesy-arena/model"
	"github.com/stretchr/testify/assert"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// Points the switch at temporary spool directories and returns them.
func setupUnifiSwitchTest(t *testing.T) (*UnifiSwitch, string, string) {
	oldRequestDir, oldResultDir := UnifiSwitchRequestDir, UnifiSwitchResultDir
	t.Cleanup(
		func() {
			UnifiSwitchRequestDir, UnifiSwitchResultDir = oldRequestDir, oldResultDir
		},
	)
	UnifiSwitchRequestDir = t.TempDir()
	UnifiSwitchResultDir = t.TempDir()

	sw := NewUnifiSwitch("", "")
	sw.resultTimeout = 2 * time.Second
	sw.resultPollInterval = 5 * time.Millisecond
	return sw, UnifiSwitchRequestDir, UnifiSwitchResultDir
}

// Stands in for the host helper: waits for a request and answers it with the given state.
func answerUnifiSwitchRequest(t *testing.T, requestDir, resultDir, state, message string) chan unifiSwitchRequest {
	requests := make(chan unifiSwitchRequest, 1)
	go func() {
		requestPath := filepath.Join(requestDir, unifiSwitchRequestFile)
		for i := 0; i < 400; i++ {
			data, err := os.ReadFile(requestPath)
			if err != nil {
				time.Sleep(5 * time.Millisecond)
				continue
			}
			var request unifiSwitchRequest
			if !assert.Nil(t, json.Unmarshal(data, &request)) {
				return
			}
			writeUnifiSwitchResult(t, resultDir, unifiSwitchResult{Id: request.Id, State: state, Message: message})
			requests <- request
			return
		}
	}()
	return requests
}

func writeUnifiSwitchResult(t *testing.T, resultDir string, result unifiSwitchResult) {
	data, err := json.Marshal(result)
	assert.Nil(t, err)
	assert.Nil(t, os.WriteFile(filepath.Join(resultDir, unifiSwitchResultFile), data, 0644))
}

func TestUnifiConfigureTeamEthernet(t *testing.T) {
	sw, requestDir, resultDir := setupUnifiSwitchTest(t)
	assert.Equal(t, "UNKNOWN", sw.Status)

	// A result left over from an earlier request must not be mistaken for the answer to this one.
	writeUnifiSwitchResult(t, resultDir, unifiSwitchResult{Id: "stale", State: "error", Message: "old failure"})

	requests := answerUnifiSwitchRequest(t, requestDir, resultDir, "ok", "")
	teams := [6]*model.Team{{Id: 254}, nil, {Id: 1114}, {Id: 8}, nil, {Id: 10101}}
	assert.Nil(t, sw.UnifiConfigureTeamEthernet(teams))
	assert.Equal(t, "ACTIVE", sw.Status)

	// Station order is preserved and empty stations are sent as blanks.
	request := <-requests
	assert.NotEmpty(t, request.Id)
	assert.Equal(t, [6]string{"254", "", "1114", "8", "", "10101"}, request.TeamNumbers)

	// No temporary files are left behind in the request directory.
	entries, err := os.ReadDir(requestDir)
	assert.Nil(t, err)
	assert.Equal(t, 1, len(entries))
}

func TestUnifiConfigureTeamEthernetNoTeams(t *testing.T) {
	sw, requestDir, resultDir := setupUnifiSwitchTest(t)

	// An empty field still goes to the helper, so that the previous match's networks are removed.
	requests := answerUnifiSwitchRequest(t, requestDir, resultDir, "ok", "")
	assert.Nil(t, sw.UnifiConfigureTeamEthernet([6]*model.Team{}))
	assert.Equal(t, "ACTIVE", sw.Status)
	request := <-requests
	assert.Equal(t, [6]string{}, request.TeamNumbers)
}

func TestUnifiConfigureTeamEthernetHelperError(t *testing.T) {
	sw, requestDir, resultDir := setupUnifiSwitchTest(t)

	answerUnifiSwitchRequest(t, requestDir, resultDir, "error", "dhcp reload failed")
	err := sw.UnifiConfigureTeamEthernet([6]*model.Team{{Id: 254}})
	if assert.NotNil(t, err) {
		assert.Contains(t, err.Error(), "dhcp reload failed")
	}
	assert.Equal(t, "ERROR", sw.Status)
}

func TestUnifiConfigureTeamEthernetHelperSilent(t *testing.T) {
	sw, _, resultDir := setupUnifiSwitchTest(t)
	sw.resultTimeout = 50 * time.Millisecond

	// Nothing answers. A stale success from an earlier request must not turn this into a pass.
	writeUnifiSwitchResult(t, resultDir, unifiSwitchResult{Id: "stale", State: "ok"})
	err := sw.UnifiConfigureTeamEthernet([6]*model.Team{{Id: 254}})
	if assert.NotNil(t, err) {
		assert.Contains(t, err.Error(), "did not answer")
	}
	assert.Equal(t, "ERROR", sw.Status)
}

func TestUnifiConfigureTeamEthernetNoSpoolDirectory(t *testing.T) {
	sw, _, _ := setupUnifiSwitchTest(t)
	UnifiSwitchRequestDir = filepath.Join(t.TempDir(), "missing")

	err := sw.UnifiConfigureTeamEthernet([6]*model.Team{{Id: 254}})
	assert.NotNil(t, err)
	assert.Equal(t, "ERROR", sw.Status)
}
