# flexiforce_mcp3008_weight.py
import spidev
import time

# --- SPI setup ---
spi = spidev.SpiDev()
spi.open(0, 0)                  # Bus 0, device 0 (CE0)
spi.max_speed_hz = 1350000

# --- MCP3008 read function ---
def read_adc(channel=0):
    """Read one channel (0–7) from MCP3008"""
    if not 0 <= channel <= 7:
        raise ValueError("Channel must be 0–7")
    adc = spi.xfer2([1, (8 + channel) << 4, 0])
    value = ((adc[1] & 3) << 8) + adc[2]
    return value

# --- Convert ADC value to voltage ---
def adc_to_voltage(adc_val, vref=3.3):
    return (adc_val * vref) / 1023

# --- Example calibration (adjust after testing) ---
# Collect real ADC readings with known weights and update slope/intercept below.
# e.g. 0 kg → ADC ≈ 10; 5 kg → ADC ≈ 500 → slope ≈ (5-0)/(500-10) ≈ 0.0102
SLOPE = 0.0102      # kg per ADC count
INTERCEPT = -0.1    # kg offset (adjust to make 0 kg read ~0)

def estimate_weight(adc_val):
    return max(0.0, SLOPE * adc_val + INTERCEPT)

try:
    print("📟 FlexiForce A201 (MCP3008 SPI) — reading live data...")
    print("Press Ctrl+C to stop.\n")
    while True:
        raw = read_adc(0)
        voltage = adc_to_voltage(raw)
        weight = estimate_weight(raw)
        print(f"ADC={raw:4d} | {voltage:4.2f} V | ~{weight:4.2f} kg")
        time.sleep(0.3)

except KeyboardInterrupt:
    print("\nStopped.")
finally:
    spi.close()
