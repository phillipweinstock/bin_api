# Code of Servo Motor Integrating with Obstacle Avoidance Sensor Module 
# Using PCA9685 (I2C) - Servo on channel 10

from adafruit_servokit import ServoKit
from gpiozero import DigitalInputDevice
from time import sleep

# --- Setup PCA9685 (I2C servo driver) ---
# The PCA9685 is an external PWM controller that communicates via I²C.
# It has 16 channels (0–15) and each channel can control one servo motor.
# The I²C address (0x40) is the default for most PCA9685 boards.
kit = ServoKit(channels=16, address=0x40)

# --- Select servo channel 10 ---
# This defines the servo motor connected to PWM channel 10 on the PCA9685 board.
# The actuation range is set to 180 degrees to allow full rotation.
servo1 = kit.servo[10]
servo1.actuation_range = 180  # optional (default is already 180°)

# --- Setup digital input sensor on GPIO 26 ---
# The obstacle avoidance sensor module has an OUT pin that becomes LOW (0)
# when it detects an object in front of it, such as a hand.
sensor = DigitalInputDevice(26)

print("System ready. Waiting for sensor trigger...")

try:
    while True:
        # Check the output value of the avoidance sensor
        # sensor.value = 0  → means object/hand detected
        # sensor.value = 1  → means no object detected
        if sensor.value == 0:
            # When sensor output is 0:
            # The system detects a hand near the sensor.
            # Action: Rotate the servo motor to 180° to open the lid.
            print("Sensor triggered! Hand detected — opening lid...")
            servo1.angle = 180     # open the lid
            sleep(5)               # keep lid open for 5 seconds

            # After 5 seconds, return the lid to its closed position.
            print("Returning servo1 to min (0°) — closing lid.")
            servo1.angle = 0       # close the lid

            # Debounce delay — gives some time before the next detection
            # to avoid continuous triggering when the hand is still there.
            sleep(1)

        else:
            # When sensor output is 1:
            # No object detected, keep the lid closed.
            servo1.angle = 0

        # Small delay to stabilize loop readings and avoid CPU overuse
        sleep(0.1)

except KeyboardInterrupt:
    # Graceful exit when user presses Ctrl+C
    print("\nProgram stopped.")
