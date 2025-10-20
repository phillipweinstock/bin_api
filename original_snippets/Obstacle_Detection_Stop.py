import motoron
import time
import lgpio as GPIO

# ---------------- Configuration Section (modifiable) ----------------
TRIG_B = 14
ECHO_B = 15

MOTOR_LEFT = 1
MOTOR_RIGHT = 2

# Reverse the left motor; if you want to reverse the right motor instead,
# set this to False and change the corresponding sign below.
REVERSE_LEFT = True

CRUISE_SPEED = 150          # Normal driving speed (-800~800, smaller means slower)
OBSTACLE_CM = 15            # Obstacle detection threshold (cm)
READ_INTERVAL_S = 0.2       # Sampling interval (seconds)

# Echo timeout settings (to prevent infinite waiting when ultrasonic fails)
ECHO_RISE_TIMEOUT_S = 0.02  # Timeout for echo rising edge (20 ms)
ECHO_FALL_TIMEOUT_S = 0.02  # Timeout for echo falling edge (20 ms)

# ---------------- GPIO Setup ----------------
h = GPIO.gpiochip_open(0)
GPIO.gpio_claim_output(h, TRIG_B)
GPIO.gpio_claim_input(h, ECHO_B)
GPIO.gpio_write(h, TRIG_B, 0)  # Set TRIG low initially

# ---------------- Motoron Setup ----------------
mc = motoron.MotoronI2C(address=0x10)
mc.reinitialize()
mc.clear_reset_flag()
mc.clear_motor_fault()

# Smooth acceleration and deceleration
mc.set_max_acceleration(MOTOR_LEFT, 80)
mc.set_max_deceleration(MOTOR_LEFT, 80)
mc.set_max_acceleration(MOTOR_RIGHT, 80)
mc.set_max_deceleration(MOTOR_RIGHT, 80)

def set_two_motors(speed):
    """
    Set both motors’ speed; reverse the left motor if REVERSE_LEFT is True.
    Motoron speed range is approximately -800..800, where the sign controls direction.
    """
    left_speed = -speed if REVERSE_LEFT else speed
    right_speed = speed
    mc.set_speed(MOTOR_LEFT, left_speed)
    mc.set_speed(MOTOR_RIGHT, right_speed)

def stop_motors():
    """Stop both motors."""
    mc.set_speed(MOTOR_LEFT, 0)
    mc.set_speed(MOTOR_RIGHT, 0)

# ---------------- Distance Measurement Function ----------------
def get_distance(trig, echo):
    """Measure distance using the ultrasonic sensor (unit: cm)."""
    GPIO.gpio_write(h, trig, 0)
    time.sleep(0.000002)
    GPIO.gpio_write(h, trig, 1)
    time.sleep(0.00001)
    GPIO.gpio_write(h, trig, 0)

    t0 = time.time()
    while GPIO.gpio_read(h, echo) == 0:
        if time.time() - t0 > ECHO_RISE_TIMEOUT_S:
            return float("inf")

    pulse_start = time.time()

    t1 = time.time()
    while GPIO.gpio_read(h, echo) == 1:
        if time.time() - t1 > ECHO_FALL_TIMEOUT_S:
            return float("inf")

    pulse_end = time.time()

    pulse_duration = pulse_end - pulse_start
    distance_cm = pulse_duration * 17150.0
    return round(distance_cm, 2)

# ---------------- Main Loop ----------------
print(" Automatic operation started: moving forward; stop if an obstacle <15 cm is detected.")
try:
    while True:
        distB = get_distance(TRIG_B, ECHO_B)
        if distB == float("inf"):
            print("Ultrasonic B: No valid echo (treated as far away).")
        else:
            print(f"Ultrasonic B Distance = {distB:.2f} cm")

        if distB < OBSTACLE_CM:
            print(" Obstacle detected nearby — stopping motors!")
            stop_motors()
        else:
            set_two_motors(CRUISE_SPEED)

        time.sleep(READ_INTERVAL_S)

except KeyboardInterrupt:
    print("\n Keyboard interrupt received — safely stopping and cleaning up...")
    stop_motors()
finally:
    try:
        stop_motors()
    except Exception:
        pass
    GPIO.gpiochip_close(h)
    print(" GPIO closed, program ended.")
