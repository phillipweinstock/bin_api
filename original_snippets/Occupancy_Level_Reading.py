# ----------------------------------------------------------------------
# This code reads the ultrasonic sensor reading and computes
# the occupancy level (%) of a bin between 18 cm (full) and 32 cm (empty).
# It uses a median filter to smooth noisy readings.
# ----------------------------------------------------------------------

import lgpio as GPIO       # Import lgpio library for low-level GPIO access
import time                # For delays and timing measurements
import statistics           # For computing median of sample readings

# ----------------------- Pin Definitions ------------------------------
TRIG = 22   # GPIO pin connected to the ultrasonic sensor's TRIG
ECHO = 16   # GPIO pin connected to the ultrasonic sensor's ECHO

# ----------------------- GPIO Setup -----------------------------------
h = GPIO.gpiochip_open(0)          # Open GPIO chip 0 (main GPIO controller)
GPIO.gpio_claim_output(h, TRIG)    # Set TRIG pin as output
GPIO.gpio_claim_input(h, ECHO)     # Set ECHO pin as input

# ----------------------- Constants ------------------------------------
MAX_DISTANCE = 32.0   # (cm) Distance when bin is completely empty
MIN_DISTANCE = 18.0   # (cm) Distance when bin is full / overloaded
TIMEOUT = 0.02        # (s) 20 ms timeout to avoid infinite waiting loops
SAMPLE_COUNT = 5      # Number of readings used for median filtering

# ----------------------------------------------------------------------
# Function: get_distance()
# Purpose : Take a single distance measurement using the ultrasonic sensor.
# ----------------------------------------------------------------------
def get_distance():
    """Measure one distance reading from ultrasonic sensor."""
    
    # Ensure TRIG pin is LOW before starting (for sensor stability)
    GPIO.gpio_write(h, TRIG, 0)
    time.sleep(0.002)

    # Send a 10 microsecond HIGH pulse to TRIG to trigger the sensor
    GPIO.gpio_write(h, TRIG, 1)
    time.sleep(0.00001)
    GPIO.gpio_write(h, TRIG, 0)

    # ---------------- Wait for Echo to go HIGH -----------------
    timeout_start = time.time()   # Record start time for timeout handling
    while GPIO.gpio_read(h, ECHO) == 0:  # Wait for rising edge
        pulse_start = time.time()         # Mark when pulse starts
        if time.time() - timeout_start > TIMEOUT:  # Timeout condition
            return None  # No echo received — exit with None

    # ---------------- Wait for Echo to go LOW ------------------
    while GPIO.gpio_read(h, ECHO) == 1:   # Wait for falling edge
        pulse_end = time.time()           # Mark when pulse ends
        if time.time() - pulse_start > TIMEOUT:  # Timeout condition
            return None  # Echo too long — exit with None

    # Calculate the pulse duration in seconds
    pulse_duration = pulse_end - pulse_start

    # Convert duration to distance (cm)
    # Formula: distance = time * (speed of sound / 2)
    # Speed of sound = 34300 cm/s, divide by 2 for round trip
    distance = pulse_duration * 17150

    return round(distance, 2)  # Return value rounded to 2 decimal places


# ----------------------------------------------------------------------
# Function: get_filtered_distance()
# Purpose : Take multiple distance readings and return the median value.
#           Median filtering helps remove outliers and noise.
# ----------------------------------------------------------------------
def get_filtered_distance(samples=SAMPLE_COUNT):
    """Take multiple readings and return median value."""
    readings = []  # List to store successful readings

    for _ in range(samples):
        d = get_distance()  # Get one reading
        if d is not None:   # Only keep valid (non-timeout) values
            readings.append(d)
        time.sleep(0.05)    # Small delay between samples

    # Return median of collected readings (or None if no valid readings)
    return round(statistics.median(readings), 2) if readings else None


# ----------------------------------------------------------------------
# Function: compute_occupancy()
# Purpose : Convert measured distance into occupancy percentage.
#           Full = 18 cm (100%), Empty = 32 cm (0%).
# ----------------------------------------------------------------------
def compute_occupancy(distance):
    """Compute occupancy as a percentage using 18–32 cm range."""
    if distance is None:  # Handle invalid readings
        return None

    # Clamp distance to valid range (18–32 cm)
    if distance > MAX_DISTANCE:
        distance = MAX_DISTANCE
    if distance < MIN_DISTANCE:
        distance = MIN_DISTANCE

    # Linear mapping: ((MAX - distance) / (MAX - MIN)) × 100%
    # Here, MAX - MIN = 13 cm (32 - 19 = 13)
    occupancy = ((MAX_DISTANCE - distance) / 13.0) * 100
    return round(occupancy, 2)


# ----------------------------------------------------------------------
# Main Loop
# Continuously measure the distance, filter it, and compute occupancy.
# Displays an alert when the bin is overloaded (below 18 cm).
# ----------------------------------------------------------------------
if __name__ == '__main__':
    try:
        while True:
            # Obtain a median-filtered distance reading
            dist = get_filtered_distance()

            if dist is not None:
                # Compute occupancy %
                occ = compute_occupancy(dist)

                # Calculate difference from minimum distance (for debug info)
                diff = round(dist - MIN_DISTANCE, 2)

                # Print alert if the bin is overfilled (distance < 18 cm)
                if dist < MIN_DISTANCE:
                    print(f"⚠️ ALERT: Bin Overload! Distance: {dist:.2f} cm | (dist - 18cm) = {diff:.2f} cm | Occupancy: 100%")
                else:
                    # Otherwise, show normal occupancy reading
                    print(f"Distance: {dist:.2f} cm | (dist - 18cm) = {diff:.2f} cm | Occupancy: {occ:.2f}%")
            else:
                # Timeout / invalid reading
                print("No echo detected (timeout)")

            time.sleep(1)  # Delay before next reading

    except KeyboardInterrupt:
        # Gracefully exit when user presses Ctrl + C
        print("\nMeasurement stopped by User.")
        GPIO.gpiochip_close(h)  # Close GPIO handle to release pins
