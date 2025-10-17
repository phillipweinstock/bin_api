import requests
import asyncio
import csv
import hashlib
import logging
import os
import statistics
import time
import uuid
import subprocess
import platform
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

if platform.system() == "Windows":
    log_file_path = "C:/temp/bin_api.log"
    os.makedirs("C:/temp", exist_ok=True)
else:
    log_file_path = "/tmp/bin_api.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(asctime)s - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(log_file_path)],
)
logger = logging.getLogger(__name__)
__VERSION__ = "1.0.0"
logger.info(f"Starting Smart Bin API v{__VERSION__}")
MOCK = 0
TRIG = 22
ECHO = 16
MAX_DISTANCE = 20.0
MIN_DISTANCE = 9.0
TIMEOUT = 0.02  # 20 ms timeout
SAMPLE_COUNT = 5
CURRENT_OCCUPANCY = 0.0
MANUAL_CLUSTER_RENAME = False
LID_LOCKED = False
WEBHOOK = "http://172.26.59.116:3000/api/bin-status"
try:
    import adafruit_dht
    import board
    import lgpio as GPIO
    import motoron
    import spidev
    from adafruit_servokit import ServoKit
    from dbus_next.aio import MessageBus
    from gpiozero import DigitalInputDevice

    logger.info("Hardware libraries imported successfully")
except ImportError as e:
    # For environments without hardware access (e.g., testing)
    # mock it
    logger.warning(f"Hardware libraries not found: {e}")
    logger.info("Using mock hardware implementations")

    class ServoKit:
        class MockServo:
            def __init__(self, channel):
                self.channel = channel
                self._angle = 0
                self.actuation_range = 180
                logger.debug(f"Mock Servo created for channel {channel}")

            @property
            def angle(self):
                return self._angle

            @angle.setter
            def angle(self, value):
                logger.debug(
                    f"Mock servo channel {self.channel} set to {value} degrees"
                )
                self._angle = value

        def __init__(self, channels):
            self.channels = channels
            self.servo = [self.MockServo(i) for i in range(channels)]
            logger.debug(f"Mock ServoKit initialized with {channels} channels")

        def set_angle(self, channel, angle):
            logger.debug(f"Mock servo channel {channel} set to {angle} degrees")

    class DigitalInputDevice:
        def __init__(self, pin):
            self.pin = pin
            logger.debug(f"Mock DigitalInputDevice initialized on pin {pin}")

        @property
        def value(self):
            return 1  # Not triggered (active low sensor)

        def is_active(self):
            return False

    class Motoron:
        def __init__(self, address):
            self.address = address
            logger.debug(f"Mock Motoron initialized with address {address}")

    class GPIO:
        _pin_states = {}  # Track pin states for mock behavior
        _read_count = {}  # Track how many times a pin has been read

        @staticmethod
        def setup(pin, mode):
            logger.debug(f"Mock GPIO setup pin {pin} mode {mode}")

        @staticmethod
        def output(pin, value):
            logger.debug(f"Mock GPIO output pin {pin} value {value}")

        @staticmethod
        def input(pin):
            return False

        @staticmethod
        def gpiochip_open():
            logger.debug("Mock GPIO chip opened")
            return None

        @staticmethod
        def gpio_claim_output(h, pin):
            logger.debug(f"Mock GPIO claim output pin {pin}")
            GPIO._pin_states[pin] = 0
            return None

        @staticmethod
        def gpio_claim_input(h, pin):
            logger.debug(f"Mock GPIO claim input pin {pin}")
            GPIO._pin_states[pin] = GPIO._read_count[pin] = 0
            return None

        @staticmethod
        def gpio_write(h, pin, value):
            logger.debug(f"Mock GPIO write pin {pin} value {value}")
            GPIO._pin_states[pin] = value

        @staticmethod
        def gpio_read(h, pin):
            # Simulate ultrasonic sensor behavior
            # First few reads return 0 (waiting for pulse)
            if pin not in GPIO._read_count:
                GPIO._read_count[pin] = 0

            GPIO._read_count[pin] += 1
            count = GPIO._read_count[pin]
            retval = 0
            match count:
                case 1 | 2:
                    retval = 0
                case 3 | 4 | 5:
                    retval = 1
                case _:
                    GPIO._read_count[pin] = 0
                    retval = 0
            return retval

    class board:
        D17 = None

    class adafruit_dht:
        class DHT11:
            def __init__(self, pin):
                logger.debug(f"Mock DHT11 initialized on pin {pin}")

            @property
            def temperature(self):
                return 25.0
            @property
            def temp_c(self):
                return 25.0

            @property
            def humidity(self):
                return 50.0

    class spidev:
        class SpiDev:
            def open(self, bus, device):
                logger.debug(f"Mock SPI opened bus {bus} device {device}")

            def xfer2(self, data):
                return [0, 0, 0]
    class WifiController:
        def __init__(self,interface='wlan0'):
            logger.debug("Mock WifiController initialized")

        def run(self,*cmd):
            logger.debug(f"Mock WifiController run command: {' '.join(cmd)}")
            return "Mocked subprocess output"
        def enable(self):
            logger.debug("Mock WifiController enable called")
            self.run("rfkill","unblock","wifi")
        def disable(self):
            logger.debug("Mock WifiController disable called")
            self.run("rfkill","block","wifi")
        def is_enabled(self):
            logger.debug("Mock WifiController is_enabled called")
            return True
            #sudo setcap cap_net_admin+ep $(which rfkill) must be run to use rfkill without sudo
            

    MOCK = 1

# Initialize hardware components (real or mock)
# NOTE: GPIO initialization is deferred to startup event to avoid import-time conflicts
controller = None  # Will be initialized in startup_event

if MOCK == 0:
    logger.info("Initializing real hardware components (GPIO deferred to startup)")
    dhtDevice = adafruit_dht.DHT11(board.D17)
    motor_controller = motoron.MotoronI2C(address=0x58)
    spi = spidev.SpiDev()
    spi.open(0, 0)  # Open SPI bus 0, device 0
    kit = ServoKit(channels=16)
    
    # GPIO will be initialized in startup_event to avoid import-time claiming
    
    class WifiController:
        def __init__(self,interface='wlan0'):
            self.interface=interface
        def run(self,*cmd):
            result=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            if result.returncode!=0:
                raise Exception(f"Command {' '.join(cmd)} failed: {result.stderr.strip()}")
            return result.stdout.strip()
        def enable(self):
            self.run("rfkill","unblock","wifi")
        def disable(self):
            self.run("rfkill","block","wifi")
        def is_enabled(self):
            status=self.run("rfkill","list","wifi")
            return "Soft blocked: no" in status and "Hard blocked: no" in status
    wifi = WifiController()
else:
    logger.info("Initializing mock hardware components")
    dhtDevice = adafruit_dht.DHT11(None)
    motor_controller = Motoron(address=0x58)
    spi = spidev.SpiDev()
    spi.open(0, 0)
    kit = ServoKit(channels=16)
    controller = GPIO.gpiochip_open()
    GPIO.gpio_claim_output(controller, TRIG)
    GPIO.gpio_claim_input(controller, ECHO)
    wifi = WifiController()

app = FastAPI(
    title="Smart Bin API",
    version=__VERSION__,
    description="REST API for ***BLE*** ***Mesh*** Federated IoT Bin System",
)

background_tasks = set()


async def get_distance():
    logger.info("Getting distance measurement")
    GPIO.gpio_write(controller, TRIG, 0)
    await asyncio.sleep(0.002)
    GPIO.gpio_write(controller, TRIG, 1)
    await asyncio.sleep(0.00001)
    time_start = time.time()
    while GPIO.gpio_read(controller, ECHO) == 0:
        pulse_start = time.time()
        if time.time() - time_start > TIMEOUT:
            logger.warning("Timeout waiting for ECHO HIGH")
            return None
    while GPIO.gpio_read(controller, ECHO) == 1:
        pulse_end = time.time()
        if time.time() - time_start > TIMEOUT:
            logger.warning("Timeout waiting for ECHO LOW")
            return None
    duration = pulse_end - pulse_start
    distance = duration * 17150  # Calculate distance in cm
    if distance < MIN_DISTANCE or distance > MAX_DISTANCE:
        logger.warning(f"Distance out of range: {distance} cm")
        return None
    logger.info(f"Distance measured: {distance} cm")
    return round(distance, 2)


async def get_median_distance(samples=SAMPLE_COUNT):
    logger.info(f"Getting median distance from {samples} samples")
    readings = []
    for _ in range(samples):
        dist = await get_distance()
        if dist is not None:
            readings.append(dist)
        await asyncio.sleep(0.05)  # Small delay between samples
    if not readings:
        logger.warning("No valid distance readings obtained")
        return None
    median_dist = statistics.median(readings)
    logger.info(f"Median distance from {samples} samples: {median_dist} cm")
    return round(median_dist, 2)


async def compute_occupancy(distance):
    if distance is None:
        return None
    if distance > MAX_DISTANCE:
        distance = MAX_DISTANCE
    if distance < MIN_DISTANCE:
        distance = MIN_DISTANCE
    occupancy = (
        (MAX_DISTANCE - distance) / (MAX_DISTANCE - MIN_DISTANCE)
    ) * 100  # not the same as Cleo's
    return round(occupancy, 2)


async def occupancy_monitoring_task():
    logging.info("Occupancy monitoring task started")
    background_tasks.add(asyncio.current_task())
    while True:
        distance = await get_median_distance()
        if distance is not None:
            occupancy = await compute_occupancy(distance)
            logging.info(f"Current occupancy: {occupancy}%")
            global CURRENT_OCCUPANCY
            CURRENT_OCCUPANCY = occupancy
        await asyncio.sleep(300)  # Check every 5 minutes
    background_tasks.remove(asyncio.current_task())


async def lid_control_task():
    # Control lid using servo on channel 10
    background_tasks.add(asyncio.current_task())
    servo = kit.servo[10]
    servo.actuation_range = 180
    sensor = DigitalInputDevice(26)
    logging.info("Lid control task started")
    while True:
        if LID_LOCKED:
            servo.angle = 0
            logging.info("Lid is locked. Keeping closed.")
            await asyncio.sleep(0.5)
            continue
        if sensor.value == 0:
            logging.info("Sensor triggered! Opening lid...")
            servo.angle = 180
            await asyncio.sleep(5)
            logging.info("Closing lid...")
            servo.angle = 0
            await asyncio.sleep(1)  # Debounce
        else:
            servo.angle = 0
        await asyncio.sleep(0.1)

    background_tasks.remove(asyncio.current_task())


async def open_door():
    # Open the door using servo on channel 11
    logging.info("Door open task started")
    background_tasks.add(asyncio.current_task())
    servo = kit.servo[11]
    servo.actuation_range = 180
    for angle in range(0, 181, 10):
        servo.angle = angle
        await asyncio.sleep(0.05)
    for angle in range(180, -1, -10):
        servo.angle = angle
        await asyncio.sleep(0.05)
    background_tasks.remove(asyncio.current_task())


def get_hardware_id():
    """
    Generate a deterministic unique ID based on hardware.

    Priority:
    1. Raspberry Pi serial number (from /proc/cpuinfo), likely need to use some `subprocess` calls i.e cat
    2. MAC address of first network interface
    3. Fallback to generated UUID (saved to file)
    """
    logger.info("Generating hardware ID")
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.startswith("Serial"):
                    serial = line.split(":")[1].strip()
                    if serial and serial != "0000000000000000":
                        logger.info(
                            f"Using CPU serial number for hardware ID: {serial[-8:]}"
                        )
                        return serial[-8:]  # Last 8 chars
    except:
        pass

    try:
        mac = ":".join(
            [
                "{:02x}".format((uuid.getnode() >> elements) & 0xFF)
                for elements in range(0, 2 * 6, 2)
            ][::-1]
        )
        if mac != "00:00:00:00:00:00":
            # Use last 6 chars of MAC (without colons)
            logger.info(
                f"Using MAC address for hardware ID: {mac.replace(':', '')[-6:]}"
            )
            return mac.replace(":", "")[-6:]
    except:
        pass

    id_file = "/tmp/bin_hardware_id"
    if os.path.exists(id_file):
        with open(id_file, "r") as f:
            return f.read().strip()
    else:
        generated_id = str(uuid.uuid4())[:6].upper()
        with open(id_file, "w") as f:
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
    combined = "".join([bid.split("-")[1][:2] for bid in sorted_ids])

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

command_queue: Dict[str, List[dict]] = {}
telemetry_buffer: List[dict] = []
election_history: List[dict] = []


# ============================================================================
# DISCOVERY & ELECTION LOGIC
# ============================================================================


def update_cluster_id():
    """
    Regenerate cluster ID based on current members.
    Called when nodes join/leave the cluster.
    """
    if MANUAL_CLUSTER_RENAME:
        return node_state["cluster_id"] # we dont really want to rename it if manually set
        #we should expect that bins joining the cluster to accept the manual name

    all_members = [node_state["bin_id"]] + list(node_state["discovered_nodes"].keys())
    new_cluster_id = generate_cluster_id(all_members)

    if new_cluster_id != node_state["cluster_id"]:
        old_cluster_id = node_state["cluster_id"]
        node_state["cluster_id"] = new_cluster_id
        logger.info(f"Cluster renamed: {old_cluster_id} → {new_cluster_id}")
        logger.info(f"Members: {', '.join(sorted(all_members))}")

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
        bin_id
        for bin_id, last_seen in node_state["discovered_nodes"].items()
        if current_time - last_seen > HEARTBEAT_TIMEOUT
    ]

    for bin_id in stale_nodes:
        logger.info(f"Removing stale node: {bin_id}")
        del node_state["discovered_nodes"][bin_id]
        if bin_id in node_state["slaves"]:
            node_state["slaves"].remove(bin_id)

    # Update cluster ID if members changed
    if stale_nodes:
        update_cluster_id()

    # If no other nodes discovered, remain/become master
    if len(node_state["discovered_nodes"]) == 0:
        if not node_state["is_master"]:
            logger.info(
                f"No other nodes detected. {node_state['bin_id']} becoming master."
            )
            node_state["is_master"] = True
            node_state["master_id"] = None
            node_state["last_election"] = datetime.utcnow()

async def periodic_telemetry():
    """
    Periodically send telemetry data to the frontend server.
    Sends this node's data plus all connected slaves' data.
    """
    background_tasks.add(asyncio.current_task())
    
    # Wait before first telemetry send to avoid blocking startup
    await asyncio.sleep(10)
    
    while True:
        try:
            # Collect this node's telemetry
            current_temp = dhtDevice.temperature if MOCK == 0 else 25.0
            current_humidity = dhtDevice.humidity if MOCK == 0 else 50.0
            
            this_node_telemetry = {
                "bin_id": node_state["bin_id"],
                "timestamp": datetime.utcnow().isoformat(),
                "fill_level": CURRENT_OCCUPANCY,
                "battery": 100.0,  # TODO: Replace with actual battery reading
                "signal_strength": -50,  # TODO: Replace with actual RSSI
                "temperature": current_temp,
                "humidity": current_humidity,
                "is_master": node_state["is_master"],
                "master_id": node_state["master_id"],
                "cluster_id": node_state["cluster_id"],
               # "location": "Warehouse A",  # TODO: Make configurable
            }
            
            # Prepare telemetry payload
            telemetry_payload = {
                "master_node": this_node_telemetry,
                "slave_nodes": [],
                "cluster_summary": {
                    "cluster_id": node_state["cluster_id"],
                    "total_nodes": len(node_state["slaves"]) + 1,
                    "master_id": node_state["bin_id"],
                    "slave_ids": node_state["slaves"],
                    "timestamp": datetime.utcnow().isoformat(),
                }
            }
            
            # Add slave telemetry if we're master
            # TODO:  this will be aggregated from BLE mesh TELEMETRY messages
            if node_state["is_master"] and node_state["slaves"]:
                logger.info(f"Collecting telemetry from {len(node_state['slaves'])} slaves")
                for slave_id in node_state["slaves"]:
                    # Mock slave data for now - will be replaced with actual BLE mesh data
                    slave_telemetry = {
                        "bin_id": slave_id,
                        "timestamp": datetime.utcnow().isoformat(),
                        "fill_level": 50.0,  # Mock data
                        "battery": 85.0,  # Mock data
                        "signal_strength": -60,  # Mock data
                        "temperature": 24.0,  # Mock data
                        "humidity": 48.0,  # Mock data
                        "is_master": False,
                        "master_id": node_state["bin_id"],
                        "cluster_id": node_state["cluster_id"],
                        #"location": f"Warehouse A - Slave",  # Mock data
                    }
                    telemetry_payload["slave_nodes"].append(slave_telemetry)
            
            # Send to webhook endpoint
            logger.info(f"Sending telemetry for cluster {node_state['cluster_id']}: " +
                       f"{len(telemetry_payload['slave_nodes']) + 1} nodes")
            
            # Run the blocking request in a thread pool to avoid blocking event loop
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(WEBHOOK, json=telemetry_payload, timeout=10)
            )
            
            if response.status_code == 200:
                logger.info(f"Telemetry sent successfully to {WEBHOOK}")
            else:
                logger.warning(f"Telemetry failed with status {response.status_code}: {response.text}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send telemetry to {WEBHOOK}: {e}")
        except Exception as e:
            logger.error(f"Error in telemetry task: {e}")
        
        await asyncio.sleep(300)  # Every 5 minutes
    
    background_tasks.remove(asyncio.current_task())

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
    global controller
    
    # If this wasnt a university project I would not use a deprecated method
    # but FastAPI's lifespan handlers are more complex to implement and I dont give a rats ass
    # about the deprecation warning for now
    
    # Initialize GPIO if on real hardware
    if MOCK == 0:
        logger.info("Initializing GPIO pins...")
        controller = GPIO.gpiochip_open(4)
        
        # Free GPIO pins if they're already claimed (cleanup from previous run)
        try:
            GPIO.gpio_free(controller, TRIG)
            logger.debug(f"Freed GPIO pin {TRIG}")
        except Exception as e:
            logger.debug(f"GPIO pin {TRIG} was not claimed: {e}")
        
        try:
            GPIO.gpio_free(controller, ECHO)
            logger.debug(f"Freed GPIO pin {ECHO}")
        except Exception as e:
            logger.debug(f"GPIO pin {ECHO} was not claimed: {e}")
        
        # Now claim the pins
        try:
            GPIO.gpio_claim_output(controller, TRIG)
            logger.info(f"Claimed GPIO pin {TRIG} as output (TRIG)")
        except Exception as e:
            logger.error(f"Failed to claim GPIO pin {TRIG}: {e}")
            raise
        
        try:
            GPIO.gpio_claim_input(controller, ECHO)
            logger.info(f"Claimed GPIO pin {ECHO} as input (ECHO)")
        except Exception as e:
            logger.error(f"Failed to claim GPIO pin {ECHO}: {e}")
            raise
    
    logging.info(f"Starting {node_state['bin_id']}...")
    logging.info(f"Cluster: {node_state['cluster_id']}")

    # Start periodic tasks in background
    asyncio.create_task(periodic_discovery())
    asyncio.create_task(periodic_telemetry())
    asyncio.create_task(lid_control_task())
    asyncio.create_task(occupancy_monitoring_task())
    # TODO implement a task to raise an event when the bin is full or about to be full

    # Initial check
    await asyncio.sleep(2)  # Brief wait on startup
    if len(node_state["discovered_nodes"]) == 0:
        logger.info(f"No other nodes detected. {node_state['bin_id']} is MASTER.")
        node_state["is_master"] = True
        node_state["last_election"] = datetime.utcnow()
    else:
        logger.info(f"Detected {len(node_state['discovered_nodes'])} other nodes.")
        logger.info(f"Election may be needed...")



@app.on_event("shutdown")
async def shutdown_event():
    """
    Clean up resources on shutdown.
    """
    logger.info("Shutting down...")
    
    # Clean up GPIO if running on real hardware
    if MOCK == 0 and controller is not None:
        try:
            logger.info("Cleaning up GPIO pins...")
            GPIO.gpio_free(controller, TRIG)
            GPIO.gpio_free(controller, ECHO)
            GPIO.gpiochip_close(controller)
            logger.info("GPIO cleanup complete")
        except Exception as e:
            logger.error(f"Error during GPIO cleanup: {e}")
    
    logger.info("Shutdown complete")



class Telemetry(BaseModel):
    bin_id: str
    timestamp: datetime
    fill_level: float
    battery: float
    signal_strength: Optional[int] = None
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    is_master: bool
    master_id: Optional[str] = None
    cluster_id: Optional[str] = None
    #location: Optional[str] = None


class ClusterSummary(BaseModel):
    cluster_id: str
    total_nodes: int
    master_id: str
    slave_ids: List[str]
    timestamp: str


class TelemetryPayload(BaseModel):
    """Comprehensive telemetry payload including master and all slaves"""
    master_node: Telemetry
    slave_nodes: List[Telemetry]
    cluster_summary: ClusterSummary


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


# @app.post("/api/v1/telemetry")
# async def post_telemetry(data: List[Telemetry]):
#     """
#     Receive telemetry from master node or aggregated from slaves.
#     Master nodes collect data from slaves via BLE mesh and push here.
#     """
#     telemetry_buffer.extend([t.dict() for t in data])
#     return {"status": "accepted", "received": len(data)}


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
            cmd for cmd in command_queue[bin_id] if cmd.get("command_id") != cmd_id
        ]

    return {"status": "ok", "ack": ack.dict()}


@app.post("/api/v1/election")
async def post_election(data: ElectionResult):
    """
    Log election result from cluster.
    Updates master/slave state based on election outcome.
    """
    election_history.append({**data.dict(), "recorded_at": datetime.utcnow()})

    # Update local node state based on election
    if data.chosen_master == node_state["bin_id"]:
        node_state["is_master"] = True
        node_state["master_id"] = None
        node_state["slaves"] = [
            m.bin_id for m in data.members if m.bin_id != node_state["bin_id"]
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
        last_election=node_state["last_election"],
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
    global MANUAL_CLUSTER_RENAME
    MANUAL_CLUSTER_RENAME = True

    return {
        "status": "renamed",
        "old_cluster_id": old_name,
        "new_cluster_id": new_name,
        "members": sorted(
            [node_state["bin_id"]] + list(node_state["discovered_nodes"].keys())
        ),
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
        raise HTTPException(status_code=400, detail="bin_id must start with 'BIN-'")

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
        "all_members": sorted(
            [node_state["bin_id"]] + list(node_state["discovered_nodes"].keys())
        ),
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

    if len(node_state["discovered_nodes"]) == 0 and not node_state["is_master"]:
        node_state["is_master"] = True
        node_state["master_id"] = None
        node_state["last_election"] = datetime.utcnow()

    return {
        "status": "unregistered",
        "bin_id": bin_id,
        "cluster_id": node_state["cluster_id"],
        "remaining_nodes": len(node_state["discovered_nodes"]),
        "all_members": sorted(
            [node_state["bin_id"]] + list(node_state["discovered_nodes"].keys())
        ),
    }

    # ============================================================================
    # HARDWARE ENDPOINTS (Not yet implemented - hardware pending)
    # ============================================================================

    return {
        "status": "unregistered",
        "bin_id": bin_id,
        "remaining_nodes": len(node_state["discovered_nodes"]),
    }


# ============================================================================
# HARDWARE ENDPOINTS (Not yet implemented - hardware pending)
# ============================================================================


@app.get("/api/v1/occupancy")
async def get_occupancy():
    """
    Get garbage bin fill level as a percentage.
    """
    return {"occupancy_percentage": CURRENT_OCCUPANCY}


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
    return {"battery_percentage": 87.3, "status": "mock-this would be replaced with a battery status reading"}


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
        "message": f"Would move to dock {dock_id}",
        "dock_id": dock_id,
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
    return {"message": "Would stop motor"}


@app.post("/api/v1/door/open")
async def door_open():
    """
    Command to open the side door.
    """
    retval = {}
    if MOCK:
        retval = {"message": "Would open side door"}
    else:

        retval = {"message": "Side door opened"}

    task = asyncio.create_task(open_door())
    return retval


@app.post("/api/v1/door/close")
async def door_close():
    """
    Command to close the door.

    TODO: Hardware integration pending
    - Interface with door actuator
    - Implement safety checks

    Example implementation:
        await door_controller.close()
        return {"status": "closed"}
    """
    # I probably should ask if I just run the open_door function in reverse...
    return {"message": "Would close door"}


@app.get("/api/v1/environment/temperature")
async def get_temperature():
    """
    Get internal temperature sensor reading.
    """
    retval = {}
    if MOCK:
        retval = {"temperature_celsius": 22.5}
    else:
        retval = {"temperature_celsius": dhtDevice.temp_c}
    return retval


@app.get("/api/v1/environment/humidity")
async def get_humidity():
    """
    Get internal humidity sensor reading.
    """
    retval = {}
    if MOCK:
        retval = {"humidity_relative": 55.0}
    else:
        retval = {"humidity_relative": dhtDevice.humidity}
    return retval


@app.get("/api/v1/environment")
async def get_environment():
    """
    Get internal sensor reading of the environment.
    """
    # retval = {}
    # if MOCK:
    #     retval = {"temperature_celsius": 22.5, "humidity_relative": 55.0}
    # else:
    retval = {
            "temperature_celsius": dhtDevice.temp_c,
            "humidity_relative": dhtDevice.humidity,
        }
    return retval


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
    retval = {}
    if MOCK:
        retval = {"rssi": -65}
    else:
        # this shit isnt implemented yet
        # If Alexander Graham Bell saw what we were doing with mobile phones now... he'd probably kill himself
        retval = {"rssi": "CAN YOU HEAR ME NOW????"}
    return retval


@app.get("/")
async def root():
    return {
        "service": "Smart Bin API",
        "version": __VERSION__,
        "node": node_state["bin_id"],
        "is_master": node_state["is_master"],
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/api/v1/telemetry/preview")
async def preview_telemetry():
    """
    Preview the telemetry payload that will be sent to the webhook.
    Useful for debugging and monitoring.
    """
    current_temp = dhtDevice.temperature if MOCK == 0 else 25.0
    current_humidity = dhtDevice.humidity if MOCK == 0 else 50.0
    
    this_node_telemetry = {
        "bin_id": node_state["bin_id"],
        "timestamp": datetime.utcnow().isoformat(),
        "fill_level": CURRENT_OCCUPANCY,
        "battery": 100.0,
        "signal_strength": -50,
        "temperature": current_temp,
        "humidity": current_humidity,
        "is_master": node_state["is_master"],
        "master_id": node_state["master_id"],
        "cluster_id": node_state["cluster_id"],
        "location": "Warehouse A",
    }
    
    telemetry_payload = {
        "master_node": this_node_telemetry,
        "slave_nodes": [],
        "cluster_summary": {
            "cluster_id": node_state["cluster_id"],
            "total_nodes": len(node_state["slaves"]) + 1,
            "master_id": node_state["bin_id"],
            "slave_ids": node_state["slaves"],
            "timestamp": datetime.utcnow().isoformat(),
        }
    }
    
    # Add slave telemetry if we're master
    if node_state["is_master"] and node_state["slaves"]:
        for slave_id in node_state["slaves"]:
            slave_telemetry = {
                "bin_id": slave_id,
                "timestamp": datetime.utcnow().isoformat(),
                "fill_level": 50.0,
                "battery": 85.0,
                "signal_strength": -60,
                "temperature": 24.0,
                "humidity": 48.0,
                "is_master": False,
                "master_id": node_state["bin_id"],
                "cluster_id": node_state["cluster_id"],
                "location": f"Warehouse A - Slave",
            }
            telemetry_payload["slave_nodes"].append(slave_telemetry)
    
    return telemetry_payload


if __name__ == "__main__":
    import uvicorn
    # Disable reload on real hardware to avoid GPIO conflicts
    # The reload feature spawns child processes that try to claim already-claimed GPIO pins
    use_reload = MOCK == 1  # Only use reload in mock/development mode
    if not use_reload:
        logger.info("Running on real hardware - auto-reload disabled")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=use_reload)

