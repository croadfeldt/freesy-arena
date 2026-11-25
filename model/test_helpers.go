// Copyright 2017 Team 254. All Rights Reserved.
// Author: pat@patfairbank.com (Patrick Fairbank)
//
// Helper methods for use in tests in this package and others.

package model

import (
	"github.com/Team254/cheesy-arena/game"
	"github.com/stretchr/testify/assert"
	"path/filepath"
	"testing"
	"time"
)

func SetupTestDb(t *testing.T) *Database {
	BaseDir = ".."
	dbDir := t.TempDir()
	dbPath := filepath.Join(dbDir, "test.db")
	database, err := OpenDatabase(dbPath)
	assert.Nil(t, err)
	t.Cleanup(
		func() {
			database.Close()
		},
	)
	return database
}

func BuildTestMatchResult(matchId int, playNumber int) *MatchResult {
	matchResult := &MatchResult{MatchId: matchId, PlayNumber: playNumber, MatchType: Qualification}
	matchResult.RedScore = game.TestScore1()
	matchResult.BlueScore = game.TestScore2()
	matchResult.RedCards = map[string]string{"1868": "yellow"}
	matchResult.BlueCards = map[string]string{}
	return matchResult
}

func BuildTestAlliances(database *Database) {
	database.CreateAlliance(&Alliance{Id: 2, TeamIds: []int{1718, 2451, 1619}, Lineup: [3]int{2451, 1718, 1619}})
	database.CreateAlliance(&Alliance{Id: 1, TeamIds: []int{254, 469, 2848, 74, 3175}, Lineup: [3]int{469, 254, 2848}})
}

// Puts at least one record in every table, for the tests that an older arena opens a newer database.
func FillEveryTable(t *testing.T, database *Database) {
	when := time.Unix(1700000000, 0)
	assert.Nil(t, database.CreateTeam(&Team{Id: 254, Name: "The Cheesy Poofs", Nickname: "Poofs"}))
	match := Match{Type: Qualification, ShortName: "Q1", LongName: "Qualification 1", TypeOrder: 1, Red1: 254}
	assert.Nil(t, database.CreateMatch(&match))
	assert.Nil(t, database.CreateMatchResult(BuildTestMatchResult(match.Id, 1)))
	assert.Nil(t, database.CreateAlliance(&Alliance{Id: 1, TeamIds: []int{254, 469, 2848}, Lineup: [3]int{469, 254, 2848}}))
	assert.Nil(t, database.CreateAward(&Award{AwardName: "Safety Award", TeamId: 254}))
	assert.Nil(t, database.CreateLowerThird(&LowerThird{TopText: "Top", BottomText: "Bottom"}))
	assert.Nil(t, database.CreateSponsorSlide(&SponsorSlide{Subtitle: "Sponsor", Line1: "Line"}))
	assert.Nil(t, database.CreateScheduleBlock(&ScheduleBlock{MatchType: Qualification, StartTime: when, NumMatches: 10}))
	assert.Nil(t, database.CreateScheduledBreak(&ScheduledBreak{MatchType: Qualification, TypeOrderBefore: 4, Time: when}))
	assert.Nil(t, database.CreateJudgingSlot(&JudgingSlot{Time: when, TeamId: 254, JudgeNumber: 1}))
	assert.Nil(t, database.CreateRanking(game.TestRanking1()))
	assert.Nil(t, database.CreateUserSession(&UserSession{Token: "token", Username: "admin", CreatedAt: when}))
	settings, err := database.GetEventSettings()
	if !assert.Nil(t, err) {
		return
	}
	settings.Name = "Newer Event"
	assert.Nil(t, database.UpdateEventSettings(settings))
}
