#!/bin/bash
# Test cluster naming and node discovery

BASE_URL="http://localhost:8000"

echo "=== Initial Status ==="
curl -s "$BASE_URL/api/v1/status" | python3 -m json.tool

echo -e "\n\n=== Adding BIN-ABC123 ==="
curl -s -X POST "$BASE_URL/api/v1/discover?bin_id=BIN-ABC123" | python3 -m json.tool

echo -e "\n\n=== Status After Adding 1 Node ==="
curl -s "$BASE_URL/api/v1/status" | python3 -m json.tool

echo -e "\n\n=== Adding BIN-DEF456 ==="
curl -s -X POST "$BASE_URL/api/v1/discover?bin_id=BIN-DEF456" | python3 -m json.tool

echo -e "\n\n=== Status After Adding 2 Nodes ==="
curl -s "$BASE_URL/api/v1/status" | python3 -m json.tool

echo -e "\n\n=== Renaming Cluster to 'Office-Floor-2' ==="
curl -s -X PUT "$BASE_URL/api/v1/cluster/rename?new_name=Office-Floor-2" | python3 -m json.tool

echo -e "\n\n=== Final Status ==="
curl -s "$BASE_URL/api/v1/status" | python3 -m json.tool

echo -e "\n\n=== Removing BIN-ABC123 ==="
curl -s -X DELETE "$BASE_URL/api/v1/discover/BIN-ABC123" | python3 -m json.tool

echo -e "\n\n=== Status After Removal ==="
curl -s "$BASE_URL/api/v1/status" | python3 -m json.tool
