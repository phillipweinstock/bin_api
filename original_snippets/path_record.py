import os
import csv
import time
from datetime import datetime

import lgpio  # Official GPIO interface for Raspberry Pi 5

# ========= Modify these according to your wiring (BCM pin numbers) =========
LEFT_A, LEFT_B  = 23, 24
RIGHT_A, RIGHT_B = 27, 25
SAMPLE_HZ = 100  # Fixed sampling frequency (recommended 50–200 Hz)
# ==========================================================================

# ========= Optional: try setting the Motoron driver to "Coast" mode (motors unpowered, easy to push manually) =========
def try_put_motoron_to_coast():
    try:
        import motoron
        mc = motoron.MotoronI2C()        # Add address=0x10 if needed
        mc.reinitialize()
        mc.clear_reset_flag()
        # Set braking to 0 (so setting speed=0 won’t apply active braking)
        mc.set_braking(1, 0)
        mc.set_braking(2, 0)
        # Immediately set all motors to Coast (outputs disconnected)
        mc.coast_now()
        # Optionally shorten the command timeout to prevent unintended drive
        mc.set_command_timeout_milliseconds(100)
        print("🔌 Motoron: set to Coast mode (can push or rotate manually).")
    except Exception as e:
        print(f"ℹ Motoron not set to Coast (possibly not connected or library missing): {e}")

# ========= Quadrature Encoder Counter (x4 decoding) =========
class QuadCounter:
    # State transition lookup table: (last, curr) -> +1 / -1 / 0
    TRANS = {
        (0,1):+1,(1,3):+1,(3,2):+1,(2,0):+1,
        (1,0):-1,(3,1):-1,(2,3):-1,(0,2):-1
    }

    def __init__(self, h, a, b, name="enc"):
        self.h = h
        self.a, self.b = a, b
        self.name = name
        self.pos = 0
        # Encoders are push-pull outputs (you already have voltage limiting), so no internal pull-up needed
        lgpio.gpio_claim_input(h, a)
        lgpio.gpio_claim_input(h, b)
        # Enable dual-edge interrupts
        lgpio.gpio_claim_alert(h, a, lgpio.RISING_EDGE | lgpio.FALLING_EDGE)
        lgpio.gpio_claim_alert(h, b, lgpio.RISING_EDGE | lgpio.FALLING_EDGE)
        self.last = ((lgpio.gpio_read(h, a) & 1) << 1) | (lgpio.gpio_read(h, b) & 1)
        lgpio.callback(h, a, lgpio.BOTH_EDGES, self._cb)
        lgpio.callback(h, b, lgpio.BOTH_EDGES, self._cb)
        self.writer_ev = None
        self._fev = None  # File handle for flushing within callback

    def bind_event_writer(self, writer, file_handle):
        """Bind a CSV writer for event logging (used inside callback)."""
        self.writer_ev = writer
        self._fev = file_handle

    def _cb(self, chip, gpio, level, tick):
        """Interrupt callback — handles both edges on A/B and updates position."""
        curr = ((lgpio.gpio_read(self.h, self.a) & 1) << 1) | (lgpio.gpio_read(self.h, self.b) & 1)
        delta = self.TRANS.get((self.last, curr), 0)
        if delta:
            self.pos += delta
            if self.writer_ev:
                # Log each event with a monotonic microsecond timestamp
                t_us = time.monotonic_ns() // 1_000
                a_lvl = (curr >> 1) & 1
                b_lvl = curr & 1
                self.writer_ev.writerow([t_us, self.name, a_lvl, b_lvl, delta, self.pos])
                if self._fev:
                    self._fev.flush()
        self.last = curr

def main():
    # 1) Set Motoron to “Coast” first (so the robot can be pushed manually)
    try_put_motoron_to_coast()

    # 2) Delete old CSV files to ensure path replay reads the latest data
    for p in ("encoder_events.csv", "encoder_samples.csv"):
        try:
            if os.path.exists(p):
                os.remove(p)
                print(f"🧹 Deleted old file: {p}")
        except Exception as e:
            print(f" Failed to delete {p}: {e}")

    # 3) Open gpiochip and initialize encoders
    h = lgpio.gpiochip_open(0)
    encL = QuadCounter(h, LEFT_A, LEFT_B, "L")
    encR = QuadCounter(h, RIGHT_A, RIGHT_B, "R")

    # 4) Open CSV files (fixed filenames)
    ev_path = "encoder_events.csv"
    sa_path = "encoder_samples.csv"
    fev = open(ev_path, "w", newline="")
    fsa = open(sa_path, "w", newline="")
    wrev = csv.writer(fev); wrev.writerow(["t_us","enc","A","B","delta","pos"])
    wrsa = csv.writer(fsa); wrsa.writerow(["t_ms","left_pos","right_pos"])

    # Bind event writers (flush immediately on edge events)
    encL.bind_event_writer(wrev, fev)
    encR.bind_event_writer(wrev, fev)

    print(" Start recording (motors are in Coast mode: can push or rotate manually). Press Ctrl+C to stop.")
    print("Event log:", os.path.abspath(ev_path))
    print("Sample log:", os.path.abspath(sa_path))

    # 5) Sampling loop
    period = 1.0 / SAMPLE_HZ
    t0 = time.time()
    try:
        while True:
            t_ms = int((time.time() - t0) * 1000)
            wrsa.writerow([t_ms, encL.pos, encR.pos])
            fsa.flush()  # Flush every sample to avoid data loss on power failure
            time.sleep(period)
    except KeyboardInterrupt:
        print("\n Saving data...")
    finally:
        fev.close(); fsa.close()
        lgpio.gpiochip_close(h)
        print(" Data saved:", ev_path, "and", sa_path)

if __name__ == "__main__":
    main()
