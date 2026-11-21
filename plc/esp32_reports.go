// Tracks when each ESP32 board last reported, so a board that goes quiet raises a warning instead of leaving
// its last values in place.

package plc

import (
	"log"
	"sync"
	"time"
)

// Board is one of the ESP32 boards that report over the PLC websocket.
type Board int

const (
	BoardScoreTable Board = iota
	BoardRedEstops
	BoardBlueEstops
	BoardRedHub
	BoardBlueHub
	boardCount
)

// A board that sends nothing for this long counts as lost. Stop boards report every 100 ms and hubs every 500 ms.
const BoardReportTimeout = 2 * time.Second

var boardNames = [boardCount]string{"score table", "red alliance stops", "blue alliance stops", "red hub", "blue hub"}

func (board Board) String() string {
	return boardNames[board]
}

// boardReports records the last report time of each board.
type boardReports struct {
	mutex    sync.Mutex
	last     [boardCount]time.Time
	lost     [boardCount]bool
	expected [boardCount]bool
	now      func() time.Time
}

// Which board writes a given PLC input.
func boardForInput(channel int) (Board, bool) {
	switch {
	case channel == int(fieldEStop):
		return BoardScoreTable, true
	case channel >= int(red1EStop) && channel <= int(red3AStop):
		return BoardRedEstops, true
	case channel >= int(blue1EStop) && channel <= int(blue3AStop):
		return BoardBlueEstops, true
	case channel >= int(redHubSensor1) && channel <= int(redHubSensor4):
		return BoardRedHub, true
	case channel >= int(blueHubSensor1) && channel <= int(blueHubSensor4):
		return BoardBlueHub, true
	}
	return 0, false
}

// Which board writes a given PLC register.
func boardForRegister(index int) (Board, bool) {
	switch {
	case index == int(redHubTotal) || (index >= int(redHubCount1) && index <= int(redHubCount4)):
		return BoardRedHub, true
	case index == int(blueHubTotal) || (index >= int(blueHubCount1) && index <= int(blueHubCount4)):
		return BoardBlueHub, true
	}
	return 0, false
}

func (reports *boardReports) clock() time.Time {
	if reports.now != nil {
		return reports.now()
	}
	return time.Now()
}

func (reports *boardReports) record(board Board) {
	reports.mutex.Lock()
	defer reports.mutex.Unlock()
	reports.last[board] = reports.clock()
	if reports.lost[board] {
		reports.lost[board] = false
		log.Printf("ESP32 board %q is reporting again.", board)
	}
}

func (reports *boardReports) setExpected(board Board, expected bool) {
	reports.mutex.Lock()
	defer reports.mutex.Unlock()
	reports.expected[board] = expected
}

func (reports *boardReports) isReporting(board Board) bool {
	reports.mutex.Lock()
	defer reports.mutex.Unlock()
	return reports.reportingLocked(board)
}

func (reports *boardReports) reportingLocked(board Board) bool {
	return !reports.last[board].IsZero() && reports.clock().Sub(reports.last[board]) < BoardReportTimeout
}

// Returns the expected boards that have not reported within the timeout, and logs each one once when it goes quiet.
func (reports *boardReports) lostBoards() []Board {
	reports.mutex.Lock()
	defer reports.mutex.Unlock()
	var lost []Board
	for board := Board(0); board < boardCount; board++ {
		if !reports.expected[board] || reports.reportingLocked(board) {
			continue
		}
		lost = append(lost, board)
		if !reports.lost[board] {
			reports.lost[board] = true
			if reports.last[board].IsZero() {
				log.Printf("ESP32 board %q has not reported since the arena started.", board)
			} else {
				log.Printf("ESP32 board %q stopped reporting at %s.", board, reports.last[board].Format("15:04:05.000"))
			}
		}
	}
	return lost
}
