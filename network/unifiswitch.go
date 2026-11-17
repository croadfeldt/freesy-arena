// Copyright 2025 Freezy Arena contributors. All Rights Reserved.
//
// Methods for configuring the team networks when the field server itself routes the team VLANs and serves
// their DHCP (the UniFi-switch layout), instead of a Cisco switch doing both.
//
// The arena does not change the host's network itself. It hands the six team numbers to a root-owned helper
// on the host through a spool directory and waits for the helper's verdict. See deploy/host/README.md.

package network

import (
	"encoding/json"
	"fmt"
	"github.com/Team254/cheesy-arena/model"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"time"
)

const (
	unifiSwitchRequestFile          = "teams.json"
	unifiSwitchResultFile           = "status.json"
	unifiSwitchResultTimeoutSec     = 120
	unifiSwitchResultPollIntervalMs = 250
	unifiSwitchResultStateOk        = "ok"
)

// Directories shared with the host helper. The arena writes requests; the helper writes results.
var (
	UnifiSwitchRequestDir = "/run/freezy-net/request"
	UnifiSwitchResultDir  = "/run/freezy-net/result"
)

type UnifiSwitch struct {
	address            string
	password           string
	mutex              sync.Mutex
	resultTimeout      time.Duration
	resultPollInterval time.Duration
	Status             string
}

// The request handed to the host helper. TeamNumbers always has six entries in station order (R1, R2, R3, B1,
// B2, B3); an empty string means the station is empty.
type unifiSwitchRequest struct {
	Id          string    `json:"id"`
	TeamNumbers [6]string `json:"team_numbers"`
}

// The helper's verdict on the request with the same Id.
type unifiSwitchResult struct {
	Id      string `json:"id"`
	State   string `json:"state"`
	Message string `json:"message"`
}

func NewUnifiSwitch(address, password string) *UnifiSwitch {
	return &UnifiSwitch{
		address:            address,
		password:           password,
		resultTimeout:      unifiSwitchResultTimeoutSec * time.Second,
		resultPollInterval: unifiSwitchResultPollIntervalMs * time.Millisecond,
		Status:             "UNKNOWN",
	}
}

// Sets up wired networks for the given set of teams. Returns an error, and leaves Status as ERROR, unless the
// host helper confirms that it applied this exact request.
func (sw *UnifiSwitch) UnifiConfigureTeamEthernet(teams [6]*model.Team) error {
	// Make sure multiple configurations aren't being set at the same time.
	sw.mutex.Lock()
	defer sw.mutex.Unlock()
	sw.Status = "CONFIGURING"

	request := unifiSwitchRequest{Id: strconv.FormatInt(time.Now().UnixNano(), 10)}
	for i, team := range teams {
		if team != nil {
			request.TeamNumbers[i] = strconv.Itoa(team.Id)
		}
	}

	if err := sw.writeRequest(request); err != nil {
		sw.Status = "ERROR"
		return err
	}

	result, err := sw.waitForResult(request.Id)
	if err != nil {
		sw.Status = "ERROR"
		return err
	}
	if result.State != unifiSwitchResultStateOk {
		sw.Status = "ERROR"
		return fmt.Errorf("host network helper reported %q: %s", result.State, result.Message)
	}

	sw.Status = "ACTIVE"
	return nil
}

// Writes the request where the host helper watches for it. The file is written under a temporary name and
// renamed into place so that the helper never reads a partial request.
func (sw *UnifiSwitch) writeRequest(request unifiSwitchRequest) error {
	data, err := json.Marshal(request)
	if err != nil {
		return fmt.Errorf("failed to encode host network request: %w", err)
	}

	tempFile, err := os.CreateTemp(UnifiSwitchRequestDir, ".teams-*.tmp")
	if err != nil {
		return fmt.Errorf("failed to create host network request in %s: %w", UnifiSwitchRequestDir, err)
	}
	tempPath := tempFile.Name()
	_, writeErr := tempFile.Write(data)
	closeErr := tempFile.Close()
	if writeErr != nil || closeErr != nil {
		os.Remove(tempPath)
		return fmt.Errorf("failed to write host network request: %v %v", writeErr, closeErr)
	}
	if err = os.Chmod(tempPath, 0644); err != nil {
		os.Remove(tempPath)
		return fmt.Errorf("failed to set permissions on host network request: %w", err)
	}
	if err = os.Rename(tempPath, filepath.Join(UnifiSwitchRequestDir, unifiSwitchRequestFile)); err != nil {
		os.Remove(tempPath)
		return fmt.Errorf("failed to submit host network request: %w", err)
	}
	return nil
}

// Waits for the helper's result for the given request. Results for other requests (for example, one left over
// from the previous match) are ignored.
func (sw *UnifiSwitch) waitForResult(id string) (*unifiSwitchResult, error) {
	resultPath := filepath.Join(UnifiSwitchResultDir, unifiSwitchResultFile)
	deadline := time.Now().Add(sw.resultTimeout)
	for {
		if data, err := os.ReadFile(resultPath); err == nil {
			var result unifiSwitchResult
			if json.Unmarshal(data, &result) == nil && result.Id == id {
				return &result, nil
			}
		}
		if time.Now().After(deadline) {
			return nil, fmt.Errorf(
				"host network helper did not answer within %v; check freezy-net.path and freezy-net.service on "+
					"the field server",
				sw.resultTimeout,
			)
		}
		time.Sleep(sw.resultPollInterval)
	}
}
