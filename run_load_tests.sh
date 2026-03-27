#!/usr/bin/env bash
# run_load_tests.sh — Run Locust at 10, 50, 100 users and collect CSV results.
# Usage: bash run_load_tests.sh [HOST]
set -euo pipefail

HOST="${1:-http://44.203.138.45:8000}"
DURATION="60s"
SPAWN_RATE=10

mkdir -p results

for USERS in 10 50 100; do
  echo ""
  echo "============================================"
  echo "  Load test: ${USERS} users for ${DURATION}"
  echo "============================================"

  locust -f locustfile.py \
    --host "$HOST" \
    --users "$USERS" \
    --spawn-rate "$SPAWN_RATE" \
    --run-time "$DURATION" \
    --headless \
    --csv "results/load_${USERS}" \
    --csv-full-history

  echo "  -> Results saved to results/load_${USERS}_stats.csv"
done

echo ""
echo "All runs complete. CSVs in ./results/"
echo ""

# Print summary table from the stats CSVs
echo "| Users | Endpoint         | Reqs   | Fails | p50 (ms) | p95 (ms) | p99 (ms) | Avg (ms) | RPS   |"
echo "|-------|------------------|--------|-------|----------|----------|----------|----------|-------|"
for USERS in 10 50 100; do
  CSV="results/load_${USERS}_stats.csv"
  if [ -f "$CSV" ]; then
    # Read the "Aggregated" row (last data row)
    tail -1 "$CSV" | awk -F',' -v u="$USERS" '{
      printf "| %-5s | %-16s | %-6s | %-5s | %-8s | %-8s | %-8s | %-8s | %-5s |\n",
        u, "Aggregated", $3, $4, $7, $11, $12, $6, $10
    }'
  fi
done
