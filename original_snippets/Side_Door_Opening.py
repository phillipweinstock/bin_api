# Import the ServoKit class from the Adafruit PCA9685 library
# This class lets you easily control standard hobby servos using the PCA9685 board
from adafruit_servokit import ServoKit

# Import the time library so we can add delays between servo movements
import time

# Create a ServoKit object for a PCA9685 board with 16 channels (default I2C address = 0x40)
# Each channel can control one servo (0–15)
kit = ServoKit(channels=16)

# Select which servo channel you want to control (here, channel 0 = PWM0)
servo = kit.servo[11]

# Set the servo's total movement range in degrees (default is 180°)
# You can adjust this if your servo has a smaller or larger range (e.g., 90°)
servo.actuation_range = 180

# Print a message to the terminal for confirmation
print("Testing servo with brown=GND, orange=5V, yellow=signal...")

# Continuous loop to sweep the servo back and forth
while True:
    # Sweep servo angle from 0° up to 180° in steps of 10°
    for angle in range(0, 181, 10):
        servo.angle = angle      # Move servo to the specified angle
        time.sleep(0.05)         # Small delay for smooth motion

    # Sweep servo angle from 180° down to 0° in steps of 10°
    for angle in range(180, -1, -10):
        servo.angle = angle      # Move servo back to the specified angle
        time.sleep(0.05)         # Small delay for smooth motion
