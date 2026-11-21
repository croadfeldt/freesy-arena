package web

import (
	"net/http"
	"testing"

	"github.com/Team254/cheesy-arena/websocket"
	gorillawebsocket "github.com/gorilla/websocket"
	"github.com/stretchr/testify/assert"
)

func TestBoardReportsMarkBoardsHealthy(t *testing.T) {
	web := setupTestWeb(t)
	web.arena.Esp32.SetHubBoardsExpected(true, true)
	web.arena.Esp32.SetScoreTableAddress("10.0.100.30")
	assert.Len(t, web.arena.Esp32.LostBoards(), 3)

	// A hub reports its counters over the PLC websocket.
	server, wsUrl := web.startTestServer()
	defer server.Close()
	conn, _, err := gorillawebsocket.DefaultDialer.Dial(wsUrl+"/api/plc/websocket", nil)
	assert.Nil(t, err)
	defer conn.Close()
	ws := websocket.NewTestWebsocket(conn)
	assert.Nil(t, ws.Write("setRegisters", []map[string]any{{"register": 3, "cValue": 16}, {"register": 1, "cValue": 51}}))
	readWebsocketTypeEventually(t, ws, "plcRegisterSetSuccess", 5)
	assert.True(t, web.arena.Esp32.IsRedHubHealthy())
	assert.False(t, web.arena.Esp32.IsBlueHubHealthy())

	// The other hub reports a sensor input.
	assert.Nil(t, ws.Write("setInput", []map[string]any{{"channel": 24, "state": true}}))
	readWebsocketTypeEventually(t, ws, "plcInputSetSuccess", 5)
	assert.True(t, web.arena.Esp32.IsBlueHubHealthy())

	// The score table posts its field E-stop state over HTTP.
	recorder := web.postHttpResponse("/api/freezy/eStopState", `[{"channel":0,"state":true}]`)
	assert.Equal(t, http.StatusOK, recorder.Code, recorder.Body.String())
	assert.Empty(t, web.arena.Esp32.LostBoards())
}
