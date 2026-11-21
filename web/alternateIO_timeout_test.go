package web

import (
	"testing"
	"time"

	"github.com/Team254/cheesy-arena/websocket"
	gorillawebsocket "github.com/gorilla/websocket"
	"github.com/stretchr/testify/assert"
)

func TestPlcWebsocketClosesQuietBoards(t *testing.T) {
	defer func(timeout time.Duration) { plcBoardReadTimeout = timeout }(plcBoardReadTimeout)
	plcBoardReadTimeout = 300 * time.Millisecond
	web := setupTestWeb(t)
	server, wsUrl := web.startTestServer()
	defer server.Close()
	conn, _, err := gorillawebsocket.DefaultDialer.Dial(wsUrl+"/api/plc/websocket", nil)
	assert.Nil(t, err)
	defer conn.Close()
	ws := websocket.NewTestWebsocket(conn)

	// A board that only listens is never closed, however long it stays quiet.
	time.Sleep(3 * plcBoardReadTimeout)

	// A board that keeps reporting stays connected well past the timeout.
	for i := 0; i < 5; i++ {
		assert.Nil(t, ws.Write("setInput", []map[string]any{{"channel": 20, "state": true}}))
		readWebsocketTypeEventually(t, ws, "plcInputSetSuccess", 10)
		time.Sleep(150 * time.Millisecond)
	}

	// Once it goes quiet, the arena closes the connection: reads end with an error instead of waiting forever.
	start := time.Now()
	for {
		if _, _, err := ws.ReadWithTimeout(2 * time.Second); err != nil {
			break
		}
	}
	assert.Less(t, time.Since(start), 1500*time.Millisecond)
}
