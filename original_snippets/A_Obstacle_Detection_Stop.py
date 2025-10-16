import motoron
import time
import lgpio as GPIO

# ------------------------------------------------------------
# This program is used to detect any obstacle in front of the bin.
# If the ultrasonic sensor detects an object within 15 cm,
# the wheels (controlled by the Motoron driver) will stop.
# Otherwise, the wheels keep running forward.
# ------------------------------------------------------------

# ---------------- Ultrasonic Pins ----------------
TRIG_B = 14   # Trigger pin for ultrasonic sensor
ECHO_B = 15   # Echo pin for ultrasonic sensor

# ---------------- GPIO Setup ----------------
h = GPIO.gpiochip_open(0)
GPIO.gpio_claim_output(h, TRIG_B)
GPIO.gpio_claim_input(h, ECHO_B)

# ---------------- Motoron Setup ----------------
# Motoron Motor Controller (I2C address 0x10)
mc = motoron.MotoronI2C(address=0x10)
mc.reinitialize()
mc.clear_reset_flag()
mc.clear_motor_fault()

# Configure motor acceleration and deceleration limits
mc.set_max_acceleration(1, 100)
mc.set_max_deceleration(1, 100)
mc.set_max_acceleration(2, 100)
mc.set_max_deceleration(2, 100)

# ---------------- Distance Function ----------------
def get_distance(trig, echo):
    """
    Measure distance using the ultrasonic sensor.
    Sends a 10 µs pulse and calculates distance based on echo time.
    Returns the distance in centimeters.
    """
    # Ensure TRIG is LOW
    GPIO.gpio_write(h, trig, 0)
    time.sleep(0.000002)

    # Send 10 µs pulse to TRIG
    GPIO.gpio_write(h, trig, 1)
    time.sleep(0.00001)
    GPIO.gpio_write(h, trig, 0)

    # Wait for echo to start and end
    pulse_start = time.time()
    while GPIO.gpio_read(h, echo) == 0:
        pulse_start = time.time()

    pulse_end = time.time()
    while GPIO.gpio_read(h, echo) == 1:
        pulse_end = time.time()

    # Calculate distance (speed of sound = 34300 cm/s → divide by 2)
    pulse_duration = pulse_end - pulse_start
    distance = pulse_duration * 17150
    return round(distance, 2)

# ---------------- Main Loop ----------------
print("🚀 Automatic operation started: Motor runs until obstacle <15 cm detected...")

while True:
    try:
        # Measure distance from Ultrasonic Sensor B
        distB = get_distance(TRIG_B, ECHO_B)
        print(f"Ultrasonic B Distance = {distB:.2f} cm")

        # ---------------- Motor Control Logic ----------------
        # If an obstacle is detected within 15 cm, stop both motors.
        if distB < 15:
            print("⚠️  Obstacle detected — stopping motors!")
            mc.set_speed(1, 0)
            mc.set_speed(2, 0)
        else:
            # Otherwise, move both wheels forward at speed 400.
            speed = 400
            mc.set_speed(1, speed)
            mc.set_speed(2, speed)

    except Exception as e:
        print("Sensor error:", e)

    # Delay before next reading
    time.sleep(1)
