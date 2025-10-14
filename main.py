from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime
import asyncio
import time
import hashlib
import uuid
import os

app = FastAPI(
    title="BLE Mesh Bin API",
    version="1.0.0",
    description="REST API for BLE Mesh IoT Bin System"
)

# ============================================================================
# UNIQUE ID GENERATION
# ============================================================================

def get_hardware_id():
    """
    Generate a deterministic unique ID based on hardware.
    
    Priority:
    1. Raspberry Pi serial number (from /proc/cpuinfo)
    2. MAC address of first network interface
    3. Fallback to generated UUID (saved to file)
    """
    # Try to get RPi serial number
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('Serial'):
                    serial = line.split(':')[1].strip()
                    if serial and serial != '0000000000000000':
                        return serial[-8:]  # Last 8 chars
    except:
        pass
    
    # Try to get MAC address
    try:
        mac = ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff)
                       for elements in range(0,2*6,2)][::-1])
        if mac != '00:00:00:00:00:00':
            # Use last 6 chars of MAC (without colons)
            return mac.replace(':', '')[-6:]
    except:
        pass
    
    # Fallback: generate and save UUID
    id_file = '/tmp/bin_hardware_id'
    if os.path.exists(id_file):
        with open(id_file, 'r') as f:
            return f.read().strip()
    else:
        generated_id = str(uuid.uuid4())[:6].upper()
        with open(id_file, 'w') as f:
            f.write(generated_id)
        return generated_id


def generate_bin_id():
    """Generate deterministic BIN-XXXXXX format ID"""
    hw_id = get_hardware_id()
    return f"BIN-{hw_id.upper()}"


def generate_cluster_id(bin_ids: List[str]):
    """
    Generate cluster ID based on member bin IDs.
    Takes first 2 chars of each bin's hardware ID and hashes them.
    
    Example: BIN-ABC123, BIN-DEF456 -> CLUSTER-A7F2
    """
    if not bin_ids:
        # Solo node - use own ID
        hw_id = get_hardware_id()
        return f"SOLO-{hw_id[:4].upper()}"
    
    # Sort for deterministic ordering
    sorted_ids = sorted(bin_ids)
    
    # Combine the hardware parts
    combined = ''.join([bid.split('-')[1][:2] for bid in sorted_ids])
    
    # Hash to get 4-char cluster ID
    hash_obj = hashlib.md5(combined.encode())
    cluster_hash = hash_obj.hexdigest()[:4].upper()
    
    return f"CLUSTER-{cluster_hash}"


# ============================================================================
# STATE MANAGEMENT
# ============================================================================

# Generate unique bin ID for this unit
BIN_ID = generate_bin_id()

# Master/Slave state
node_state = {
    "bin_id": BIN_ID,
    "is_master": True,  # Default to master if no other units detected
    "cluster_id": generate_cluster_id([]),  # Solo cluster initially
    "master_id": None,  # ID of current master (if slave)
    "slaves": [],  # List of slave bin_ids (if master)
    "last_election": None,
    "discovered_nodes": {},  # {bin_id: last_seen_timestamp}
}

# Discovery settings
DISCOVERY_TIMEOUT = 30  # seconds - if no nodes found, remain master
HEARTBEAT_TIMEOUT = 60  # seconds - if no heartbeat, node is considered offline

# Command queue: {bin_id: [commands]}
command_queue: Dict[str, List[dict]] = {}

# Telemetry buffer (in-memory for now)
telemetry_buffer: List[dict] = []

# Election history
election_history: List[dict] = []


# ============================================================================
# DISCOVERY & ELECTION LOGIC
# ============================================================================

def update_cluster_id():
    """
    Regenerate cluster ID based on current members.
    Called when nodes join/leave the cluster.
    """
    all_members = [node_state["bin_id"]] + list(node_state["discovered_nodes"].keys())
    new_cluster_id = generate_cluster_id(all_members)
    
    if new_cluster_id != node_state["cluster_id"]:
        old_cluster_id = node_state["cluster_id"]
        node_state["cluster_id"] = new_cluster_id
        print(f"Cluster renamed: {old_cluster_id} → {new_cluster_id}")
        print(f"Members: {', '.join(sorted(all_members))}")
    
    return new_cluster_id


async def check_for_other_nodes():
    """
    Check for other nodes in the cluster.
    If no nodes detected after DISCOVERY_TIMEOUT, become master.
    
    TODO: This will be replaced with BLE mesh discovery
    For now, it's a placeholder that maintains master status.
    """
    # Simulate discovery period
    await asyncio.sleep(DISCOVERY_TIMEOUT)
    
    # Clean up stale nodes
    current_time = time.time()
    stale_nodes = [
        bin_id for bin_id, last_seen in node_state["discovered_nodes"].items()
        if current_time - last_seen > HEARTBEAT_TIMEOUT
    ]
    
    for bin_id in stale_nodes:
        print(f"Removing stale node: {bin_id}")
        del node_state["discovered_nodes"][bin_id]
        if bin_id in node_state["slaves"]:
            node_state["slaves"].remove(bin_id)
    
    # Update cluster ID if members changed
    if stale_nodes:
        update_cluster_id()
    
    # If no other nodes discovered, remain/become master
    if len(node_state["discovered_nodes"]) == 0:
        if not node_state["is_master"]:
            print(f"No other nodes detected. {node_state['bin_id']} becoming master.")
            node_state["is_master"] = True
            node_state["master_id"] = None
            node_state["last_election"] = datetime.utcnow()


async def periodic_discovery():
    """
    Periodically check for nodes and clean up stale entries.
    Runs in background.
    """
    while True:
        await check_for_other_nodes()
        await asyncio.sleep(30)  # Check every 30 seconds


@app.on_event("startup")
async def startup_event():
    """
    On startup, check for other nodes.
    If none found, become master.
    """
    print(f"Starting {node_state['bin_id']}...")
    print(f"Cluster: {node_state['cluster_id']}")
    
    # Start discovery in background
    asyncio.create_task(periodic_discovery())
    
    # Initial check
    await asyncio.sleep(2)  # Brief wait on startup
    if len(node_state["discovered_nodes"]) == 0:
        print(f"No other nodes detected. {node_state['bin_id']} is MASTER.")
        node_state["is_master"] = True
        node_state["last_election"] = datetime.utcnow()
    else:
        print(f"Detected {len(node_state['discovered_nodes'])} other nodes.")
        print(f"Election may be needed...")


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class Telemetry(BaseModel):
    bin_id: str
    timestamp: datetime
    fill_level: float
    battery: float
    signal_strength: Optional[int] = None
    temperature: Optional[float] = None
    is_master: bool
    master_id: Optional[str] = None
    location: Optional[str] = None


class Command(BaseModel):
    command_id: str
    action: str
    parameters: Optional[dict] = None


class CommandAck(BaseModel):
    command_id: str
    bin_id: str
    status: str


class ElectionMember(BaseModel):
    bin_id: str
    score: float
    is_candidate: bool


class ElectionResult(BaseModel):
    cluster_id: str
    members: List[ElectionMember]
    chosen_master: str


class MasterStatus(BaseModel):
    bin_id: str
    is_master: bool
    cluster_id: str
    master_id: Optional[str]
    slaves: List[str]
    last_election: Optional[datetime]


# ============================================================================
# CORE API ENDPOINTS (Backend Interface)
# ============================================================================

@app.post("/api/v1/telemetry")
async def post_telemetry(data: List[Telemetry]):
    """
    Receive telemetry from master node or aggregated from slaves.
    Master nodes collect data from slaves via BLE mesh and push here.
    """
    telemetry_buffer.extend([t.dict() for t in data])
    return {"status": "accepted", "received": len(data)}


@app.get("/api/v1/commands/{bin_id}")
async def get_commands(bin_id: str):
    """
    Retrieve pending commands for a specific bin.
    Master node fetches commands for itself and slaves.
    """
    return command_queue.get(bin_id, [])


@app.post("/api/v1/commands/ack")
async def ack_command(ack: CommandAck):
    """
    Acknowledge command completion.
    Removes command from queue after execution.
    """
    bin_id = ack.bin_id
    cmd_id = ack.command_id
    
    if bin_id in command_queue:
        command_queue[bin_id] = [
            cmd for cmd in command_queue[bin_id] 
            if cmd.get("command_id") != cmd_id
        ]
    
    return {"status": "ok", "ack": ack.dict()}


@app.post("/api/v1/election")
async def post_election(data: ElectionResult):
    """
    Log election result from cluster.
    Updates master/slave state based on election outcome.
    """
    election_history.append({
        **data.dict(),
        "recorded_at": datetime.utcnow()
    })
    
    # Update local node state based on election
    if data.chosen_master == node_state["bin_id"]:
        node_state["is_master"] = True
        node_state["master_id"] = None
        node_state["slaves"] = [
            m.bin_id for m in data.members 
            if m.bin_id != node_state["bin_id"]
        ]
    else:
        node_state["is_master"] = False
        node_state["master_id"] = data.chosen_master
        node_state["slaves"] = []
    
    node_state["last_election"] = datetime.utcnow()
    
    return {"status": "logged", "new_master": data.chosen_master}


# ============================================================================
# MASTER/SLAVE STATUS WEBHOOK
# ============================================================================

@app.get("/api/v1/status", response_model=MasterStatus)
async def get_status():
    """
    Advertise this unit's master/slave status and list slaves.
    Used for monitoring and debugging mesh topology.
    """
    return MasterStatus(
        bin_id=node_state["bin_id"],
        is_master=node_state["is_master"],
        cluster_id=node_state["cluster_id"],
        master_id=node_state["master_id"],
        slaves=node_state["slaves"],
        last_election=node_state["last_election"]
    )


@app.put("/api/v1/cluster/rename")
async def rename_cluster(new_name: str):
    """
    Manually rename the cluster.
    Useful for giving meaningful names instead of auto-generated IDs.
    
    Example: "Office-Floor-2" or "Warehouse-A"
    """
    old_name = node_state["cluster_id"]
    node_state["cluster_id"] = new_name
    
    return {
        "status": "renamed",
        "old_cluster_id": old_name,
        "new_cluster_id": new_name,
        "members": sorted([node_state["bin_id"]] + list(node_state["discovered_nodes"].keys()))
    }


@app.post("/api/v1/discover")
async def register_node(bin_id: str, cluster_id: Optional[str] = None):
    """
    Register a discovered node (for testing/manual registration).
    
    In production, this will be replaced by BLE mesh HELLO messages.
    This endpoint simulates node discovery.
    """
    # Validate bin_id format
    if not bin_id.startswith("BIN-"):
        raise HTTPException(
            status_code=400,
            detail="bin_id must start with 'BIN-'"
        )
    
    # Update discovered nodes
    node_state["discovered_nodes"][bin_id] = time.time()
    
    # Regenerate cluster ID based on new membership
    new_cluster_id = update_cluster_id()
    
    # If we're master and this is a new node, add to slaves
    if node_state["is_master"] and bin_id not in node_state["slaves"]:
        node_state["slaves"].append(bin_id)
    
    return {
        "status": "registered",
        "bin_id": bin_id,
        "cluster_id": node_state["cluster_id"],
        "is_master": node_state["is_master"],
        "total_nodes": len(node_state["discovered_nodes"]) + 1,  # +1 for self
        "all_members": sorted([node_state["bin_id"]] + list(node_state["discovered_nodes"].keys()))
    }


@app.delete("/api/v1/discover/{bin_id}")
async def unregister_node(bin_id: str):
    """
    Remove a node from discovered nodes (for testing).
    Simulates node going offline.
    """
    if bin_id in node_state["discovered_nodes"]:
        del node_state["discovered_nodes"][bin_id]
    
    if bin_id in node_state["slaves"]:
        node_state["slaves"].remove(bin_id)
    
    # Regenerate cluster ID based on remaining members
    update_cluster_id()
    
    # If no more nodes and we're not master, become master
    if len(node_state["discovered_nodes"]) == 0 and not node_state["is_master"]:
        node_state["is_master"] = True
        node_state["master_id"] = None
        node_state["last_election"] = datetime.utcnow()
    
    return {
        "status": "unregistered",
        "bin_id": bin_id,
        "cluster_id": node_state["cluster_id"],
        "remaining_nodes": len(node_state["discovered_nodes"]),
        "all_members": sorted([node_state["bin_id"]] + list(node_state["discovered_nodes"].keys()))
    }


# ============================================================================
# HARDWARE ENDPOINTS (Not yet implemented - hardware pending)
# ============================================================================
    
    return {
        "status": "unregistered",
        "bin_id": bin_id,
        "remaining_nodes": len(node_state["discovered_nodes"])
    }


# ============================================================================
# HARDWARE ENDPOINTS (Not yet implemented - hardware pending)
# ============================================================================

@app.get("/api/v1/occupancy")
async def get_occupancy():
    """
    Get garbage bin fill level as a percentage.
    
    TODO: Hardware integration pending
    - Connect to ultrasonic/IR sensor
    - Calculate distance to waste
    - Convert to percentage (0-100%)
    
    Example implementation:
        sensor_distance = read_ultrasonic_sensor()
        bin_depth = 100  # cm
        occupancy = ((bin_depth - sensor_distance) / bin_depth) * 100
        return {"occupancy_percentage": occupancy}
    """
    # Mock data until hardware ready
    return {"occupancy_percentage": 45.5, "status": "mock"}


@app.get("/api/v1/battery")
async def get_battery():
    """
    Get battery level as a percentage.
    
    TODO: Hardware integration pending
    - Read from battery management IC (e.g., MAX17048)
    - Query voltage/percentage via I2C
    
    Example implementation:
        battery_voltage = read_battery_voltage()
        battery_pct = voltage_to_percentage(battery_voltage)
        return {"battery_percentage": battery_pct}
    """
    # Mock data until hardware ready
    return {"battery_percentage": 87.3, "status": "mock"}


@app.post("/api/v1/motor/dock")
async def move_to_dock(dock_id: Optional[str] = "D1"):
    """
    Command bin to move to specified dock.
    
    TODO: Hardware integration pending
    - Interface with motor controller
    - Implement navigation logic
    - Add obstacle detection
    
    Example implementation:
        await motor_controller.navigate_to_dock(dock_id)
        await wait_for_docking_complete()
        return {"status": "docked"}
    """
    # Mock response until hardware ready
    return {
        "status": "mock",
        "message": f"Would move to dock {dock_id}",
        "dock_id": dock_id
    }


@app.post("/api/v1/motor/stop")
async def motor_stop():
    """
    Emergency stop for motor movement.
    
    TODO: Hardware integration pending
    - Immediate motor cutoff
    - Safety checks
    
    Example implementation:
        motor_controller.emergency_stop()
        return {"status": "stopped"}
    """
    return {"status": "mock", "message": "Would stop motor"}


@app.get("/api/v1/temperature")
async def get_temperature():
    """
    Get internal temperature sensor reading.
    
    TODO: Hardware integration pending
    - Read from DHT22/BME280 sensor
    - Return celsius value
    
    Example implementation:
        temp_c = read_temperature_sensor()
        return {"temperature_celsius": temp_c}
    """
    return {"temperature_celsius": 22.5, "status": "mock"}


@app.get("/api/v1/signal-strength")
async def get_signal_strength():
    """
    Get BLE/WiFi signal strength (RSSI).
    
    TODO: Hardware integration pending
    - Query BLE adapter for RSSI to master
    - Or WiFi RSSI if connected to AP
    
    Example implementation:
        rssi = get_ble_rssi_to_master()
        return {"rssi": rssi}
    """
    return {"rssi": -65, "status": "mock"}


# ============================================================================
# ROOT & HEALTH
# ============================================================================

@app.get("/")
async def root():
    return {
        "service": "Smart Bin API",
        "version": "1.0.0",
        "node": node_state["bin_id"],
        "is_master": node_state["is_master"]
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
