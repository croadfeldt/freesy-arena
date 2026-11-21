// Copyright 2014 Team 254. All Rights Reserved.
// Author: pat@patfairbank.com (Patrick Fairbank)

package web

import (
	"bytes"
	"github.com/Team254/cheesy-arena/field"
	"github.com/Team254/cheesy-arena/game"
	"github.com/Team254/cheesy-arena/model"
	"github.com/Team254/cheesy-arena/tournament"
	"github.com/stretchr/testify/assert"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestSetupSettingsMarksSettingsThatNeedAnother(t *testing.T) {
	web := setupTestWeb(t)
	body := web.getHttpResponse("/setup/settings").Body.String()

	// The page greys these out, with the note, until the setting they need is on.
	assert.Contains(t, body, `id="sccSettings"`)
	assert.Contains(t, body, `id="sccNeedsNetwork"`)
	assert.Contains(t, body, `id="nexusAutoQueueSettings"`)
	assert.Contains(t, body, `id="nexusNeedsTba"`)
	// Greyed-out fields are not sent, so the page enables them again before saving.
	assert.Contains(t, body, `$(this).find(":input").prop("disabled", false)`)
	assert.Contains(t, body, "settings-save-bar")
	assert.NotContains(t, body, "alterntive")
}

func TestSetupSettings(t *testing.T) {
	web := setupTestWeb(t)

	// Check the default setting values.
	recorder := web.getHttpResponse("/setup/settings")
	assert.Equal(t, 200, recorder.Code)
	assert.Contains(t, recorder.Body.String(), "Untitled Event")
	assert.Contains(t, recorder.Body.String(), "8")
	assert.Contains(t, recorder.Body.String(), "transitionShiftDurationSec")
	assert.Contains(t, recorder.Body.String(), "shiftDurationSec")
	assert.Contains(t, recorder.Body.String(), "endgameDurationSec")
	assert.Contains(t, recorder.Body.String(), "placeholder=\"10.0.100.60\"")
	assert.NotContains(t, recorder.Body.String(), "tbaPublishingEnabled\"  checked")
	assert.Contains(t, recorder.Body.String(), "autoAudienceScoreSec")
	assert.Contains(t, recorder.Body.String(), "autoAudiencePlayoffDelaySec")
	assert.Contains(t, recorder.Body.String(), "autoAudienceBracketSec")
	assert.Contains(t, recorder.Body.String(), "autoAudienceLastMatchSec")
	assert.Contains(t, recorder.Body.String(), "audienceRankingsOption")
	assert.Contains(t, recorder.Body.String(), "Audience Rankings Display")

	// Change the settings and check the response.
	recorder = web.postHttpResponse(
		"/setup/settings",
		"name=Chezy Champs&code=CC&playoffType=single&numPlayoffAlliances=16&tbaPublishingEnabled=on&"+
			"tbaEventCode=2014cc&tbaSecretId=secretId&tbaSecret=tbasec&transitionShiftDurationSec=12&"+
			"shiftDurationSec=24&endgameDurationSec=32&ledControllerAddress=10.0.100.61&ledUniverseMode=two",
	)
	assert.Equal(t, 303, recorder.Code)
	assert.Equal(t, "/setup/settings#event", recorder.Header().Get("Location"))
	recorder = web.getHttpResponse("/setup/settings")
	assert.Contains(t, recorder.Body.String(), "Chezy Champs")
	assert.Contains(t, recorder.Body.String(), "16")
	assert.Contains(t, recorder.Body.String(), "tbaPublishingEnabled\"  checked")
	assert.Contains(t, recorder.Body.String(), "2014cc")
	assert.Contains(t, recorder.Body.String(), "secretId")
	assert.Contains(t, recorder.Body.String(), "tbasec")
	assert.Equal(t, 12, web.arena.EventSettings.TransitionShiftDurationSec)
	assert.Equal(t, 24, web.arena.EventSettings.ShiftDurationSec)
	assert.Equal(t, 32, web.arena.EventSettings.EndgameDurationSec)
	assert.Equal(t, "10.0.100.61", web.arena.EventSettings.LedControllerAddress)
	assert.Equal(t, "two", web.arena.EventSettings.LedUniverseMode)
	assert.Equal(t, 140, game.GetTeleopDurationSec())

	recorder = web.postHttpResponse("/setup/settings", "name=Field Tab Event&activeSettingsTab=field")
	assert.Equal(t, 303, recorder.Code)
	assert.Equal(t, "/setup/settings#field", recorder.Header().Get("Location"))
}

func TestSetupSettingsBlockedDuringMatch(t *testing.T) {
	web := setupTestWeb(t)
	web.arena.EventSettings.Name = "Original Event"
	web.arena.MatchState = field.AutoPeriod

	recorder := web.postHttpResponse("/setup/settings", "name=Changed Event&activeSettingsTab=field")

	assert.Equal(t, 200, recorder.Code)
	assert.Contains(
		t, recorder.Body.String(), "Settings cannot be changed while a match is in progress or is uncommitted.",
	)
	assert.Contains(t, recorder.Body.String(), "hash = \"#field\"")
	assert.Equal(t, "Original Event", web.arena.EventSettings.Name)
}

func TestSetupSettingsAllowedDuringTimeoutStates(t *testing.T) {
	for _, matchState := range []field.MatchState{field.TimeoutActive, field.PostTimeout} {
		web := setupTestWeb(t)
		web.arena.MatchState = matchState

		recorder := web.postHttpResponse("/setup/settings", "name=Changed Event")

		assert.Equal(t, 303, recorder.Code)
		assert.Equal(t, "Changed Event", web.arena.EventSettings.Name)
	}
}

func TestSettingsSaveAllowed(t *testing.T) {
	testCases := []struct {
		matchState field.MatchState
		allowed    bool
	}{
		{field.PreMatch, true},
		{field.StartMatch, false},
		{field.AutoPeriod, false},
		{field.PausePeriod, false},
		{field.TeleopPeriod, false},
		{field.PostMatch, false},
		{field.TimeoutActive, true},
		{field.PostTimeout, true},
	}

	for _, testCase := range testCases {
		assert.Equal(t, testCase.allowed, settingsSaveAllowed(testCase.matchState))
	}
}

func TestSetupSettingsDoubleElimination(t *testing.T) {
	web := setupTestWeb(t)

	recorder := web.postHttpResponse("/setup/settings", "playoffType=DoubleEliminationPlayoff&numPlayoffAlliances=4")
	assert.Equal(t, 303, recorder.Code)
	assert.Equal(t, model.DoubleEliminationPlayoff, web.arena.EventSettings.PlayoffType)
	assert.Equal(t, 4, web.arena.EventSettings.NumPlayoffAlliances)

	recorder = web.postHttpResponse("/setup/settings", "playoffType=DoubleEliminationPlayoff&numPlayoffAlliances=3")
	assert.Equal(t, 200, recorder.Code)
	assert.Contains(t, recorder.Body.String(), "Number of alliances for double elimination must be 4 to 8.")
	assert.Equal(t, 4, web.arena.EventSettings.NumPlayoffAlliances)
}

func TestSetupSettingsInvalidValues(t *testing.T) {
	web := setupTestWeb(t)
	recorder := web.postHttpResponse("/setup/settings", "playoffType=SingleEliminationPlayoff&numPlayoffAlliances=8")
	assert.Equal(t, 303, recorder.Code)

	// Invalid number of alliances.
	recorder = web.postHttpResponse("/setup/settings", "playoffType=SingleEliminationPlayoff&numAlliances=1")
	assert.Contains(t, recorder.Body.String(), "must be between 2 and 16")

	recorder = web.postHttpResponse("/setup/settings", "playoffType=DoubleEliminationPlayoff&numPlayoffAlliances=3")
	assert.Contains(t, recorder.Body.String(), "must be 4 to 8")

	// Changing the playoff type after alliance selection is finalized.
	assert.Nil(t, web.arena.Database.CreateAlliance(&model.Alliance{Id: 1}))
	recorder = web.postHttpResponse("/setup/settings", "playoffType=DoubleEliminationPlayoff")
	assert.Contains(t, recorder.Body.String(), "Cannot change playoff type or size after alliance selection")

	// Changing the playoff size after alliance selection is finalized.
	recorder = web.postHttpResponse("/setup/settings", "numPlayoffAlliances=2")
	assert.Contains(t, recorder.Body.String(), "Cannot change playoff type or size after alliance selection")
}

func TestSetupSettingsClearDb(t *testing.T) {
	createData := func(web *Web) {
		assert.Nil(t, web.arena.Database.CreateTeam(&model.Team{Id: 254}))
		assert.Nil(t, web.arena.Database.CreateMatch(&model.Match{Type: model.Practice}))
		assert.Nil(t, web.arena.Database.CreateMatch(&model.Match{Type: model.Qualification}))
		assert.Nil(t, web.arena.Database.CreateMatch(&model.Match{Type: model.Playoff}))
		assert.Nil(t, web.arena.Database.CreateMatchResult(&model.MatchResult{MatchId: 1, PlayNumber: 1}))
		assert.Nil(t, web.arena.Database.CreateMatchResult(&model.MatchResult{MatchId: 1, PlayNumber: 2}))
		assert.Nil(t, web.arena.Database.CreateMatchResult(&model.MatchResult{MatchId: 2, PlayNumber: 1}))
		assert.Nil(t, web.arena.Database.CreateMatchResult(&model.MatchResult{MatchId: 3, PlayNumber: 1}))
		assert.Nil(t, web.arena.Database.CreateRanking(&game.Ranking{TeamId: 254}))
		assert.Nil(t, web.arena.Database.CreateAlliance(&model.Alliance{Id: 1}))
		web.arena.AllianceSelectionAlliances = append(web.arena.AllianceSelectionAlliances, model.Alliance{Id: 1})
	}

	// Test clearing practice data.
	web := setupTestWeb(t)
	createData(web)
	recorder := web.postHttpResponse("/setup/db/clear/practice", "")
	assert.Equal(t, 303, recorder.Code)
	teams, _ := web.arena.Database.GetAllTeams()
	assert.NotEmpty(t, teams)
	matches, _ := web.arena.Database.GetMatchesByType(model.Practice, true)
	assert.Empty(t, matches)
	matchResult, _ := web.arena.Database.GetMatchResultForMatch(1)
	assert.Nil(t, matchResult)
	matches, _ = web.arena.Database.GetMatchesByType(model.Qualification, true)
	assert.NotEmpty(t, matches)
	matchResult, _ = web.arena.Database.GetMatchResultForMatch(2)
	assert.NotNil(t, matchResult)
	matches, _ = web.arena.Database.GetMatchesByType(model.Playoff, true)
	assert.NotEmpty(t, matches)
	matchResult, _ = web.arena.Database.GetMatchResultForMatch(3)
	assert.NotNil(t, matchResult)
	rankings, _ := web.arena.Database.GetAllRankings()
	assert.NotEmpty(t, rankings)
	tournament.CalculateRankings(web.arena.Database, false)
	assert.NotEmpty(t, rankings)
	alliances, _ := web.arena.Database.GetAllAlliances()
	assert.NotEmpty(t, alliances)
	assert.NotEmpty(t, web.arena.AllianceSelectionAlliances)

	// Test clearing qualification data.
	web = setupTestWeb(t)
	createData(web)
	recorder = web.postHttpResponse("/setup/db/clear/qualification", "")
	assert.Equal(t, 303, recorder.Code)
	teams, _ = web.arena.Database.GetAllTeams()
	assert.NotEmpty(t, teams)
	matches, _ = web.arena.Database.GetMatchesByType(model.Practice, true)
	assert.NotEmpty(t, matches)
	matchResult, _ = web.arena.Database.GetMatchResultForMatch(1)
	assert.NotNil(t, matchResult)
	matches, _ = web.arena.Database.GetMatchesByType(model.Qualification, true)
	assert.Empty(t, matches)
	matchResult, _ = web.arena.Database.GetMatchResultForMatch(2)
	assert.Nil(t, matchResult)
	matches, _ = web.arena.Database.GetMatchesByType(model.Playoff, true)
	assert.NotEmpty(t, matches)
	matchResult, _ = web.arena.Database.GetMatchResultForMatch(3)
	assert.NotNil(t, matchResult)
	rankings, _ = web.arena.Database.GetAllRankings()
	assert.Empty(t, rankings)
	tournament.CalculateRankings(web.arena.Database, false)
	assert.Empty(t, rankings)
	alliances, _ = web.arena.Database.GetAllAlliances()
	assert.NotEmpty(t, alliances)
	assert.NotEmpty(t, web.arena.AllianceSelectionAlliances)

	// Test clearing playoff data.
	web = setupTestWeb(t)
	createData(web)
	recorder = web.postHttpResponse("/setup/db/clear/playoff", "")
	assert.Equal(t, 303, recorder.Code)
	teams, _ = web.arena.Database.GetAllTeams()
	assert.NotEmpty(t, teams)
	matches, _ = web.arena.Database.GetMatchesByType(model.Practice, true)
	assert.NotEmpty(t, matches)
	matchResult, _ = web.arena.Database.GetMatchResultForMatch(1)
	assert.NotNil(t, matchResult)
	matches, _ = web.arena.Database.GetMatchesByType(model.Qualification, true)
	assert.NotEmpty(t, matches)
	matchResult, _ = web.arena.Database.GetMatchResultForMatch(2)
	assert.NotNil(t, matchResult)
	matches, _ = web.arena.Database.GetMatchesByType(model.Playoff, true)
	assert.Empty(t, matches)
	matchResult, _ = web.arena.Database.GetMatchResultForMatch(3)
	assert.Nil(t, matchResult)
	rankings, _ = web.arena.Database.GetAllRankings()
	assert.NotEmpty(t, rankings)
	tournament.CalculateRankings(web.arena.Database, false)
	assert.NotEmpty(t, rankings)
	alliances, _ = web.arena.Database.GetAllAlliances()
	assert.Empty(t, alliances)
	assert.Empty(t, web.arena.AllianceSelectionAlliances)

	// Test with invalid match types.
	recorder = web.postHttpResponse("/setup/db/clear/all", "")
	assert.Equal(t, 200, recorder.Code)
	assert.Contains(t, recorder.Body.String(), "Invalid tournament stage to clear")
	recorder = web.postHttpResponse("/setup/db/clear/test", "")
	assert.Equal(t, 200, recorder.Code)
	assert.Contains(t, recorder.Body.String(), "Invalid tournament stage to clear")
}

func TestSetupSettingsBackupRestoreDb(t *testing.T) {
	web := setupTestWeb(t)

	// Modify a parameter so that we know when the database has been restored.
	web.arena.EventSettings.Name = "Chezy Champs"
	assert.Nil(t, web.arena.Database.UpdateEventSettings(web.arena.EventSettings))

	// Back up the database.
	recorder := web.getHttpResponse("/setup/db/save")
	assert.Equal(t, 200, recorder.Code)
	assert.Equal(t, "application/octet-stream", recorder.HeaderMap["Content-Type"][0])
	backupBody := recorder.Body

	// Wipe the database to reset the defaults.
	web = setupTestWeb(t)
	assert.NotEqual(t, "Chezy Champs", web.arena.EventSettings.Name)

	// Check restoring with a missing file.
	recorder = web.postHttpResponse("/setup/db/restore", "")
	assert.Contains(t, recorder.Body.String(), "No database backup file was specified")
	assert.NotEqual(t, "Chezy Champs", web.arena.EventSettings.Name)

	// Check restoring with a corrupt file.
	recorder = web.postFileHttpResponse("/setup/db/restore", "databaseFile", bytes.NewBufferString("invalid"))
	assert.Contains(t, recorder.Body.String(), "Could not read uploaded database backup file")
	assert.NotEqual(t, "Chezy Champs", web.arena.EventSettings.Name)

	// Check restoring with the backup retrieved before.
	recorder = web.postFileHttpResponse("/setup/db/restore", "databaseFile", backupBody)
	assert.Equal(t, "Chezy Champs", web.arena.EventSettings.Name)
}

func TestSetupSettingsPublishToTba(t *testing.T) {
	web := setupTestWeb(t)

	tbaServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	defer tbaServer.Close()

	web.arena.TbaClient.BaseUrl = tbaServer.URL
	web.arena.EventSettings.TbaPublishingEnabled = true

	recorder := web.getHttpResponse("/setup/settings/publish_teams")
	assert.Equal(t, 303, recorder.Code)
	assert.Equal(t, "/setup/settings#publishing", recorder.Header().Get("Location"))

	web.arena.TbaClient.BaseUrl = "fakeurl"

	recorder = web.getHttpResponse("/setup/settings/publish_alliances")
	assert.Equal(t, 500, recorder.Code)
	assert.Contains(t, recorder.Body.String(), "Failed to publish alliances")
	assert.Contains(t, recorder.Body.String(), "hash = \"#publishing\"")

	recorder = web.getHttpResponse("/setup/settings/publish_awards")
	assert.Equal(t, 500, recorder.Code)
	assert.Contains(t, recorder.Body.String(), "Failed to publish awards")
	assert.Contains(t, recorder.Body.String(), "hash = \"#publishing\"")

	recorder = web.getHttpResponse("/setup/settings/publish_matches")
	assert.Equal(t, 500, recorder.Code)
	assert.Contains(t, recorder.Body.String(), "Failed to delete published matches")
	assert.Contains(t, recorder.Body.String(), "hash = \"#publishing\"")

	recorder = web.getHttpResponse("/setup/settings/publish_rankings")
	assert.Equal(t, 500, recorder.Code)
	assert.Contains(t, recorder.Body.String(), "Failed to publish rankings")
	assert.Contains(t, recorder.Body.String(), "hash = \"#publishing\"")

	recorder = web.getHttpResponse("/setup/settings/publish_teams")
	assert.Equal(t, 500, recorder.Code)
	assert.Contains(t, recorder.Body.String(), "Failed to publish teams")
	assert.Contains(t, recorder.Body.String(), "hash = \"#publishing\"")
}

func (web *Web) postFileHttpResponse(path string, paramName string, file *bytes.Buffer) *httptest.ResponseRecorder {
	body := new(bytes.Buffer)
	writer := multipart.NewWriter(body)
	part, _ := writer.CreateFormFile(paramName, "file.ext")
	io.Copy(part, file)
	writer.Close()
	recorder := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", path, body)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	web.newHandler().ServeHTTP(recorder, req)
	return recorder
}

func TestSetupSettingsAudienceOptions(t *testing.T) {
	web := setupTestWeb(t)

	recorder := web.postHttpResponse("/setup/settings",
		"activeSettingsTab=automation&autoAudienceDisplayEnabled=on&"+
			"autoAudienceScoreSec=25&autoAudiencePlayoffDelaySec=8&"+
			"autoAudienceBracketSec=35&autoAudienceLastMatchSec=60&"+
			"audienceScoreBottomOffsetPx=75&audienceRankingsOptionsPresent=1&"+
			"audienceRankingsOption=rp&audienceRankingsOption=nextMatch"+
			"&autoDurationSec=20&pauseDurationSec=3&transitionShiftDurationSec=10&shiftDurationSec=25&endgameDurationSec=30&energizedBonusThreshold=100&superchargedBonusThreshold=360&traversalBonusThreshold=50")
	assert.Equal(t, 303, recorder.Code)
	assert.Equal(t, "/setup/settings#automation", recorder.Header().Get("Location"))
	settings := web.arena.EventSettings
	assert.True(t, settings.AutoAudienceDisplayEnabled)
	assert.Equal(t, 25, settings.AudienceScoreSeconds())
	assert.Equal(t, 8, settings.AudiencePlayoffDelaySeconds())
	assert.Equal(t, 35, settings.AudienceBracketSeconds())
	assert.Equal(t, 60, settings.AudienceLastMatchSeconds())
	assert.Equal(t, "rp,nextMatch", settings.AudienceRankingsFields)

	stored, err := web.arena.Database.GetEventSettings()
	assert.NoError(t, err)
	assert.Equal(t, 75, stored.AudienceScoreBottomOffsetPx)
	assert.Equal(t, 25, stored.AutoAudienceScoreSec)
	assert.Equal(t, 35, stored.AutoAudienceBracketSec)
	assert.Equal(t, "rp,nextMatch", stored.AudienceRankingsFields)

	page := web.getHttpResponse("/setup/settings")
	assert.Equal(t, 200, page.Code)
	assert.Contains(t, page.Body.String(), "value=\"25\"")
	assert.Contains(t, page.Body.String(), "value=\"35\"")
	assert.Contains(t, page.Body.String(), "audienceStatNext")
}

func TestSetupSettingsAudienceTimerValidation(t *testing.T) {
	for _, bad := range []string{"0", "-1", "601", "bad", "1.5"} {
		web := setupTestWeb(t)
		recorder := web.postHttpResponse("/setup/settings",
			"activeSettingsTab=automation&autoAudienceScoreSec="+bad+
				"&audienceRankingsOptionsPresent=1&audienceRankingsOption=nextMatch")
		assert.Equal(t, 200, recorder.Code)
		assert.Contains(t, recorder.Body.String(), "between 1 and 600 seconds")
		assert.Equal(t, 20, web.arena.EventSettings.AudienceScoreSeconds())
		assert.Equal(t, "", web.arena.EventSettings.AudienceRankingsFields)
	}
}

func TestSetupSettingsAudienceOffsetValidation(t *testing.T) {
	for _, bad := range []string{"-1", "bad", "1.5", ""} {
		t.Run(bad, func(t *testing.T) {
			web := setupTestWeb(t)
			web.arena.EventSettings.AudienceScoreBottomOffsetPx = 75
			recorder := web.postHttpResponse("/setup/settings", "name=Changed&audienceScoreBottomOffsetPx="+bad)
			assert.Equal(t, 200, recorder.Code)
			assert.Contains(t, recorder.Body.String(), "nonnegative whole number")
			assert.Equal(t, 75, web.arena.EventSettings.AudienceScoreBottomOffsetPx)
			assert.Equal(t, "Untitled Event", web.arena.EventSettings.Name)
		})
	}
}

func TestSetupSettingsAudienceOffsetDefaultAndOmission(t *testing.T) {
	web := setupTestWeb(t)
	assert.Zero(t, web.arena.EventSettings.AudienceScoreBottomOffsetPx)
	web.arena.EventSettings.AudienceScoreBottomOffsetPx = 75
	recorder := web.postHttpResponse("/setup/settings", "name=Test")
	assert.Equal(t, 303, recorder.Code)
	assert.Equal(t, 75, web.arena.EventSettings.AudienceScoreBottomOffsetPx)
	recorder = web.postHttpResponse("/setup/settings", "audienceScoreBottomOffsetPx=0")
	assert.Equal(t, 303, recorder.Code)
	stored, err := web.arena.Database.GetEventSettings()
	assert.NoError(t, err)
	assert.Zero(t, stored.AudienceScoreBottomOffsetPx)
}

func TestSetupSettingsAudienceChromaColor(t *testing.T) {
	web := setupTestWeb(t)
	assert.False(t, web.arena.EventSettings.AudienceChromaOverrideEnabled)
	page := web.getHttpResponse("/setup/settings")
	assert.Contains(t, page.Body.String(), `value="#00ff00"`)
	recorder := web.postHttpResponse("/setup/settings",
		"audienceChromaOptionsPresent=1&audienceChromaOverrideEnabled=on&audienceChromaColor=%2312ABef")
	assert.Equal(t, 303, recorder.Code)
	stored, err := web.arena.Database.GetEventSettings()
	assert.NoError(t, err)
	assert.True(t, stored.AudienceChromaOverrideEnabled)
	assert.Equal(t, "#12abef", stored.AudienceChromaColor)
	page = web.getHttpResponse("/setup/settings")
	assert.Contains(t, page.Body.String(), `value="#12abef"`)

	// Older forms retain the override, while unchecking it explicitly disables it.
	recorder = web.postHttpResponse("/setup/settings", "name=Test")
	assert.Equal(t, 303, recorder.Code)
	assert.True(t, web.arena.EventSettings.AudienceChromaOverrideEnabled)
	assert.Equal(t, "#12abef", web.arena.EventSettings.AudienceChromaColor)
	recorder = web.postHttpResponse("/setup/settings",
		"audienceChromaOptionsPresent=1&audienceChromaColor=%2312abef")
	assert.Equal(t, 303, recorder.Code)
	stored, err = web.arena.Database.GetEventSettings()
	assert.NoError(t, err)
	assert.False(t, stored.AudienceChromaOverrideEnabled)
}

func TestSetupSettingsAudienceChromaValidation(t *testing.T) {
	for _, bad := range []string{"", "red", "%23fff", "%23gg0000", "%230000000", "%23-00001"} {
		t.Run(bad, func(t *testing.T) {
			web := setupTestWeb(t)
			recorder := web.postHttpResponse("/setup/settings",
				"name=Changed&audienceChromaOptionsPresent=1&audienceChromaColor="+bad)
			assert.Equal(t, 200, recorder.Code)
			assert.Contains(t, recorder.Body.String(), "six-digit hex color")
			assert.Equal(t, "Untitled Event", web.arena.EventSettings.Name)
			assert.Empty(t, web.arena.EventSettings.AudienceChromaColor)
		})
	}
}

func TestSetupSettingsAudienceCamera(t *testing.T) {
	web := setupTestWeb(t)
	assert.False(t, web.arena.EventSettings.AudienceCameraBehindHeadTable)
	for _, enabled := range []bool{true, false} {
		form := "audienceCameraOptionsPresent=1"
		if enabled {
			form += "&audienceCameraBehindHeadTable=on"
		}
		recorder := web.postHttpResponse("/setup/settings", form)
		assert.Equal(t, 303, recorder.Code)
		stored, err := web.arena.Database.GetEventSettings()
		assert.NoError(t, err)
		assert.Equal(t, enabled, stored.AudienceCameraBehindHeadTable)
		// An older form omitting the option must preserve the saved value.
		recorder = web.postHttpResponse("/setup/settings", "name=Test")
		assert.Equal(t, 303, recorder.Code)
		assert.Equal(t, enabled, web.arena.EventSettings.AudienceCameraBehindHeadTable)
	}
}
