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
import threading
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

USE_TEMP_LOG = True

if USE_TEMP_LOG:
    if platform.system() == "Windows":
        log_file_path = "C:/temp/bin_api.log"
        os.makedirs("C:/temp", exist_ok=True)
    else:
        log_file_path = "/tmp/bin_api.log"
else:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_file_path = os.path.join(script_dir, "bin_api.log")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)s - %(asctime)s - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(log_file_path)],
)
logger = logging.getLogger(__name__)
__VERSION__ = "1.0.0"
logger.info(f"Starting Smart Bin v{__VERSION__}")
MOCK = 0
# Ultrasonic Lid/Avoidance constants
TRIG = 22
ECHO = 16
LID_SENSOR = 26  # GPIO pin for lid sensor (active low)
MAX_DISTANCE = 24.72
MIN_DISTANCE = 15
TIMEOUT = 0.02  # 20 ms timeout
SAMPLE_COUNT = 5
# Encoder constants & objects
encL, encR = None, None
LEFT_A, LEFT_B  = 23, 24
RIGHT_A, RIGHT_B = 27, 25
SAMPLE_HZ = 100  # Fixed sampling frequency (recommended 50–200 Hz)
MAX_PWM = 800
ACC = 150
DEC = 150
SPEED_SCALE = 13   #( 100-300)
SMOOTH_ALPHA = 0.5
MIN_DT = 0.005
MOTOR_DIR_L = -1
MOTOR_DIR_R = 1
STATIONARY_THRESHOLD = 3  # Max encoder change to consider "stationary"
STATIONARY_DURATION = 1.0  # Seconds of stationary data to trim from end
# Global state & configuration
CURRENT_OCCUPANCY = 0.0
MANUAL_CLUSTER_RENAME = False
LID_LOCKED = False
MOTOR_OPERATION_ACTIVE = False  # Lock lid during motor path operations
WEBHOOK = "http://172.26.59.116:3000/api/bin-status"


try:
    import adafruit_dht
    import board
    import lgpio as GPIO
    import motoron
    import spidev
    from adafruit_servokit import ServoKit
    from dbus_next.aio import MessageBus

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
            @property
            def temperature(self):
                return 25.0

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
controller = None 

if MOCK == 0:
    logger.info("Initializing real hardware components (GPIO deferred to startup)")
    dhtDevice = adafruit_dht.DHT11(board.D17)
    motor_controller = motoron.MotoronI2C()
    spi = spidev.SpiDev()
    spi.open(0, 0)  # Open SPI bus 0, device 0
    kit = ServoKit(channels=16)
    #wifi = WifiController() implement later
    # forward declare controller

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
    
    class MockDHT11:
        @property
        def temperature(self):
            return 22.5
        
        @property
        def humidity(self):
            return 55.0
    
    dhtDevice = MockDHT11()
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
dht_lock = threading.Lock()


async def get_distance():
    logger.info("Getting distance measurement")
    
    def blocking_gpio_read():
        encL_cb_backup, encR_cb_backup = None, None
        if MOCK == 0 and encL is not None and encR is not None:
            try:
                # Remove encoder callbacks temporarily
                GPIO.callback(controller, LEFT_A, GPIO.BOTH_EDGES, None)
                GPIO.callback(controller, LEFT_B, GPIO.BOTH_EDGES, None)
                GPIO.callback(controller, RIGHT_A, GPIO.BOTH_EDGES, None)
                GPIO.callback(controller, RIGHT_B, GPIO.BOTH_EDGES, None)
            except Exception as e:
                logger.debug(f"Could not disable encoder callbacks: {e}")
        
        try:
            # Check initial state
            initial_echo = GPIO.gpio_read(controller, ECHO)
            logger.debug(f"ECHO initial state: {initial_echo}")
            
            GPIO.gpio_write(controller, TRIG, 0)
            time.sleep(0.002)
            GPIO.gpio_write(controller, TRIG, 1)
            time.sleep(0.00001)
            GPIO.gpio_write(controller, TRIG, 0)
            
            time_start = time.time()
            pulse_start = time_start
            pulse_end = time_start
            
            wait_count = 0
            while GPIO.gpio_read(controller, ECHO) == 0:
                pulse_start = time.time()
                wait_count += 1
                if time.time() - time_start > TIMEOUT:
                    logger.warning(f"Timeout waiting for ECHO HIGH (checked {wait_count} times)")
                    return None
            
            logger.debug(f"ECHO went HIGH after {wait_count} checks, duration: {pulse_start - time_start:.6f}s")
            

            wait_count = 0
            while GPIO.gpio_read(controller, ECHO) == 1:
                pulse_end = time.time()
                wait_count += 1
                if time.time() - time_start > TIMEOUT:
                    echo_duration = pulse_end - pulse_start
                    logger.warning(f"Timeout waiting for ECHO LOW (checked {wait_count} times, pulse duration so far: {echo_duration:.6f}s)")
                    return None
            
            logger.debug(f"ECHO went LOW after {wait_count} checks")
            
            duration = pulse_end - pulse_start
            distance = duration * 17150
            
            if distance < MIN_DISTANCE or distance > MAX_DISTANCE:
                logger.warning(f"Distance out of range: {distance} cm")
                return None
            
            logger.info(f"Distance measured: {distance} cm")
            return round(distance, 2)
        finally:
            # Re-enable encoder callbacks
            if MOCK == 0 and encL is not None and encR is not None:
                try:
                    GPIO.callback(controller, LEFT_A, GPIO.BOTH_EDGES, encL._cb)
                    GPIO.callback(controller, LEFT_B, GPIO.BOTH_EDGES, encL._cb)
                    GPIO.callback(controller, RIGHT_A, GPIO.BOTH_EDGES, encR._cb)
                    GPIO.callback(controller, RIGHT_B, GPIO.BOTH_EDGES, encR._cb)
                except Exception as e:
                    logger.error(f"Could not re-enable encoder callbacks: {e}")
    
    try:
        loop = asyncio.get_event_loop()
        distance = await asyncio.wait_for(
            loop.run_in_executor(None, blocking_gpio_read),
            timeout=2.0
        )
        return distance
    except asyncio.TimeoutError:
        logger.error("Ultrasonic sensor read timed out")
        return None
    except Exception as e:
        logger.error(f"Error reading ultrasonic sensor: {e}")
        return None

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
    try:
        while True:
            try:
                distance = await get_median_distance()
                if distance is not None:
                    occupancy = await compute_occupancy(distance)
                    logging.info(f"Current occupancy: {occupancy}%")
                    global CURRENT_OCCUPANCY
                    CURRENT_OCCUPANCY = occupancy
            except asyncio.CancelledError:
                logger.info("Occupancy monitoring task cancelled, shutting down")
                raise
            except Exception as e:
                logger.error(f"Error in occupancy monitoring task: {e}")
            await asyncio.sleep(300)  # Check every 5 minutes
    finally:
        background_tasks.remove(asyncio.current_task())

async def lid_control_task():
    """
    Control lid using servo on channel 10.
    """
    background_tasks.add(asyncio.current_task())
    
    try:
        servo = kit.servo[0]
        servo.actuation_range = 180
        lid_sensor_gpio = None
        if MOCK == 0:
            try:
                # Set up GPIO 26 as input with pull-up resistor (sensor is active low)
                GPIO.gpio_claim_input(controller, LID_SENSOR, GPIO.SET_PULL_UP)
                lid_sensor_gpio = LID_SENSOR
                logger.info(f"Lid sensor initialized on GPIO {LID_SENSOR}")
            except Exception as e:
                logger.error(f"Failed to initialize lid sensor on GPIO {LID_SENSOR}: {e}")
                logger.warning("Lid sensor disabled - continuing without it")
        else:
            logger.info("Mock mode - lid sensor disabled")
        
        logging.info("Lid control task started")
        last_sensor_state = None
        
        while True:
            try:
                # Check if motor operation is active or lid is manually locked
                if LID_LOCKED or MOTOR_OPERATION_ACTIVE:
                    with dht_lock:
                        servo.angle = 180
                    if MOTOR_OPERATION_ACTIVE:
                        logging.debug("Motor operation active - lid locked closed.")
                    else:
                        logging.info("Lid is manually locked. Keeping closed.")
                    await asyncio.sleep(0.5)
                    continue
                
                if lid_sensor_gpio is not None:
                    sensor_value = GPIO.gpio_read(controller, lid_sensor_gpio)
                    
                    if sensor_value != last_sensor_state:
                        logger.debug(f"Lid sensor state changed: {last_sensor_state} -> {sensor_value}")
                        last_sensor_state = sensor_value
                    
                    if sensor_value == 0:  # Sensor triggered (active low)
                        logging.info("Lid sensor triggered! Opening lid...")
                        with dht_lock:
                            servo.angle = 0#180
                        await asyncio.sleep(5)
                        logging.info("Closing lid...")
                        with dht_lock:
                            servo.angle = 180
                        await asyncio.sleep(1)  
                    else:
                        with dht_lock:
                            servo.angle = 180
                else:
                    with dht_lock:
                        servo.angle = 180
                
                await asyncio.sleep(0.1)
                
            except asyncio.CancelledError:
                logger.info("Lid control task cancelled, shutting down")
                raise
            except Exception as e:
                logger.error(f"Error in lid control task: {e}")
                await asyncio.sleep(1)  
    finally:
        background_tasks.remove(asyncio.current_task())


async def open_door():
    # Open the door using servo on channel 11
    logging.info("Door open task started")
    background_tasks.add(asyncio.current_task())
    servo = kit.servo[11]
    servo.actuation_range = 180
    with dht_lock:
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
            if MOCK == 0:
                try:
                    with open("/sys/bus/iio/devices/iio:device0/in_temp_input", "r") as f:
                        current_temp = int(f.read().strip()) / 1000.0
                    with open("/sys/bus/iio/devices/iio:device0/in_humidityrelative_input", "r") as f:
                        current_humidity = int(f.read().strip()) / 1000.0
                except FileNotFoundError as e:
                    logger.warning(f"IIO sensor files not found, using mock values: {e}")
                    current_temp = 25.0
                    current_humidity = 50.0
                except Exception as e:
                    logger.error(f"Error reading IIO sensors, using mock values: {e}")
                    current_temp = 25.0
                    current_humidity = 50.0
            else:
                current_temp = 25.0
                current_humidity = 50.0
            
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
            
            # Send to webhook endpoint with shorter timeout and better error handling
            logger.info(f"Attempting to send telemetry to {WEBHOOK}")
            
            try:
                # Run the blocking request in a thread pool with short timeout
                loop = asyncio.get_event_loop()
                response = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, 
                        lambda: requests.post(WEBHOOK, json=telemetry_payload, timeout=3)
                    ),
                    timeout=5.0  # Total timeout including thread pool overhead
                )
                
                if response.status_code == 200:
                    logger.info(f"Telemetry sent successfully to {WEBHOOK}")
                else:
                    logger.warning(f"Telemetry failed with status {response.status_code}: {response.text}")
            except asyncio.TimeoutError:
                logger.error(f"Telemetry request to {WEBHOOK} timed out after 5 seconds")
            except requests.exceptions.ConnectionError:
                logger.error(f"Cannot connect to webhook {WEBHOOK} - is the server running?")
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to send telemetry to {WEBHOOK}: {e}")
                
        except asyncio.CancelledError:
            logger.info("Telemetry task cancelled, shutting down")
            raise
        except Exception as e:
            logger.error(f"Error in telemetry task: {e}")
        
        await asyncio.sleep(300)  # Every 5 minutes
    
    background_tasks.remove(asyncio.current_task())

async def periodic_discovery():
    """
    Periodically check for nodes and clean up stale entries.
    Runs in background.
    """
    background_tasks.add(asyncio.current_task())
    try:
        while True:
            try:
                await check_for_other_nodes()
            except asyncio.CancelledError:
                logger.info("Discovery task cancelled, shutting down")
                raise
            except Exception as e:
                logger.error(f"Error in discovery task: {e}")
            await asyncio.sleep(30)  # Check every 30 seconds
    finally:
        background_tasks.remove(asyncio.current_task())

async def coast_motors():
    try:
        motor_controller.reinitialize()
        motor_controller.clear_reset_flag()
        
        for ch in (1, 2):
            motor_controller.set_max_acceleration(ch, ACC)
            motor_controller.set_max_deceleration(ch, DEC)
        
        motor_controller.set_braking(1, 0)
        motor_controller.set_braking(2, 0)
        motor_controller.coast_now()
        
        # Increase timeout to prevent premature coasting during playback
        motor_controller.set_command_timeout_milliseconds(1000)  # Increased from 100ms to 1000ms
        
        logger.info(f"Motors initialized: ACC={ACC}, DEC={DEC}, timeout=1000ms, coast mode enabled")
    except Exception as e:
        logger.error(f"Motoron not set to Coast (possibly not connected or library missing): {e}")

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
        controller = GPIO.gpiochip_open(0)
        
        
        
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
        
        try:
            logger.info(f"Attempting to initialize encoders on pins L({LEFT_A},{LEFT_B}) R({RIGHT_A},{RIGHT_B})")
            
            class QuadCounter:
                # State transition lookup table: (last, curr) -> +1 / -1 / 0
                TRANS = {
                    (0,1):+1,(1,3):+1,(3,2):+1,(2,0):+1,
                    (1,0):-1,(3,1):-1,(2,3):-1,(0,2):-1
                }

                def __init__(self, h, a, b, name="enc"):
                    logger.info(f"QuadCounter.__init__ called for {name} on pins ({a},{b})")
                    self.h = h
                    self.a, self.b = a, b
                    self.name = name
                    self.pos = 0
                    logger.debug(f"{name}: Claiming input pins")
                    GPIO.gpio_claim_input(h, a)
                    GPIO.gpio_claim_input(h, b)
                    logger.debug(f"{name}: Setting up alerts")
                    GPIO.gpio_claim_alert(h, a, GPIO.RISING_EDGE | GPIO.FALLING_EDGE)
                    GPIO.gpio_claim_alert(h, b, GPIO.RISING_EDGE | GPIO.FALLING_EDGE)
                    logger.debug(f"{name}: Reading initial state")
                    self.last = ((GPIO.gpio_read(h, a) & 1) << 1) | (GPIO.gpio_read(h, b) & 1)
                    logger.debug(f"{name}: Setting up callbacks")
                    GPIO.callback(h, a, GPIO.BOTH_EDGES, self._cb)
                    GPIO.callback(h, b, GPIO.BOTH_EDGES, self._cb)
                    self.writer_ev = None
                    self._fev = None
                    logger.info(f"{name} initialized successfully")

                def bind_event_writer(self, writer, file_handle):
                    """Bind a CSV writer for event logging (used inside callback)."""
                    self.writer_ev = writer
                    self._fev = file_handle

                def _cb(self, chip, gpio, level, tick):
                    """Interrupt callback — handles both edges on A/B and updates position."""
                    curr = ((GPIO.gpio_read(self.h, self.a) & 1) << 1) | (GPIO.gpio_read(self.h, self.b) & 1)
                    delta = self.TRANS.get((self.last, curr), 0)
                    if delta:
                        self.pos += delta
                        if self.writer_ev:
                            t_us = time.monotonic_ns() // 1_000
                            a_lvl = (curr >> 1) & 1
                            b_lvl = curr & 1
                            self.writer_ev.writerow([t_us, self.name, a_lvl, b_lvl, delta, self.pos])
                            if self._fev:
                                self._fev.flush()
                    self.last = curr
            
            global encL, encR
            logger.info("Creating left encoder...")
            encL = QuadCounter(controller, LEFT_A, LEFT_B, name="LeftEncoder")
            logger.info("Creating right encoder...")
            encR = QuadCounter(controller, RIGHT_A, RIGHT_B, name="RightEncoder")
            logger.info(f"Encoders initialized: encL={encL}, encR={encR}")
        except Exception as e:
            logger.error(f"Error during Encoder initialization: {e}", exc_info=True)
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
            GPIO.gpio_free(controller, LID_SENSOR)
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
    
    Returns:
        - List of pending Command objects for the specified bin_id
    
    Example Response:
        ```json
        [
            {
                "command_id": "cmd-12345",
                "bin_id": "BIN-CB9B8676",
                "action": "open_lid",
                "params": {}
            }
        ]
        ```
    """
    return command_queue.get(bin_id, [])


@app.post("/api/v1/commands/ack")
async def ack_command(ack: CommandAck):
    """
    Acknowledge command completion.
    Removes command from queue after execution.
    
    Returns:
        - status: Status message (ok)
        - ack: The acknowledged CommandAck object
    
    Example Response:
        ```json
        {
            "status": "ok",
            "ack": {
                "bin_id": "BIN-CB9B8676",
                "command_id": "cmd-12345",
                "success": true,
                "message": "Lid opened successfully"
            }
        }
        ```
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
    
    Returns:
        - status: Status message (logged)
        - new_master: Bin ID of the newly elected master
    
    Example Response:
        ```json
        {
            "status": "logged",
            "new_master": "BIN-CB9B8676"
        }
        ```
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

@app.get("/api/v1/status", response_model=MasterStatus)
async def get_status():
    """
    Advertise this unit's master/slave status and list slaves.
    Used for monitoring and debugging mesh topology.
    
    Returns:
        - bin_id: This node's bin ID
        - is_master: Boolean indicating if this node is cluster master
        - cluster_id: Current cluster identifier
        - master_id: Bin ID of the cluster master
        - slaves: List of slave bin IDs in the cluster
        - last_election: Timestamp of last election event
    
    Example Response:
        ```json
        {
            "bin_id": "BIN-CB9B8676",
            "is_master": true,
            "cluster_id": "SOLO-CB9B",
            "master_id": null,
            "slaves": [],
            "last_election": "2025-10-18T14:23:45.123456"
        }
        ```
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
    
    Returns:
        - status: Status message (renamed)
        - old_cluster_id: Previous cluster identifier
        - new_cluster_id: New cluster identifier
        - members: List of all bin IDs in the cluster
    
    Example Response:
        ```json
        {
            "status": "renamed",
            "old_cluster_id": "SOLO-CB9B",
            "new_cluster_id": "Office-Floor-2",
            "members": ["BIN-CB9B8676"]
        }
        ```
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
    
    Returns:
        - status: Status message (registered)
        - bin_id: The registered bin ID
        - cluster_id: Updated cluster identifier
        - total_nodes: Total number of nodes in cluster
        
    Errors:
        - 400: Invalid bin_id format (must start with 'BIN-')
    
    Example Response:
        ```json
        {
            "status": "registered",
            "bin_id": "BIN-AAAABBBB",
            "cluster_id": "CLUSTER-3AC5",
            "is_master": true,
            "total_nodes": 2,
            "all_members": ["BIN-AAAABBBB", "BIN-CB9B8676"]
        }
        ```
    """
    if not bin_id.startswith("BIN-"):
        raise HTTPException(status_code=400, detail="bin_id must start with 'BIN-'")

    node_state["discovered_nodes"][bin_id] = time.time()
    new_cluster_id = update_cluster_id()

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
    
    Returns:
        - status: Status message (unregistered)
        - bin_id: The unregistered bin ID
        - cluster_id: Updated cluster identifier
        - remaining_nodes: Number of discovered nodes remaining
        - all_members: List of all remaining bin IDs in cluster
    
    Example Response:
        ```json
        {
            "status": "unregistered",
            "bin_id": "BIN-AAAABBBB",
            "cluster_id": "SOLO-CB9B",
            "remaining_nodes": 0,
            "all_members": ["BIN-CB9B8676"]
        }
        ```
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



@app.get("/api/v1/occupancy")
async def get_occupancy():
    """
    Get garbage bin fill level as a percentage.
    
    Returns:
        - occupancy_percentage: Float between 0-100 representing fill level
    
    Example Response:
        ```json
        {
            "occupancy_percentage": 15.82
        }
        ```
    """
    return {"occupancy_percentage": CURRENT_OCCUPANCY}


@app.get("/api/v1/lid/status")
async def get_lid_status():
    """
    Get current lid sensor status and lock state.
    
    Returns:
        - lid_locked: Boolean indicating if lid is manually locked
        - sensor_pin: GPIO pin number for lid sensor
        - sensor_value: Current sensor reading (0=triggered, 1=not triggered)
        - sensor_triggered: Boolean indicating if sensor is currently triggered
        - note: Explanation of sensor behavior
    
    Example Response:
        ```json
        {
            "lid_locked": false,
            "sensor_pin": 26,
            "sensor_value": 1,
            "sensor_triggered": false,
            "note": "sensor_value=0 means triggered (active low)"
        }
        ```
    """
    try:
        if MOCK == 0:
            sensor_value = GPIO.gpio_read(controller, LID_SENSOR)
        else:
            sensor_value = 1  # Mock value - not triggered
    except Exception as e:
        sensor_value = f"error: {e}"
    
    return {
        "lid_locked": LID_LOCKED,
        "sensor_pin": LID_SENSOR,
        "sensor_value": sensor_value,
        "sensor_triggered": sensor_value == 0 if isinstance(sensor_value, int) else False,
        "note": "sensor_value=0 means triggered (active low)"
    }


@app.get("/api/v1/battery")
async def get_battery():
    """
    Get battery level as a percentage.
    
    Returns:
        - battery_percentage: Float between 0-100
        - status: Status string (mock/ok)
    
    Example Response:
        ```json
        {
            "battery_percentage": 87.3,
            "status": "mock-this would be replaced with a battery status reading"
        }
        ```
    """
    return {"battery_percentage": 87.3, "status": "mock-this would be replaced with a battery status reading"}

def trim_stationary_data(csv_path: str):
    """
    Trim stationary data from the end of a recorded path.
    Removes rows where encoders haven't changed significantly for STATIONARY_DURATION seconds.
    """
    rows = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    
    if len(rows) < 10:
        logger.info(f"Too few rows ({len(rows)}) to trim from {csv_path}")
        return
    
    threshold_samples = int(STATIONARY_DURATION * SAMPLE_HZ)
    buffer_samples = int(0.2 * SAMPLE_HZ)  # 0.2 seconds buffer

    first_moving_idx = 0
    start_left = int(rows[0]["left_pos"])
    start_right = int(rows[0]["right_pos"])
    
    for i in range(1, min(len(rows), len(rows))):  # Check all rows
        curr_left = int(rows[i]["left_pos"])
        curr_right = int(rows[i]["right_pos"])
        
        if abs(curr_left - start_left) > STATIONARY_THRESHOLD or abs(curr_right - start_right) > STATIONARY_THRESHOLD:
            first_moving_idx = max(0, i - buffer_samples)  # Keep small buffer before movement
            logger.info(f"First significant movement at sample {i}: ({start_left},{start_right}) → ({curr_left},{curr_right})")
            break

    last_moving_idx = len(rows) - 1
    end_left = int(rows[-1]["left_pos"])
    end_right = int(rows[-1]["right_pos"])
    
    for i in range(len(rows) - 1, max(0, 0), -1):
        if i == 0:
            break
        curr_left = int(rows[i]["left_pos"])
        curr_right = int(rows[i]["right_pos"])
        
        # Check if position has deviated from the end position
        if abs(curr_left - end_left) > STATIONARY_THRESHOLD or abs(curr_right - end_right) > STATIONARY_THRESHOLD:
            last_moving_idx = min(len(rows) - 1, i + buffer_samples)  # Keep small buffer after movement
            logger.info(f"Last significant movement at sample {i}: ({curr_left},{curr_right}) → ({end_left},{end_right})")
            break
    
    if first_moving_idx >= last_moving_idx:
        logger.warning(f"No significant movement detected in {csv_path}, keeping all data")
        return
    
    trimmed_rows = rows[first_moving_idx:last_moving_idx + 1]
    if first_moving_idx > 0 or last_moving_idx < len(rows) - 1:
        trimmed_count_start = first_moving_idx
        trimmed_count_end = len(rows) - last_moving_idx - 1
        logger.info(f"Trimming {trimmed_count_start} samples from start, {trimmed_count_end} from end of {csv_path}")
        logger.info(f"Kept {len(trimmed_rows)}/{len(rows)} samples")
        
        t_offset = int(trimmed_rows[0]["t_ms"])
        for row in trimmed_rows:
            row["t_ms"] = str(int(row["t_ms"]) - t_offset)
        
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["t_ms", "left_pos", "right_pos"])
            writer.writeheader()
            for row in trimmed_rows:
                writer.writerow(row)
    else:
        logger.info(f"No stationary data to trim from {csv_path}")

async def record_motor_path(name: str):
    """
    Record motor path for the specified motor.
    """
    global MOTOR_OPERATION_ACTIVE
    background_tasks.add(asyncio.current_task())
    
    if MOCK:
        logger.info("Mock mode - skipping motor path recording")
        background_tasks.remove(asyncio.current_task())
        return
    
    # Lock the lid during motor operation
    MOTOR_OPERATION_ACTIVE = True
    logger.info("Motor operation started - lid locked")
    
    try:
        os.makedirs("motor_paths", exist_ok=True)
        
        if os.path.exists(f"motor_paths/events_{name}.csv"):
            logger.warning(f"Motor path events {name} already exists and will be overwritten.")
            os.remove(f"motor_paths/events_{name}.csv")
        if os.path.exists(f"motor_paths/samples_{name}.csv"):
            logger.warning(f"Motor path samples {name} already exists and will be overwritten.")
            os.remove(f"motor_paths/samples_{name}.csv")
            
        events = open(f"motor_paths/events_{name}.csv", "w", newline="")
        positions = open(f"motor_paths/samples_{name}.csv", "w", newline="")
        events_writer = csv.writer(events)
        events_writer.writerow(["t_us","enc","A","B","delta","pos"])
        positions_writer = csv.writer(positions)
        positions_writer.writerow(["t_ms","left_pos","right_pos"])  # Changed to t_ms to match path_replay.py

        logger.info(f"Recording motor path for {name}")
        encL.bind_event_writer(events_writer, events)
        encR.bind_event_writer(events_writer, events)
        period = 1.0 / SAMPLE_HZ
        t0 = time.time()  # Start time for relative timestamps
        try:
            while True:
                t_ms = int((time.time() - t0) * 1000)  # Milliseconds since start
                positions_writer.writerow([t_ms, encL.pos, encR.pos])
                positions.flush()
                await asyncio.sleep(period)
        except asyncio.CancelledError:
            logger.info(f"Recording task for {name} stopped, saving path...")
        finally:
            events.flush()
            positions.flush()
            events.close()
            positions.close()
            encL.bind_event_writer(None, None)
            encR.bind_event_writer(None, None)
            
            samples_file = f"motor_paths/samples_{name}.csv"
            try:
                logger.info(f"Starting trim of {samples_file}...")
                await asyncio.get_event_loop().run_in_executor(None, trim_stationary_data, samples_file)
                logger.info(f"Trim completed for {samples_file}")
            except Exception as e:
                logger.error(f"Failed to trim stationary data: {e}")
            
            logger.info(f"Motor path recording for {name} saved and closed")
    finally:
        # Unlock the lid when motor operation is done
        MOTOR_OPERATION_ACTIVE = False
        logger.info("Motor operation finished - lid unlocked")
        background_tasks.discard(asyncio.current_task())

async def play_motor_path(name: str, reverse: bool = False):
    """
    Play back recorded motor path for the specified motor.
    """
    global MOTOR_OPERATION_ACTIVE
    
    def clamp(value, min_value, max_value):
        return max(min_value, min(value, max_value))
    
    background_tasks.add(asyncio.current_task())
    
    if MOCK:
        logger.info("Mock mode - skipping motor path playback")
        background_tasks.remove(asyncio.current_task())
        return
    
    async def turn_180(motor_controller):
        logger.info("Executing 180-degree turn maneuver")
        motor_controller.set_speed(1, 380 * -1)
        motor_controller.set_speed(2, 380 * MOTOR_DIR_R)
        await asyncio.sleep(10)
        motor_controller.set_speed(1, 0)
        motor_controller.set_speed(2, 0)
        motor_controller.coast_now()
        logger.info("180-degree turn maneuver complete")
    # Lock the lid during motor operation
    MOTOR_OPERATION_ACTIVE = True
    logger.info("Motor operation started - lid locked")
    
    try:
        events_file = f"motor_paths/events_{name}.csv"
        samples_file = f"motor_paths/samples_{name}.csv"
        if not os.path.exists(events_file) or not os.path.exists(samples_file):
            logger.error(f"Motor path files for {name} not found.")
            return

        logger.info(f"Playing back motor path for {name} (Going to dock={reverse})")
        sample_rows = []
        with open(samples_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                t = int(row["t_ms"])  # Changed from t_us to t_ms
                L = int(row["left_pos"])
                R = int(row["right_pos"])
                sample_rows.append((t, L, R))
            if len(sample_rows) < 2:
                logger.error(f"No samples found in {samples_file}")
                return
        vL_prev, vR_prev = 0, 0
        if reverse:
            sample_rows = list(reversed(sample_rows))
        
        logger.info(f"Starting playback: {len(sample_rows)} samples, reverse={reverse}")
        logger.info(f"Playback config: SPEED_SCALE={SPEED_SCALE}, MAX_PWM={MAX_PWM}, SMOOTH_ALPHA={SMOOTH_ALPHA}")
        logger.info(f"Motor DIR config: MOTOR_DIR_L={MOTOR_DIR_L}, MOTOR_DIR_R={MOTOR_DIR_R}")
        
        try:
            # Ensure motor controller is properly configured before playback
            motor_controller.reinitialize()
            motor_controller.clear_reset_flag() 
            motor_controller.clear_motor_fault()
            for ch in (1, 2):
                motor_controller.set_max_acceleration(ch, ACC)
                motor_controller.set_max_deceleration(ch, DEC)
                motor_controller.set_braking(ch, 0)
            motor_controller.set_command_timeout_milliseconds(1000)
            
            # Verify motor controller is responding
            try:
                status = motor_controller.get_status_flags()
                logger.info(f"Motor controller status: 0x{status:04X}")
                if status & 0x0004:  # Protocol error bit
                    logger.warning("Motor controller protocol error detected")
                if status & 0x0080:  # Command timeout bit
                    logger.warning("Motor controller had command timeout")
            except Exception as e:
                logger.warning(f"Could not read motor controller status: {e}")
            
            logger.info("Motor controller reinitialized for playback")
            
            motor_controller.set_speed(1,0)
            motor_controller.set_speed(2,0)
            await asyncio.sleep(0.2)

            # Track statistics for debugging
            max_vL, max_vR = 0, 0
            total_distance_L, total_distance_R = 0, 0
            await turn_180(motor_controller)
            for i in range(1, len(sample_rows)):
                t0,L0,R0 = sample_rows[i-1]
                t1,L1,R1 = sample_rows[i]
                dt = max((t1 - t0) / 1000.0, MIN_DT)
                
                dL = (L1 - L0)
                dR = (R1 - R0)
                # if reverse:
                #     dL = -dL
                #     dR = -dR
                
                dL *= MOTOR_DIR_L
                dR *= MOTOR_DIR_R
                
                vL_cmd = clamp(int(dL * SPEED_SCALE), -MAX_PWM, MAX_PWM)
                vR_cmd = clamp(int(dR * SPEED_SCALE), -MAX_PWM, MAX_PWM)
                
                if SMOOTH_ALPHA > 0.0:
                    vL_cmd = int((1.0 - SMOOTH_ALPHA) * vL_prev + SMOOTH_ALPHA * vL_cmd)
                    vR_cmd = int((1.0 - SMOOTH_ALPHA) * vR_prev + SMOOTH_ALPHA * vR_cmd)
                
                # Track statistics
                max_vL = max(max_vL, abs(vL_cmd))
                max_vR = max(max_vR, abs(vR_cmd))
                total_distance_L += abs(dL)
                total_distance_R += abs(dR)
                
                if i % 20 == 0:
                    actual_L = encL.pos if not MOCK else 0
                    actual_R = encR.pos if not MOCK else 0
                    logger.debug(f"Step {i}/{len(sample_rows)}: dL={dL:+4d} dR={dR:+4d} → vL={vL_cmd:+4d} vR={vR_cmd:+4d} | Actual: L={actual_L} R={actual_R}")
                
                motor_controller.set_speed(1, vL_cmd)
                motor_controller.set_speed(2, vR_cmd)
                
                vL_prev = vL_cmd
                vR_prev = vR_cmd
                await asyncio.sleep(dt)
            
            motor_controller.set_speed(1,0)
            motor_controller.set_speed(2,0)
            await asyncio.sleep(0.2)
            motor_controller.coast_now()
            logger.info("Motors set to coast after playback")
            logger.info(f"Playback stats: max_vL={max_vL}, max_vR={max_vR}, total_dist_L={total_distance_L}, total_dist_R={total_distance_R}")
            logger.info(f"Path replay for {name} completed")

        except asyncio.CancelledError:
            logger.info(f"Motor path playback for {name} cancelled, stopping motors...")
            motor_controller.set_speed(1,0)
            motor_controller.set_speed(2,0)
            motor_controller.coast_now()
            raise
            
    finally:
        # Unlock the lid when motor operation is done
        MOTOR_OPERATION_ACTIVE = False
        logger.info("Motor operation finished - lid unlocked")
        await asyncio.sleep(0.2)
        background_tasks.remove(asyncio.current_task())



@app.post("/api/v1/motor/record_path/start")
async def start_recording_path(name: Optional[str] = "default_path"):
    """
    Command to start recording the path for a specific motor.
    
    Returns:
        - message: Status message indicating recording has started
        - name: The name of the motor being recorded
    """
    task = asyncio.create_task(record_motor_path(name))
    return {
        "message": f"Started recording for {name}, call /stop to finish and save the path",
    }
@app.post("/api/v1/motor/record_path/stop")
async def stop_recording_path():
    """
    Command to stop recording the motor path.
    
    Returns:
        - message: Status message indicating recording has stopped
    """
    for task in background_tasks:
        if task.get_coro().__name__ == "record_motor_path":
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.info("Motor path recording task cancelled successfully")
            return {
                "message": "Stopped recording motor path and saved data",
            }
    return {
        "message": "No active motor path recording found",
    }

@app.post("/api/v1/motor/test")
async def test_motors(speed: int = 200, duration: float = 2.0):
    """
    Test motor controller by running motors at specified speed for a duration.
    Useful for diagnosing motor controller issues.
    
    Args:
        speed: PWM speed (-800 to +800, default 200)
        duration: Duration in seconds (default 2.0)
    
    Returns:
        - message: Test result
        - encoder_start: Starting encoder positions
        - encoder_end: Ending encoder positions
        - encoder_delta: Change in encoder positions
    """
    if MOCK:
        return {"message": "Mock mode - skipping motor test"}
    
    try:
        motor_controller.reinitialize()
        motor_controller.clear_reset_flag()
        motor_controller.clear_motor_fault()
        
        for ch in (1, 2):
            motor_controller.set_max_acceleration(ch, ACC)
            motor_controller.set_max_deceleration(ch, DEC)
            motor_controller.set_braking(ch, 0)
        
        motor_controller.set_command_timeout_milliseconds(1000)
        
        status = motor_controller.get_status_flags()
        logger.info(f"Motor controller status before test: 0x{status:04X}")
        
        start_L = encL.pos
        start_R = encR.pos
        
        logger.info(f"Testing motors: speed={speed}, duration={duration}s")
        motor_controller.set_speed(1, speed)
        motor_controller.set_speed(2, speed)
        
        await asyncio.sleep(duration)
        
        motor_controller.set_speed(1, 0)
        motor_controller.set_speed(2, 0)
        await asyncio.sleep(0.2)
        motor_controller.coast_now()
        
        end_L = encL.pos
        end_R = encR.pos
        
        delta_L = end_L - start_L
        delta_R = end_R - start_R
        
        logger.info(f"Motor test complete: L {start_L}→{end_L} (Δ{delta_L}), R {start_R}→{end_R} (Δ{delta_R})")
        
        return {
            "message": "Motor test complete",
            "speed": speed,
            "duration": duration,
            "encoder_start": {"left": start_L, "right": start_R},
            "encoder_end": {"left": end_L, "right": end_R},
            "encoder_delta": {"left": delta_L, "right": delta_R},
            "status": f"0x{status:04X}"
        }
        
    except Exception as e:
        logger.error(f"Motor test failed: {e}")
        return {"message": f"Motor test failed: {e}"}

@app.post("/api/v1/motor/dock")
async def move_to_dock(dock_id: Optional[str] = "default_path"):
    """
    Command bin to move to specified dock.
    
    Args:
        dock_id: Identifier of the target docking station (default: "default_path")
    
    Returns:
        - message: Status message indicating playback has started
        - dock_id: The dock ID that was targeted
    """
    task = asyncio.create_task(play_motor_path(dock_id,reverse=True))
    return {
        "message": f"Would move to dock {dock_id}",
        "dock_id": dock_id,
    }

@app.post("/api/v1/motor/return")
async def return_from_dock(dock_id: Optional[str] = "default_path"):
    """
    Command bin to return from specified dock.
    
    Args:
        dock_id: Identifier of the docking station to return from (default: "default_path")
    
    Returns:
        - message: Status message indicating playback has started
        - dock_id: The dock ID that was targeted
    """
    task = asyncio.create_task(play_motor_path(dock_id,reverse=False))
    return {
        "message": f"Would return from dock {dock_id}",
        "dock_id": dock_id,
    }

@app.post("/api/v1/motor/stop")
async def motor_stop():
    """
    Emergency stop for motor movement.
    
    Returns:
        - message: Confirmation message
    
    Example Response:
        ```json
        {
            "message": "Would stop motor"
        }
        ```
    """
    for task in background_tasks:
        if task.get_coro().__name__ == "play_motor_path":
            task.cancel()
            await task

    return {"message": "motor stopped"}


@app.post("/api/v1/door/open")
async def door_open():
    """
    Command to open the side door.
    
    Returns:
        - message: Status message indicating door action
    
    Example Response:
        ```json
        {
            "message": "Side door opened"
        }
        ```
    """
    retval = {"message": "Side door opened"}
    task = asyncio.create_task(open_door())
    return retval


@app.post("/api/v1/door/close")
async def door_close():
    """
    Command to close the door.
    
    Returns:
        - message: Status message indicating door action
    
    Example Response:
        ```json
        {
            "message": "Would close door"
        }
        ```
    """
    return {"message": "Would close door"}


@app.get("/api/v1/environment/temperature")
async def get_temperature():
    """
    Get internal temperature sensor reading.
    
    Returns:
        - temperature_celsius: Float value of temperature in Celsius
    
    Errors:
        - 503: Invalid temperature reading from sensor
        - 504: Sensor read timeout (disconnected or malfunctioning)
        - 500: Unexpected sensor error
    
    Example Response:
        ```json
        {
            "temperature_celsius": 22.5
        }
        ```
    """
    try:
        if MOCK == 0:
            with open("/sys/bus/iio/devices/iio:device0/in_temp_input", "r") as f:
                temp_raw = int(f.read().strip())
                temp_celsius = temp_raw / 1000.0
        else:
            temp_celsius = 22.5
        return {"temperature_celsius": temp_celsius}
    except FileNotFoundError:
        logger.error("Temperature sensor file not found")
        raise HTTPException(status_code=503, detail="Temperature sensor not available")
    except Exception as e:
        logger.error(f"Error reading temperature: {e}")
        raise HTTPException(status_code=500, detail=f"Temperature sensor error: {e}")


@app.get("/api/v1/environment/humidity")
async def get_humidity():
    """
    Get internal humidity sensor reading.
    
    Returns:
        - humidity_relative: Float value of relative humidity (0-100%)
    
    Errors:
        - 503: Invalid humidity reading from sensor
        - 504: Sensor read timeout (disconnected or malfunctioning)
        - 500: Unexpected sensor error
    
    Example Response:
        ```json
        {
            "humidity_relative": 55.0
        }
        ```
    """
    try:
        if MOCK == 0:
            with open("/sys/bus/iio/devices/iio:device0/in_humidityrelative_input", "r") as f:
                humidity_raw = int(f.read().strip())
                humidity_relative = humidity_raw / 1000.0
        else:
            humidity_relative = 55.0
        return {"humidity_relative": humidity_relative}
    except FileNotFoundError:
        logger.error("Humidity sensor file not found")
        raise HTTPException(status_code=503, detail="Humidity sensor not available")
    except Exception as e:
        logger.error(f"Error reading humidity: {e}")
        raise HTTPException(status_code=500, detail=f"Humidity sensor error: {e}")


@app.get("/api/v1/environment")
async def get_environment():
    """
    Get complete environmental sensor readings (temperature and humidity).
    
    Returns:
        - temperature_celsius: Float value of temperature in Celsius
        - humidity_relative: Float value of relative humidity (0-100%)
        - status: String indicating mock or ok status
    
    Errors:
        - 503: Sensor read failed or returned invalid data
        - 504: Sensor read timeout (disconnected or malfunctioning)
        - 500: Unexpected sensor error
    
    Example Response:
        ```json
        {
            "temperature_celsius": 22.5,
            "humidity_relative": 55.0,
            "status": "ok"
        }
        ```
    """
    try:
        if MOCK == 0:
            with open("/sys/bus/iio/devices/iio:device0/in_temp_input", "r") as f:
                temp_raw = int(f.read().strip())
                temp_celsius = temp_raw / 1000.0
            
            with open("/sys/bus/iio/devices/iio:device0/in_humidityrelative_input", "r") as f:
                humidity_raw = int(f.read().strip())
                humidity_relative = humidity_raw / 1000.0
            
            status = "ok"
        else:
            temp_celsius = 25.0
            humidity_relative = 50.0
            status = "mock"
        
        return {
            "temperature_celsius": temp_celsius,
            "humidity_relative": humidity_relative,
            "status": status
        }
    except FileNotFoundError:
        logger.error("Environmental sensor files not found")
        raise HTTPException(status_code=503, detail="Environmental sensors not available")
    except Exception as e:
        logger.error(f"Error reading environmental sensors: {e}")
        raise HTTPException(status_code=500, detail=f"Environmental sensor error: {e}")


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
    
    Returns:
        - rssi: Integer RSSI value in dBm (typically -30 to -90)
    
    Example Response:
        ```json
        {
            "rssi": -65
        }
        ```
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
    """
    API root endpoint showing service information.
    
    Returns:
        - service: Service name
        - version: API version string
        - node: Bin ID of this node
        - is_master: Boolean indicating if this node is cluster master
    
    Example Response:
        ```json
        {
            "service": "Smart Bin API",
            "version": "1.0.0",
            "node": "BIN-CB9B8676",
            "is_master": true
        }
        ```
    """
    return {
        "service": "Smart Bin API",
        "version": __VERSION__,
        "node": node_state["bin_id"],
        "is_master": node_state["is_master"],
    }


@app.get("/health")
async def health_check():
    """
    Health check endpoint for monitoring service status.
    
    Returns:
        - status: String indicating service health (healthy/unhealthy)
        - background_tasks: Number of active background tasks
        - tasks_running: List of running background task names
    
    Example Response:
        ```json
        {
            "status": "healthy",
            "background_tasks": 3,
            "tasks_running": ["periodic_discovery", "lid_control_task", "occupancy_monitoring_task"]
        }
        ```
    """
    return {
        "status": "healthy",
        "background_tasks": len(background_tasks),
        "tasks_running": [str(task.get_name()) for task in background_tasks]
    }


@app.get("/api/v1/telemetry/preview")
async def preview_telemetry():
    """
    Preview the telemetry payload that will be sent to the webhook.
    Useful for debugging and monitoring.
    
    Returns:
        - bin_id: This node's bin ID
        - timestamp: ISO format timestamp
        - fill_level: Current occupancy percentage
        - battery: Battery level percentage
        - signal_strength: RSSI value
        - temperature: Temperature in Celsius
        - humidity: Relative humidity percentage
        - is_master: Boolean indicating if this node is master
        - master_id: Cluster master bin ID
        - cluster_id: Cluster identifier
    
    Example Response:
        ```json
        {
            "bin_id": "BIN-CB9B8676",
            "timestamp": "2025-10-18T14:23:45.123456",
            "fill_level": 15.82,
            "battery": 100.0,
            "signal_strength": -50,
            "temperature": 25.0,
            "humidity": 50.0,
            "is_master": true,
            "master_id": null,
            "cluster_id": "SOLO-CB9B"
        }
        ```
    """
    current_temp = 25.0
    current_humidity = 50.0
    
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
    
    if node_state["is_master"] and node_state["slaves"]:
        for slave_id in node_state["slaves"]:
            slave_telemetry = {
                "bin_id": slave_id,
                "timestamp": datetime.utcnow().isoformat(),
                "fill_level": 50.0,#mock data for now
                "battery": 85.0,
                "signal_strength": -60,
                "temperature": 24.0,
                "humidity": 48.0,
                "is_master": False,
                "master_id": node_state["bin_id"],
                "cluster_id": node_state["cluster_id"],
                #"location": f"Warehouse A - Slave",
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

