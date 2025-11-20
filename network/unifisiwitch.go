// Copyright 2014 Team 254. All Rights Reserved.
// Author: pat@patfairbank.com (Patrick Fairbank)
//
// Methods for configuring a Cisco Switch 3500-series switch for team VLANs.

package network

import (
	"bufio"
	"bytes"
	"fmt"
	"github.com/Team254/cheesy-arena/model"
	"net"
	"sync"
	"time"
)

const (
	switchConfigBackoffDurationSec = 5
	switchConfigPauseDurationSec   = 2
	switchTeamGatewayAddress       = 4
	switchTelnetPort               = 23
)

const (
	red1Vlan  = 10
	red2Vlan  = 20
	red3Vlan  = 30
	blue1Vlan = 40
	blue2Vlan = 50
	blue3Vlan = 60
)

type UnifiSwitch struct {
	address               string
	port                  int
	password              string
	mutex                 sync.Mutex
	configBackoffDuration time.Duration
	configPauseDuration   time.Duration
	Status                string
}

var ServerIpAddress = "10.0.100.5" // The DS will try to connect to this address only.

func NewUnifiSwitch(address, password string) *Switch {
	return &Switch{
		address:               address,
		port:                  switchTelnetPort,
		password:              password,
		configBackoffDuration: switchConfigBackoffDurationSec * time.Second,
		configPauseDuration:   switchConfigPauseDurationSec * time.Second,
		Status:                "UNKNOWN",
	}
}

// Sets up wired networks for the given set of teams.
func (sw *Switch) UnifiConfigureTeamEthernet(teams [6]*model.Team) error {
	// Make sure multiple configurations aren't being set at the same time.
	sw.mutex.Lock()
	defer sw.mutex.Unlock()
	sw.Status = "CONFIGURING"

	// Remove old team VLANs to reset the switch state.
	removeTeamVlansCommand := "ansible-playbook create_vlans.yaml"

	_, err := sw.runCommand(removeTeamVlansCommand)
	if err != nil {
		sw.Status = "ERROR"
		return err
	}
	time.Sleep(sw.configPauseDuration)

	// Create the new team VLANs.
	addTeamVlansCommand := fmt.Sprintf("ansible-playbook -e'{\"team_numbers\": [\"%d\", \"%d\", \"%d\", \"%d\", \"\", \"%d\" ]}' config_dhcp.yaml",
		teams[0].Id,
		teams[1].Id,
		teams[2].Id,
		teams[3].Id,
		teams[4].Id,
		teams[5].Id
	)
	
	if len(addTeamVlansCommand) > 0 {
		_, err = sw.runLocalCommand(addTeamVlansCommand)
		if err != nil {
			sw.Status = "ERROR"
			return err
		}
	}

	// Give some time for the configuration to take before another one can be attempted.
	time.Sleep(sw.configBackoffDuration)

	sw.Status = "ACTIVE"
	return nil
}

// Logs into the switch via Telnet and runs the given command in user exec mode. Reads the output and
// returns it as a string.
func (sw *Switch) runLocalCommand(command string) (string, error) {
	// Pass the command string to the shell via the -c flag
	cmd := exec.Command("/bin/sh", "-c", commandStr)

	// Create buffers to capture stdout and stderr
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	output, err := cmd.CombinedOutput()
	if err != nil {
		log.Fatalf("command failed: %v\nOutput: %s", err, string(output))
	}

	fmt.Println("--- Command Output ---")
	fmt.Println(string(output))

	return string(output), nil
}
