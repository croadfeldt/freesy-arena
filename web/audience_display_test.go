// Copyright 2014 Team 254. All Rights Reserved.
// Author: pat@patfairbank.com (Patrick Fairbank)

package web

import (
	"github.com/Team254/cheesy-arena/game"
	"github.com/Team254/cheesy-arena/model"
	"github.com/Team254/cheesy-arena/websocket"
	gorillawebsocket "github.com/gorilla/websocket"
	"github.com/stretchr/testify/assert"
	"net/url"
	"strconv"
	"testing"
)

func TestAudienceDisplay(t *testing.T) {
	web := setupTestWeb(t)

	recorder := web.getHttpResponse("/displays/audience")
	assert.Equal(t, 302, recorder.Code)
	assert.Contains(t, recorder.Header().Get("Location"), "displayId=100")
	assert.Contains(t, recorder.Header().Get("Location"), "background=%230f0")
	assert.Contains(t, recorder.Header().Get("Location"), "reversed=false")
	assert.Contains(t, recorder.Header().Get("Location"), "overlayLocation=bottom")

	web.arena.EventSettings.AudienceScoreBottomOffsetPx = 75
	recorder = web.getHttpResponse(
		"/displays/audience?displayId=1&background=%23000&reversed=false&overlayLocation=top",
	)
	assert.Equal(t, 200, recorder.Code)
	assert.Contains(t, recorder.Body.String(), "Audience Display - Untitled Event - Cheesy Arena")
	assert.Contains(t, recorder.Body.String(), `data-bottom-offset-px="75"`)
	assert.Contains(t, recorder.Body.String(), "finalTiebreakReason")
	assert.Contains(t, recorder.Body.String(), "audienceInformation")
	assert.Contains(t, recorder.Body.String(), "audience_information.js")
}

func TestAudienceDisplayWebsocket(t *testing.T) {
	web := setupTestWeb(t)

	server, wsUrl := web.startTestServer()
	defer server.Close()
	conn, _, err := gorillawebsocket.DefaultDialer.Dial(wsUrl+"/displays/audience/websocket?displayId=1", nil)
	assert.Nil(t, err)
	defer conn.Close()
	ws := websocket.NewTestWebsocket(conn)

	// Should get a few status updates right after connection.
	readWebsocketType(t, ws, "displayConfiguration")
	readWebsocketType(t, ws, "matchTiming")
	readWebsocketType(t, ws, "audienceDisplayMode")
	readWebsocketType(t, ws, "matchLoad")
	readWebsocketType(t, ws, "matchTime")
	readWebsocketType(t, ws, "realtimeScore")
	readWebsocketType(t, ws, "scorePosted")
	readWebsocketType(t, ws, "allianceSelection")
	readWebsocketType(t, ws, "lowerThird")

	// Run through a match cycle.
	web.arena.MatchLoadNotifier.Notify()
	readWebsocketType(t, ws, "matchLoad")
	web.arena.AllianceStations["R1"].Bypass = true
	web.arena.AllianceStations["R2"].Bypass = true
	web.arena.AllianceStations["R3"].Bypass = true
	web.arena.AllianceStations["B1"].Bypass = true
	web.arena.AllianceStations["B2"].Bypass = true
	web.arena.AllianceStations["B3"].Bypass = true
	web.arena.StartMatch()
	web.arena.Update()
	web.arena.Update()
	messages := readWebsocketMultiple(t, ws, 4)
	screen, ok := messages["audienceDisplayMode"]
	if assert.True(t, ok) {
		assert.Equal(t, "match", screen)
	}
	sound, ok := messages["playSound"]
	if assert.True(t, ok) {
		assert.Equal(t, "start", sound)
	}
	_, ok = messages["matchTime"]
	assert.True(t, ok)
	_, ok = messages["realtimeScore"]
	assert.True(t, ok)
	web.arena.RealtimeScoreNotifier.Notify()
	readWebsocketType(t, ws, "realtimeScore")
	web.arena.SavedMatch = &model.Match{
		Status:              game.RedWonMatch,
		UseTiebreakCriteria: true,
	}
	web.arena.SavedMatchResult = &model.MatchResult{
		RedScore: &game.Score{},
		BlueScore: &game.Score{
			AutoTowerStatuses: [3]game.TowerStatus{game.TowerLevel1},
			Fouls:             []game.Foul{{FoulId: 1, IsMajor: true}},
		},
		RedCards:  map[string]string{},
		BlueCards: map[string]string{},
	}
	web.arena.ScorePostedNotifier.Notify()
	scorePosted := readWebsocketType(t, ws, "scorePosted").(map[string]any)
	assert.Equal(t, "TIEBREAK: MAJOR FOULS", scorePosted["TiebreakReason"])
	for _, threshold := range []int{0, 50, 0, 42} {
		web.arena.EventSettings.TraversalBonusThreshold = threshold
		web.arena.ScorePostedNotifier.Notify()
		scorePosted = readWebsocketType(t, ws, "scorePosted").(map[string]any)
		assert.Equal(t, threshold != 0, scorePosted["TraversalBonusEnabled"])
	}

	// Test other overlays.
	web.arena.AllianceSelectionNotifier.Notify()
	readWebsocketType(t, ws, "allianceSelection")
	web.arena.LowerThirdNotifier.Notify()
	readWebsocketType(t, ws, "lowerThird")
}

func TestAudienceDisplayChromaOverride(t *testing.T) {
	web := setupTestWeb(t)
	web.arena.EventSettings.AudienceChromaColor = "#123456"
	url := "/displays/audience?displayId=1&background=%230f0&reversed=false&overlayLocation=bottom"
	page := web.getHttpResponse(url)
	assert.Equal(t, 200, page.Code)
	assert.NotContains(t, page.Body.String(), "data-chroma-color")
	web.arena.EventSettings.AudienceChromaOverrideEnabled = true
	page = web.getHttpResponse(url)
	assert.Equal(t, 200, page.Code)
	assert.Contains(t, page.Body.String(), `data-chroma-color="#123456"`)
}

func TestAudienceDisplayCameraOrientation(t *testing.T) {
	for _, enabled := range []bool{false, true} {
		for _, override := range []string{"", "false", "true"} {
			name := strconv.FormatBool(enabled) + "/" + override
			t.Run(name, func(t *testing.T) {
				web := setupTestWeb(t)
				web.arena.EventSettings.AudienceCameraBehindHeadTable = enabled
				path := "/displays/audience"
				expected := strconv.FormatBool(enabled)
				if override != "" {
					path += "?reversed=" + override
					expected = override
				}
				page := web.getHttpResponse(path)
				assert.Equal(t, 302, page.Code)
				location, err := url.Parse(page.Header().Get("Location"))
				assert.NoError(t, err)
				assert.Equal(t, expected, location.Query().Get("reversed"))
				page = web.getHttpResponse(location.String())
				assert.Equal(t, 200, page.Code)
				assert.NotContains(t, page.Body.String(), "data-camera-behind-head-table")
			})
		}
	}
}
