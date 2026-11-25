// Writes the database that deploy/image/test_older_arena.sh hands to an older arena.

package field

import (
	"os"
	"testing"
	"time"

	"github.com/Team254/cheesy-arena/model"
	"github.com/stretchr/testify/require"
)

// Writes an event with a record in every table to the path in FREEZY_DB_WRITE. It is an event an arena
// can start on: alliances are selected, so the playoff matches exist too.
func TestWriteDatabaseForAnotherArena(t *testing.T) {
	path := os.Getenv("FREEZY_DB_WRITE")
	if path == "" {
		t.Skip("FREEZY_DB_WRITE is not set")
	}
	arena, err := NewArena(path)
	require.Nil(t, err)
	model.FillEveryTable(t, arena.Database)
	for id := 2; id <= arena.EventSettings.NumPlayoffAlliances; id++ {
		teams := []int{id * 100, id*100 + 1, id*100 + 2}
		require.Nil(t, arena.Database.CreateAlliance(&model.Alliance{Id: id, TeamIds: teams, Lineup: [3]int(teams)}))
	}
	require.Nil(t, arena.CreatePlayoffMatches(time.Unix(1700003600, 0)))
	require.Nil(t, arena.UpdatePlayoffTournament())
	require.Nil(t, arena.Database.Close())
}
