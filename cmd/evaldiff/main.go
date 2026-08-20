package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"sort"

	"github.com/redis/go-redis/v9"
)

func main() {
	redisAddr := flag.String("redis", "localhost:6379", "Redis address")
	currentDir := flag.String("current", "current", "directory containing current JSON runs")
	flag.Parse()

	files, err := filepath.Glob(filepath.Join(*currentDir, "*.json"))
	if err != nil || len(files) == 0 {
		fmt.Fprintf(os.Stderr, "no current run JSON found in %s\n", *currentDir)
		os.Exit(2)
	}
	sort.Strings(files)

	client := redis.NewClient(&redis.Options{Addr: *redisAddr})
	defer client.Close()
	ctx := context.Background()
	regressions := 0

	for _, file := range files {
		current := readJSONFile(file)
		scenarioID, ok := current["scenario_id"].(string)
		if !ok {
			fmt.Fprintf(os.Stderr, "%s has no scenario_id\n", file)
			os.Exit(2)
		}

		goldenJSON, err := client.Get(ctx, "golden:"+scenarioID).Result()
		if err != nil {
			fmt.Fprintf(os.Stderr, "golden %q: %v\n", scenarioID, err)
			os.Exit(2)
		}
		var golden map[string]any
		if err := json.Unmarshal([]byte(goldenJSON), &golden); err != nil {
			fmt.Fprintf(os.Stderr, "decode golden %q: %v\n", scenarioID, err)
			os.Exit(2)
		}

		differences := diff("$", golden, current)
		if len(differences) == 0 {
			fmt.Printf("PASS  %s\n", scenarioID)
			continue
		}
		regressions++
		fmt.Printf("FAIL  %s\n", scenarioID)
		for _, difference := range differences {
			fmt.Printf("  %s\n", difference)
		}
	}

	if regressions > 0 {
		fmt.Printf("\nAgent regression gate failed: %d scenario(s) changed\n", regressions)
		os.Exit(1)
	}
	fmt.Printf("\nAgent regression gate passed: %d scenario(s) match golden\n", len(files))
}

func readJSONFile(path string) map[string]any {
	data, err := os.ReadFile(path)
	if err != nil {
		fmt.Fprintf(os.Stderr, "read %s: %v\n", path, err)
		os.Exit(2)
	}
	var value map[string]any
	if err := json.Unmarshal(data, &value); err != nil {
		fmt.Fprintf(os.Stderr, "decode %s: %v\n", path, err)
		os.Exit(2)
	}
	return value
}

func diff(path string, golden, current any) []string {
	if reflect.DeepEqual(golden, current) {
		return nil
	}

	switch expected := golden.(type) {
	case map[string]any:
		actual, ok := current.(map[string]any)
		if !ok {
			return []string{changed(path, golden, current)}
		}
		keySet := make(map[string]bool, len(expected)+len(actual))
		for key := range expected {
			keySet[key] = true
		}
		for key := range actual {
			keySet[key] = true
		}
		keys := make([]string, 0, len(keySet))
		for key := range keySet {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		var differences []string
		for _, key := range keys {
			expectedValue, expectedExists := expected[key]
			actualValue, exists := actual[key]
			if !expectedExists {
				differences = append(differences, fmt.Sprintf("%s.%s: unexpected", path, key))
				continue
			}
			if !exists {
				differences = append(differences, fmt.Sprintf("%s.%s: missing", path, key))
				continue
			}
			differences = append(differences, diff(path+"."+key, expectedValue, actualValue)...)
		}
		return differences
	case []any:
		actual, ok := current.([]any)
		if !ok || len(expected) != len(actual) {
			return []string{changed(path, golden, current)}
		}
		var differences []string
		for index := range expected {
			childPath := fmt.Sprintf("%s[%d]", path, index)
			differences = append(differences, diff(childPath, expected[index], actual[index])...)
		}
		return differences
	default:
		return []string{changed(path, golden, current)}
	}
}

func changed(path string, golden, current any) string {
	goldenJSON, _ := json.Marshal(golden)
	currentJSON, _ := json.Marshal(current)
	return fmt.Sprintf("%s: golden=%s current=%s", path, goldenJSON, currentJSON)
}
