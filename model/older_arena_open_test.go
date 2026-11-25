// Reads every table of a database. deploy/image/test_older_arena.sh copies this file into an older
// checkout of the arena and runs it there against a database this version wrote, so it uses only what
// the arena has had for years.

package model

import (
	"os"
	"testing"
)

func readEveryTable(t *testing.T, database *Database) {
	count := func(table string, records int, err error) {
		if err != nil {
			t.Errorf("reading the %s table: %v", table, err)
		} else if records == 0 {
			t.Errorf("the %s table read as empty", table)
		}
	}
	alliances, err := database.allianceTable.getAll()
	count("Alliance", len(alliances), err)
	awards, err := database.awardTable.getAll()
	count("Award", len(awards), err)
	settings, err := database.eventSettingsTable.getAll()
	count("EventSettings", len(settings), err)
	judgingSlots, err := database.judgingSlotTable.getAll()
	count("JudgingSlot", len(judgingSlots), err)
	lowerThirds, err := database.lowerThirdTable.getAll()
	count("LowerThird", len(lowerThirds), err)
	matches, err := database.matchTable.getAll()
	count("Match", len(matches), err)
	matchResults, err := database.matchResultTable.getAll()
	count("MatchResult", len(matchResults), err)
	rankings, err := database.rankingTable.getAll()
	count("Ranking", len(rankings), err)
	scheduleBlocks, err := database.scheduleBlockTable.getAll()
	count("ScheduleBlock", len(scheduleBlocks), err)
	scheduledBreaks, err := database.scheduledBreakTable.getAll()
	count("ScheduledBreak", len(scheduledBreaks), err)
	sponsorSlides, err := database.sponsorSlideTable.getAll()
	count("SponsorSlide", len(sponsorSlides), err)
	teams, err := database.teamTable.getAll()
	count("Team", len(teams), err)
	userSessions, err := database.userSessionTable.getAll()
	count("UserSession", len(userSessions), err)
}

// Opens the database at the path in FREEZY_DB_OPEN, written by another version of the arena.
func TestOpenDatabaseFromAnotherArena(t *testing.T) {
	path := os.Getenv("FREEZY_DB_OPEN")
	if path == "" {
		t.Skip("FREEZY_DB_OPEN is not set")
	}
	database, err := OpenDatabase(path)
	if err != nil {
		t.Fatalf("opening the database: %v", err)
	}
	defer database.Close()
	readEveryTable(t, database)
}
