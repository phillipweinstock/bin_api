# Cluster Naming & Node ID System

## Overview
The BLE Mesh Bin system now features **automatic cluster naming** and **deterministic unique node IDs**.

---

## Node ID Generation

### Format
```
BIN-{HARDWARE_ID}
```

Example: `BIN-CB9B8676`

### Hardware ID Sources (in priority order)
1. **Raspberry Pi Serial Number** - Last 8 characters from `/proc/cpuinfo`
2. **MAC Address** - Last 6 characters (without colons)
3. **Fallback UUID** - Generated and saved to `/tmp/bin_hardware_id`

### Characteristics
- ✅ **Deterministic**: Same device = Same ID
- ✅ **Unique**: Each device gets a different ID
- ✅ **Persistent**: Survives reboots (on RPi)
- ✅ **Automatic**: No manual configuration needed

---

## Cluster Naming

### Auto-Generated Names

#### Solo Node (No Cluster)
```
Format: SOLO-{FIRST_4_CHARS}
Example: SOLO-CB9B
```

#### Multi-Node Cluster
```
Format: CLUSTER-{HASH}
Algorithm: MD5 hash of combined bin IDs (first 2 chars each, sorted)
Example: CLUSTER-A7F2
```

**Generation Logic:**
```python
# Example with 3 nodes
bin_ids = ["BIN-ABC123", "BIN-DEF456", "BIN-GHI789"]
sorted_ids = sorted(bin_ids)  # Sort for deterministic order
combined = "ABDEGH"  # First 2 chars of each
hash = md5(combined)[:4].upper()  # "A7F2"
cluster_id = f"CLUSTER-{hash}"  # "CLUSTER-A7F2"
```

### Properties
- ✅ **Deterministic**: Same members = Same name (regardless of join order)
- ✅ **Unique**: Different member combinations = Different names
- ✅ **Dynamic**: Auto-updates when nodes join/leave
- ✅ **Renamable**: Can be manually overridden via API

---

## API Endpoints

### Check Status
```bash
GET /api/v1/status
```

**Response:**
```json
{
  "bin_id": "BIN-CB9B8676",
  "is_master": true,
  "cluster_id": "SOLO-CB9B",
  "master_id": null,
  "slaves": [],
  "last_election": "2025-10-07T14:30:00Z"
}
```

### Discover Node (Testing)
```bash
POST /api/v1/discover?bin_id=BIN-ABC123
```

**Response:**
```json
{
  "status": "registered",
  "bin_id": "BIN-ABC123",
  "cluster_id": "CLUSTER-A7F2",
  "is_master": true,
  "total_nodes": 2,
  "all_members": ["BIN-ABC123", "BIN-CB9B8676"]
}
```

**What happens:**
1. Node is added to discovered nodes
2. Cluster ID is regenerated based on all members
3. If this node is master, the new node is added as slave

### Remove Node (Testing)
```bash
DELETE /api/v1/discover/BIN-ABC123
```

**Response:**
```json
{
  "status": "unregistered",
  "bin_id": "BIN-ABC123",
  "cluster_id": "SOLO-CB9B",
  "remaining_nodes": 0,
  "all_members": ["BIN-CB9B8676"]
}
```

**What happens:**
1. Node is removed from cluster
2. Cluster ID is regenerated (back to SOLO if alone)
3. If no nodes remain, this node becomes master

### Rename Cluster
```bash
PUT /api/v1/cluster/rename?new_name=Office-Floor-2
```

**Response:**
```json
{
  "status": "renamed",
  "old_cluster_id": "CLUSTER-A7F2",
  "new_cluster_id": "Office-Floor-2",
  "members": ["BIN-ABC123", "BIN-CB9B8676", "BIN-DEF456"]
}
```

**Use Cases:**
- Human-readable names for physical locations
- Organizational naming schemes
- Testing and debugging

---

## Automatic Cluster Updates

### When Cluster ID Changes
- ✅ Node joins cluster
- ✅ Node leaves cluster
- ✅ Stale nodes timeout (60s)
- ✅ Manual rename via API

### Console Output Example
```
Cluster renamed: SOLO-CB9B → CLUSTER-A7F2
Members: BIN-ABC123, BIN-CB9B8676

Removing stale node: BIN-DEF456
Cluster renamed: CLUSTER-A7F2 → CLUSTER-B3E1
Members: BIN-ABC123, BIN-CB9B8676
```

---

## BLE Mesh Integration (Future)

When BLE mesh is implemented:

### Discovery Process
1. **Broadcast HELLO** with bin_id every 10s
2. **Receive HELLO** from other nodes
3. **Update discovered_nodes** with timestamp
4. **Regenerate cluster_id** based on all discovered nodes
5. **Trigger election** if cluster membership changed

### HELLO Message Format
```json
{
  "type": "HELLO",
  "src": "BIN-CB9B8676",
  "dst": "BROADCAST",
  "cluster": "CLUSTER-A7F2",
  "timestamp": 1696789200,
  "payload": {
    "battery": 0.93,
    "rssi_to_ap": -68,
    "uptime": 12560,
    "is_candidate": true
  }
}
```

### Cluster Synchronization
- All nodes independently calculate same cluster_id
- Master broadcasts official cluster_id in ELECTION_RESULT
- Slaves adopt master's cluster_id if different

---

## Testing

### Run Test Script
```bash
./test_cluster.sh
```

This will:
1. Check initial solo status
2. Add nodes and watch cluster ID change
3. Rename cluster manually
4. Remove nodes and watch cluster ID update

### Manual Testing with curl
```bash
# Check current status
curl http://localhost:8000/api/v1/status

# Add a node
curl -X POST "http://localhost:8000/api/v1/discover?bin_id=BIN-TEST01"

# Rename cluster
curl -X PUT "http://localhost:8000/api/v1/cluster/rename?new_name=Lab-A"

# Remove node
curl -X DELETE "http://localhost:8000/api/v1/discover/BIN-TEST01"
```

---

## Implementation Notes

### Why MD5 for Cluster Hash?
- Fast computation
- Consistent 4-character output
- Not used for security, just deterministic naming
- Collision probability very low for small clusters

### Why First 2 Characters of Each Bin ID?
- Balance between uniqueness and brevity
- Sufficient entropy for small-medium clusters
- Keeps cluster names short

### Why Allow Manual Renaming?
- Production deployments need meaningful names
- Easier monitoring and debugging
- Organizational requirements
- Can always revert to auto-generated if needed

---

## Example Cluster Evolution

```
# Start: Solo node
BIN-CB9B8676  →  SOLO-CB9B

# Add BIN-ABC123
[BIN-ABC123, BIN-CB9B8676]  →  CLUSTER-A7F2

# Add BIN-DEF456
[BIN-ABC123, BIN-CB9B8676, BIN-DEF456]  →  CLUSTER-B3E1

# Rename manually
CLUSTER-B3E1  →  Office-Floor-2

# BIN-ABC123 goes offline (timeout)
[BIN-CB9B8676, BIN-DEF456]  →  Office-Floor-2  (keeps manual name)

# All others leave
BIN-CB9B8676  →  SOLO-CB9B  (reverts to solo)
```

---

## Summary

✅ **Deterministic bin IDs** - Hardware-based, unique per device  
✅ **Automatic cluster naming** - Based on member composition  
✅ **Dynamic updates** - Cluster name adjusts as members join/leave  
✅ **Manual override** - Can rename clusters for production use  
✅ **Transparent to REST API** - Backend doesn't need to know about topology changes  
✅ **Ready for BLE mesh** - Architecture supports distributed discovery  

The system is **self-organizing** and **self-naming** with minimal configuration! 🎉
