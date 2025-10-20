import os
import csv
import time
from datetime import datetime

import lgpio  # Official GPIO interface for Raspberry Pi 5

# ========= GPIO mapping (BCM numbering) =========
LEFT_A, LEFT_B  = 23, 24
RIGHT_A, RIGHT_B = 27, 25
SAMPLE_HZ = 100  # Sampling frequency (recommended 50–200 Hz)
# ===============================================

# ========= Optional: Set Motoron to Coast mode (for free rotation) =========
def try_put_motoron_to_coast():
    """
    If the Motoron library and hardware are available:
      - Reinitialize the controller
      - Clear reset flag
      - Set braking to zero
      - Immediately switch all channels to Coast mode (freewheel)
    If not connected or not installed, this call will be safely ignored.
    """
    try:
        import motoron
        mc = motoron.MotoronI2C()        # Specify address if needed (e.g., address=0x10)
        mc.reinitialize()
        mc.clear_reset_flag()
        mc.set_braking(1, 0)
        mc.set_braking(2, 0)
        mc.coast_now()
        mc.set_command_timeout_milliseconds(100)
        print("🔌 Motoron: set to Coast (motors free to spin).")
    except Exception as e:
        print(f"ℹ️ Motoron not set to Coast (not connected or library missing): {e}")

# ========= Quadrature encoder counter (x4 decoding) =========
class QuadCounter:
    # Transition table: (last_state, current_state) -> +1 / -1 / 0
    TRANS = {
        (0,1):+1,(1,3):+1,(3,2):+1,(2,0):+1,
        (1,0):-1,(3,1):-1,(2,3):-1,(0,2):-1
    }

    def __init__(self, h, a, b, name="enc"):
        self.h = h
        self.a, self.b = a, b
        self.name = name
        self.pos = 0
        # Encoder outputs are push-pull; no internal pull-ups required
        lgpio.gpio_claim_input(h, a)
        lgpio.gpio_claim_input(h, b)
        # Enable edge alerts on both channels
        lgpio.gpio_claim_alert(h, a, lgpio.RISING_EDGE | lgpio.FALLING_EDGE)
        lgpio.gpio_claim_alert(h, b, lgpio.RISING_EDGE | lgpio.FALLING_EDGE)
        self.last = ((lgpio.gpio_read(h, a) & 1) << 1) | (lgpio.gpio_read(h, b) & 1)
        lgpio.callback(h, a, lgpio.BOTH_EDGES, self._cb)
        lgpio.callback(h, b, lgpio.BOTH_EDGES, self._cb)
        self.writer_ev = None
        self._fev = None  # event-file handle for flushing inside callback

    def bind_event_writer(self, writer, file_handle):
        self.writer_ev = writer
        self._fev = file_handle

    def _cb(self, chip, gpio, level, tick):
        curr = ((lgpio.gpio_read(self.h, self.a) & 1) << 1) | (lgpio.gpio_read(self.h, self.b) & 1)
        delta = self.TRANS.get((self.last, curr), 0)
        if delta:
            self.pos += delta
            if self.writer_ev:
                # Use monotonic clock (µs) for timestamp
                t_us = time.monotonic_ns() // 1_000
                a_lvl = (curr >> 1) & 1
                b_lvl = curr & 1
                self.writer_ev.writerow([t_us, self.name, a_lvl, b_lvl, delta, self.pos])
                if self._fev:
                    self._fev.flush()
        self.last = curr

def main():
    # 1) Put Motoron into Coast mode (so motors spin freely)
    try_put_motoron_to_coast()

    # 2) Delete any old CSVs to ensure replay uses the newest data
    for p in ("encoder_events.csv", "encoder_samples.csv"):
        try:
            if os.path.exists(p):
                os.remove(p)
                print(f" Deleted old file: {p}")
        except Exception as e:
            print(f" Failed to delete {p}: {e}")

    # 3) Open gpiochip and initialize encoders
    h = lgpio.gpiochip_open(0)
    encL = QuadCounter(h, LEFT_A, LEFT_B, "L")
    encR = QuadCounter(h, RIGHT_A, RIGHT_B, "R")

    # 4) Open CSV files (fixed names)
    ev_path = "encoder_events.csv"
    sa_path = "encoder_samples.csv"
    fev = open(ev_path, "w", newline="")
    fsa = open(sa_path, "w", newline="")
    wrev = csv.writer(fev); wrev.writerow(["t_us","enc","A","B","delta","pos"])
    wrsa = csv.writer(fsa); wrsa.writerow(["t_ms","left_pos","right_pos"])

    # Bind event writer for immediate flush on every edge
    encL.bind_event_writer(wrev, fev)
    encR.bind_event_writer(wrev, fev)

    print(" Recording started (motors in Coast mode; can push/rotate freely). Press Ctrl+C to stop.")
    print("Event log:", os.path.abspath(ev_path))
    print("Sample log:", os.path.abspath(sa_path))

    # 5) Sampling loop
    period = 1.0 / SAMPLE_HZ
    t0 = time.time()
    try:
        while True:
            t_ms = int((time.time() - t0) * 1000)
            wrsa.writerow([t_ms, encL.pos, encR.pos])
            fsa.flush()  # flush every frame to protect data on power loss
            time.sleep(period)
    except KeyboardInterrupt:
        print("\n Saving data ...")
    finally:
        fev.close(); fsa.close()
        lgpio.gpiochip_close(h)
        print(" Saved:", ev_path, "and", sa_path)

if __name__ == "__main__":
    main()
