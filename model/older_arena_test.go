// An older arena opens a database written by a newer one.
//
// The field server rolls back to the image it ran before, with the database the newer arena has been
// writing (deploy/image/DESIGN.md, "Updates and rollback"). There is no migration step: records are
// JSON in Bolt buckets, and that only works while a field the arena does not know is ignored.
//
// TestOlderArenaOpensNewerDatabase stands in for the older arena with this one, by adding what a newer
// arena could add. deploy/image/test_older_arena.sh does it with two real versions.

package model

import (
	"encoding/json"
	"testing"
	"time"

	"github.com/Team254/cheesy-arena/game"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.etcd.io/bbolt"
)

const newerField = "AddedByANewerArena"
const newerBucket = "TableOfANewerArena"

// Every bucket and the records in it, as stored.
func stored(t *testing.T, path string) map[string]map[string]map[string]any {
	bolt, err := bbolt.Open(path, 0644, &bbolt.Options{Timeout: time.Second})
	require.Nil(t, err)
	defer bolt.Close()
	buckets := map[string]map[string]map[string]any{}
	require.Nil(t, bolt.View(func(tx *bbolt.Tx) error {
		return tx.ForEach(func(name []byte, bucket *bbolt.Bucket) error {
			records := map[string]map[string]any{}
			buckets[string(name)] = records
			return bucket.ForEach(func(key, value []byte) error {
				record := map[string]any{}
				if err := json.Unmarshal(value, &record); err != nil {
					return err
				}
				records[string(key)] = record
				return nil
			})
		})
	}))
	return buckets
}

// What a newer arena could have done to the database: a field this arena does not know in every record,
// and a table it does not know.
func makeNewer(t *testing.T, path string) {
	bolt, err := bbolt.Open(path, 0644, &bbolt.Options{Timeout: time.Second})
	require.Nil(t, err)
	defer bolt.Close()
	require.Nil(t, bolt.Update(func(tx *bbolt.Tx) error {
		err := tx.ForEach(func(name []byte, bucket *bbolt.Bucket) error {
			changed := map[string][]byte{}
			err := bucket.ForEach(func(key, value []byte) error {
				record := map[string]any{}
				if err := json.Unmarshal(value, &record); err != nil {
					return err
				}
				record[newerField] = map[string]any{"Text": "new", "Numbers": []int{1, 2}}
				changed[string(key)], err = json.Marshal(record)
				return err
			})
			if err != nil {
				return err
			}
			for key, value := range changed {
				if err := bucket.Put([]byte(key), value); err != nil {
					return err
				}
			}
			return nil
		})
		if err != nil {
			return err
		}
		bucket, err := tx.CreateBucket([]byte(newerBucket))
		if err != nil {
			return err
		}
		return bucket.Put([]byte("1"), []byte(`{"Id":1,"Anything":"at all"}`))
	}))
}

func TestOlderArenaOpensNewerDatabase(t *testing.T) {
	database := SetupTestDb(t)
	FillEveryTable(t, database)
	require.Nil(t, database.Close())

	// A table added to the arena later must get a record in FillEveryTable, or it is not tested here.
	before := stored(t, database.Path)
	for name, records := range before {
		assert.NotEmpty(t, records, "FillEveryTable puts nothing in the %s table", name)
	}
	makeNewer(t, database.Path)

	database, err := OpenDatabase(database.Path)
	require.Nil(t, err)
	readEveryTable(t, database)

	// What this arena knows reads as it was written.
	team, err := database.GetTeamById(254)
	require.Nil(t, err)
	assert.Equal(t, "The Cheesy Poofs", team.Name)
	settings, err := database.GetEventSettings()
	require.Nil(t, err)
	assert.Equal(t, "Newer Event", settings.Name)
	result, err := database.GetMatchResultForMatch(1)
	require.Nil(t, err)
	assert.Equal(t, game.TestScore1(), result.RedScore)

	// A record this arena saves loses what it did not know. One it only reads keeps it. So going back
	// to the newer arena finds its own fields empty in the records the older one saved.
	team.Nickname = "Saved by the older arena"
	require.Nil(t, database.UpdateTeam(team))
	require.Nil(t, database.Close())
	after := stored(t, database.Path)
	for _, record := range after["Team"] {
		assert.NotContains(t, record, newerField)
	}
	for name, records := range after {
		if name == "Team" || name == newerBucket {
			continue
		}
		for key, record := range records {
			assert.Contains(t, record, newerField, "%s %s lost a field without being saved", name, key)
		}
	}
	// A table this arena does not know is left as it was.
	assert.Equal(t, map[string]map[string]any{"1": {"Id": float64(1), "Anything": "at all"}}, after[newerBucket])
}
