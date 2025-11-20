// Copyright 2014 Team 254. All Rights Reserved.
// Author: pat@patfairbank.com (Patrick Fairbank)
//
// Methods for configuring a Cisco Switch 3500-series switch for team VLANs.

package network

import (
	"bytes"
	"fmt"
	"github.com/Team254/cheesy-arena/model"
	"sync"
	"time"
	"encoding/json"
	"log"
	"os/exec"
)

const (
	// This are not used yet, but may in the future if we tap into the API vs ansible
	UnifiSwitchConfigBackoffDurationSec = 5
	UnifiSwitchConfigPauseDurationSec   = 2
	UnifiSwitchTeamGatewayAddress       = 4
	UnifiSwitchAPIPort					= 9999
)

// Don't need these for now, ansible has these defined in it already.
// const (
// 	red1Vlan  = 10
// 	red2Vlan  = 20
// 	red3Vlan  = 30
// 	blue1Vlan = 40
// 	blue2Vlan = 50
// 	blue3Vlan = 60
// )

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
		port:                  UnifiSwitchAPIPort,
		password:              password,
		configBackoffDuration: UnifiSwitchConfigBackoffDurationSec * time.Second,
		configPauseDuration:   UnifiSwitchConfigPauseDurationSec * time.Second,
		Status:                "UNKNOWN",
	}
}

// Sets up wired networks for the given set of teams.
// Helper function to run commands safely using os/exec
func (sw *Switch) runExecCommand(name string, args ...string) error {
	cmd := exec.Command(name, args...)
	
	// Optional: Attach stdout/stderr for debugging/logging
	// cmd.Stdout = os.Stdout
	// cmd.Stderr = os.Stderr

	fmt.Printf("Executing command: %s\n", cmd.Args) // Log the command

	if err := cmd.Run(); err != nil {
		// Log the error detail before returning it
		log.Printf("Command failed: %s %v\n", name, err)
		return fmt.Errorf("command execution failed: %w", err)
	}
	return nil
}

func (sw *Switch) UnifiConfigureTeamEthernet(teams []*model.Team) error {
	// Make sure multiple configurations aren't being set at the same time.
	sw.mutex.Lock()
	defer sw.mutex.Unlock()
	sw.Status = "CONFIGURING"

	// --- Step 1: Remove old team VLANs (cleaner command execution) ---
	// No need for a separate string variable for a simple command
	err := sw.runExecCommand("ansible-playbook", "create_vlans.yaml")
	if err != nil {
		sw.Status = "ERROR"
		return err
	}
	time.Sleep(sw.configPauseDuration)

	// --- Step 2: Create the new team VLANs (safe JSON and exec) ---

	// Prepare data structure for JSON marshaling
	type AnsibleVars struct {
		TeamNumbers []int `json:"team_numbers"` // Use int type for IDs, JSON handles conversion
	}

	var ids []int
	for _, team := range teams {
		if team != nil {
			ids = append(ids, team.Id)
		}
	}
	
	if len(ids) == 0 {
		log.Println("No team IDs provided; skipping 'config_dhcp.yaml' playbook.")
		sw.Status = "ACTIVE"
		return nil
	}

	vars := AnsibleVars{TeamNumbers: ids}
	
	// Safely marshal the Go struct into a JSON byte slice
	jsonData, err := json.Marshal(vars)
	if err != nil {
		sw.Status = "ERROR"
		return fmt.Errorf("failed to marshal JSON for ansible vars: %w", err)
	}

	// The -e argument needs the JSON string wrapped in single quotes for the shell to interpret it correctly
	extraVarsArg := fmt.Sprintf("'%s'", string(jsonData))

	// Execute the command safely
	err = sw.runExecCommand("ansible-playbook", "-e", extraVarsArg, "config_dhcp.yaml")
	if err != nil {
		sw.Status = "ERROR"
		return err
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
