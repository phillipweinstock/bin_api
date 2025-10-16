import time
import board
import adafruit_dht
from gpiozero import DigitalInputDevice

# --- DHT11 setup (temperature and humidity sensor) ---
# DHT11 connected to GPIO17
dhtDevice = adafruit_dht.DHT11(board.D17)

print("System ready — reading DHT11 sensor...")

while True:
    try:
        # Read temperature (°C) and humidity (%)
        temp_c = dhtDevice.temperature
        humidity = dhtDevice.humidity

        # Print sensor readings
        print(f"Temperature: {temp_c:.1f} °C   Humidity: {humidity:.1f}%")

    except Exception as e:
        print("Sensor error:", e)

    # Delay between readings
    time.sleep(1)
