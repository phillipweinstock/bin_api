# BLE Mesh Implementation Notes

## Overview
This document outlines the BLE mesh networking implementation required for the bin system. **Not yet implemented** - hardware pending.

---

## BLE Service Configuration

### Service UUID
```
Primary Service: 0000ffe0-0000-1000-8000-00805f9b34fb
Characteristic:  0000ffe1-0000-1000-8000-00805f9b34fb
```

### Characteristic Properties
- **Write Without Response**: For sending packets quickly
- **Notify**: For receiving async updates (commands from master)

### Advertisement Data
```python
{
    "Service UUID": "0000ffe0-0000-1000-8000-00805f9b34fb",
    "Local Name": "BIN-034",
    "Manufacturer Data": {
        "cluster": "OfficeA",
        "role": "child"  # or "master"
    }
}
```

---

## Message Schema

### Common Envelope
```json
{
  "type": "MESSAGE_TYPE",
  "src": "BIN-034",
  "dst": "BROADCAST or BIN-ID",
  "cluster": "OfficeA",
  "timestamp": 1696789200,
  "payload": { }
}
```

### Message Types

#### 1. HELLO (Discovery & Election)
```json
{
  "type": "HELLO",
  "src": "BIN-034",
  "dst": "BROADCAST",
  "cluster": "OfficeA",
  "timestamp": 1696789200,
  "payload": {
    "battery": 0.93,
    "rssi_to_ap": -68,
    "uptime": 12560,
    "is_candidate": true
  }
}
```

#### 2. ELECTION_RESULT
```json
{
  "type": "ELECTION_RESULT",
  "src": "BIN-001",
  "dst": "BROADCAST",
  "cluster": "OfficeA",
  "timestamp": 1696789300,
  "payload": {
    "new_master": "BIN-001",
    "score": 0.91,
    "members": ["BIN-001", "BIN-002", "BIN-003"]
  }
}
```

#### 3. TELEMETRY (Slave → Master)
```json
{
  "type": "TELEMETRY",
  "src": "BIN-034",
  "dst": "BIN-001",
  "cluster": "OfficeA",
  "timestamp": 1696789400,
  "payload": {
    "fill_level": 0.82,
    "battery": 0.93,
    "signal_strength": -65,
    "temperature": 22.1
  }
}
```

#### 4. COMMAND (Master → Slave)
```json
{
  "type": "COMMAND",
  "src": "BIN-001",
  "dst": "BIN-034",
  "cluster": "OfficeA",
  "timestamp": 1696789500,
  "payload": {
    "command_id": "CMD-5531",
    "action": "MOVE_TO_DOCK",
    "parameters": { "dock_id": "D2" }
  }
}
```

#### 5. ACK (Acknowledgement)
```json
{
  "type": "ACK",
  "src": "BIN-034",
  "dst": "BIN-001",
  "cluster": "OfficeA",
  "timestamp": 1696789550,
  "payload": {
    "command_id": "CMD-5531",
    "status": "done"
  }
}
```

---

## Implementation Guidelines

### BLE Constraints
- **MTU**: ≤ 180 bytes per message
- **Encoding**: UTF-8 JSON
- **Transport**: Write-without-response or Notify
- **Compression**: Optional (zlib/LZ4 if needed)

### Time Synchronization
- NTP sync every few hours
- Or cluster-wide time sync via master

---

## Example Python Implementation (Bleak)

### Sending JSON Messages
```python
import json
import asyncio
from bleak import BleakClient

BLE_CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"

async def send_json(client, message):
    """Send JSON message over BLE"""
    payload = json.dumps(message).encode("utf-8")
    await client.write_gatt_char(BLE_CHAR_UUID, payload, response=False)

async def main():
    message = {
        "type": "TELEMETRY",
        "src": "BIN-034",
        "dst": "BIN-001",
        "cluster": "OfficeA",
        "timestamp": 1696789400,
        "payload": {
            "fill_level": 0.82,
            "battery": 0.93
        }
    }
    
    async with BleakClient("AA:BB:CC:DD:EE:FF") as client:
        await send_json(client, message)

asyncio.run(main())
```

### Receiving Messages (Notify Handler)
```python
from bleak import BleakClient
import json

async def notification_handler(sender, data):
    """Handle incoming BLE notifications"""
    try:
        message = json.loads(data.decode("utf-8"))
        msg_type = message.get("type")
        
        if msg_type == "COMMAND":
            await handle_command(message)
        elif msg_type == "HELLO":
            await handle_hello(message)
        elif msg_type == "ELECTION_RESULT":
            await handle_election_result(message)
            
    except json.JSONDecodeError:
        print(f"Invalid JSON received: {data}")

async def handle_command(message):
    """Process incoming command"""
    payload = message["payload"]
    command_id = payload["command_id"]
    action = payload["action"]
    
    # Execute command based on action
    # ...
    
    # Send ACK
    ack_message = {
        "type": "ACK",
        "src": "BIN-034",
        "dst": message["src"],
        "cluster": message["cluster"],
        "timestamp": int(time.time()),
        "payload": {
            "command_id": command_id,
            "status": "done"
        }
    }
    # await send_json(client, ack_message)
```

---

## Election Algorithm

### Score Calculation
```python
def calculate_election_score(battery, rssi, uptime):
    """
    Calculate node's fitness score for master election.
    Higher score = better candidate
    """
    # Weights
    W_BATTERY = 0.5
    W_RSSI = 0.3
    W_UPTIME = 0.2
    
    # Normalize RSSI (-100 to -30 dBm)
    rssi_normalized = (rssi + 100) / 70  # 0-1 range
    
    # Normalize uptime (0 to 1 week in seconds)
    uptime_normalized = min(uptime / 604800, 1.0)
    
    score = (
        W_BATTERY * battery +
        W_RSSI * rssi_normalized +
        W_UPTIME * uptime_normalized
    )
    
    return score
```

### Election Process
1. **Discovery Phase** (30 seconds)
   - All nodes broadcast HELLO messages
   - Collect neighbor information

2. **Scoring Phase**
   - Each node calculates its own score
   - Nodes with battery < 20% mark `is_candidate: false`

3. **Election Phase**
   - Highest scoring candidate becomes master
   - Master broadcasts ELECTION_RESULT

4. **Confirmation Phase**
   - All nodes acknowledge new master
   - Update local state

### Re-election Triggers
- Master battery drops below 15%
- Master loses connectivity (no HELLO for 60s)
- Manual trigger via API
- Scheduled every 24 hours

---

## Multi-Cluster Design

### Cluster Partitioning
```
Cluster A (Floor 1)
  ├── BIN-001 (Master) - RSSI: -55
  ├── BIN-002 (Slave)  - RSSI: -60
  └── BIN-003 (Slave)  - RSSI: -58

Cluster B (Floor 2)
  ├── BIN-004 (Master) - RSSI: -52
  └── BIN-005 (Slave)  - RSSI: -65
```

### Cluster Merging
If nodes from different clusters detect each other:
1. Compare cluster sizes
2. Merge into larger cluster
3. Trigger re-election
4. Update cluster_id

---

## Implementation Checklist

### Phase 1: Basic BLE Communication
- [ ] Set up BLE GATT server with custom service UUID
- [ ] Implement JSON message sending/receiving
- [ ] Test message encoding/decoding
- [ ] Implement notification handlers

### Phase 2: Discovery & Mesh Formation
- [ ] Broadcast HELLO messages every 10s
- [ ] Scan for neighboring nodes
- [ ] Build neighbor table
- [ ] Implement cluster detection

### Phase 3: Master Election
- [ ] Implement score calculation
- [ ] Election coordinator logic
- [ ] Broadcast ELECTION_RESULT
- [ ] Handle election state changes

### Phase 4: Telemetry Aggregation
- [ ] Slaves send TELEMETRY to master
- [ ] Master aggregates data
- [ ] Master pushes to REST API `/api/v1/telemetry`

### Phase 5: Command Distribution
- [ ] Master polls `/api/v1/commands/{bin_id}`
- [ ] Master forwards COMMAND to slaves
- [ ] Slaves execute and send ACK
- [ ] Master confirms via `/api/v1/commands/ack`

### Phase 6: Fault Tolerance
- [ ] Heartbeat monitoring
- [ ] Auto re-election on master failure
- [ ] Message retry logic
- [ ] Network partition handling

---

## Testing Strategy

### Unit Tests
- Message serialization/deserialization
- Score calculation
- State transitions

### Integration Tests
- Two-node communication
- Three-node election
- Master failover scenario
- Command routing

### Stress Tests
- 10+ nodes in mesh
- High message throughput
- Network latency simulation
- Battery drain scenarios

---

## Dependencies

```bash
pip install bleak pybluez asyncio
```

For Raspberry Pi 5:
```bash
sudo apt-get update
sudo apt-get install -y bluetooth bluez libbluetooth-dev
sudo systemctl enable bluetooth
sudo systemctl start bluetooth
```

---

## Security Considerations (Future)

- [ ] Message signing (HMAC-SHA256)
- [ ] Replay attack prevention (nonce/sequence numbers)
- [ ] Node authentication (shared secret)
- [ ] Command authorization (role-based)

---

## Notes

- Keep this document updated as implementation progresses
- Test with physical hardware before deployment
- Monitor BLE mesh stability in production
- Consider fallback to WiFi if BLE fails
