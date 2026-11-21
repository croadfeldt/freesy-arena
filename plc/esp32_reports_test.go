package plc

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestBoardForInputAndRegister(t *testing.T) {
	for channel, want := range map[input]Board{
		fieldEStop: BoardScoreTable, red1EStop: BoardRedEstops, red3AStop: BoardRedEstops,
		blue1EStop: BoardBlueEstops, blue3AStop: BoardBlueEstops, redHubSensor1: BoardRedHub,
		redHubSensor4: BoardRedHub, blueHubSensor1: BoardBlueHub, blueHubSensor4: BoardBlueHub,
	} {
		board, ok := boardForInput(int(channel))
		assert.True(t, ok, channel.String())
		assert.Equal(t, want, board, channel.String())
	}
	for _, channel := range []input{redConnected1, ftaReady} {
		_, ok := boardForInput(int(channel))
		assert.False(t, ok, channel.String())
	}
	for index, want := range map[register]Board{
		redHubTotal: BoardRedHub, redHubCount1: BoardRedHub, redHubCount4: BoardRedHub,
		blueHubTotal: BoardBlueHub, blueHubCount1: BoardBlueHub, blueHubCount4: BoardBlueHub,
	} {
		board, ok := boardForRegister(int(index))
		assert.True(t, ok, index.String())
		assert.Equal(t, want, board, index.String())
	}
	_, ok := boardForRegister(int(fieldIoConnection))
	assert.False(t, ok)
}

func TestBoardGoesQuietAndComesBack(t *testing.T) {
	now := time.Date(2026, 11, 21, 14, 9, 0, 0, time.UTC)
	esp32 := new(Esp32IO)
	esp32.reports.now = func() time.Time { return now }

	// Nothing is expected, so nothing is lost.
	assert.Empty(t, esp32.LostBoards())

	// An expected hub that has never reported is lost, including right after the arena starts.
	esp32.SetHubBoardsExpected(true, false)
	assert.Equal(t, []Board{BoardRedHub}, esp32.LostBoards())
	assert.False(t, esp32.IsRedHubHealthy())

	esp32.ReportRegisters([]int{int(redHubCount1), int(redHubTotal)})
	assert.Empty(t, esp32.LostBoards())
	assert.True(t, esp32.IsRedHubHealthy())

	// Still fine just inside the timeout; lost once it passes, as in the capture where .46 went quiet.
	now = now.Add(BoardReportTimeout - time.Millisecond)
	assert.Empty(t, esp32.LostBoards())
	now = now.Add(time.Millisecond)
	assert.Equal(t, []Board{BoardRedHub}, esp32.LostBoards())
	assert.False(t, esp32.IsRedHubHealthy())

	// One report brings it back.
	esp32.ReportInputs([]int{int(redHubSensor2)})
	assert.Empty(t, esp32.LostBoards())
}

func TestStopBoardsAreExpectedWhenTheirAddressIsSet(t *testing.T) {
	now := time.Date(2026, 11, 21, 14, 9, 0, 0, time.UTC)
	esp32 := new(Esp32IO)
	esp32.reports.now = func() time.Time { return now }
	esp32.SetRedAllianceStationEstopAddress("10.0.100.21")
	assert.Equal(t, []Board{BoardRedEstops}, esp32.LostBoards())

	// The port 80 check alone no longer makes a stop board healthy; it must also be reporting.
	esp32.RedEstopsHealthy = true
	assert.False(t, esp32.IsRedEstopsHealthy())
	esp32.ReportInputs([]int{int(red2AStop)})
	assert.True(t, esp32.IsRedEstopsHealthy())
	assert.Empty(t, esp32.LostBoards())

	// A board on another channel range does not count for the red stops.
	now = now.Add(BoardReportTimeout)
	esp32.ReportInputs([]int{int(blue1EStop)})
	assert.Equal(t, []Board{BoardRedEstops}, esp32.LostBoards())
}
