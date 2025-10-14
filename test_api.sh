#!/bin/bash
# Quick test script for BLE Mesh Bin API

API_URL="http://localhost:8000"

echo "========================================"
echo "BLE Mesh Bin API - Quick Test Script"
echo "========================================"
echo ""

# 1. Check server status
echo "1. Checking server status..."
curl -s $API_URL/api/v1/status | jq '.'
echo ""

# 2. Get root info
echo "2. Getting root info..."
curl -s $API_URL/ | jq '.'
echo ""

# 3. Simulate discovering a node
echo "3. Simulating node discovery (BIN-TEST001)..."
curl -s -X POST "$API_URL/api/v1/discover?bin_id=BIN-TEST001" | jq '.'
echo ""

# 4. Check status after discovery
echo "4. Checking status after discovery (cluster should rename)..."
curl -s $API_URL/api/v1/status | jq '.'
echo ""

# 5. Add another node
echo "5. Adding second node (BIN-TEST002)..."
curl -s -X POST "$API_URL/api/v1/discover?bin_id=BIN-TEST002" | jq '.'
echo ""

# 6. Check final status
echo "6. Final status check..."
curl -s $API_URL/api/v1/status | jq '.'
echo ""

# 7. Test hardware endpoints (mock)
echo "7. Testing hardware endpoints..."
echo "   - Occupancy:"
curl -s $API_URL/api/v1/occupancy | jq '.'
echo "   - Battery:"
curl -s $API_URL/api/v1/battery | jq '.'
echo "   - Temperature:"
curl -s $API_URL/api/v1/temperature | jq '.'
echo ""

# 8. Submit test telemetry
echo "8. Submitting test telemetry..."
curl -s -X POST $API_URL/api/v1/telemetry \
  -H "Content-Type: application/json" \
  -d '[{
    "bin_id": "BIN-CB9B8676",
    "timestamp": "2025-10-07T14:00:00Z",
    "fill_level": 0.45,
    "battery": 0.87,
    "signal_strength": -65,
    "temperature": 22.5,
    "is_master": true,
    "master_id": null,
    "location": "Office-4B"
  }]' | jq '.'
echo ""

# 9. Clean up - remove test nodes
echo "9. Cleaning up test nodes..."
curl -s -X DELETE "$API_URL/api/v1/discover/BIN-TEST001" | jq '.'
curl -s -X DELETE "$API_URL/api/v1/discover/BIN-TEST002" | jq '.'
echo ""

# 10. Final status (should be back to SOLO)
echo "10. Final status (should be SOLO again)..."
curl -s $API_URL/api/v1/status | jq '.'
echo ""

echo "========================================"
echo "Test complete!"
echo "View interactive docs at:"
echo "  - Swagger UI: $API_URL/docs"
echo "  - ReDoc:      $API_URL/redoc"
echo "========================================"
