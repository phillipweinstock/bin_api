import csv
import time
from motoron import MotoronI2C

# ======== Adjustable Parameters ========
MOTORON_ADDR = None   # None = default 0x14; use 0x10 if your board is set to that address
MAX_PWM = 800
ACC = 150
DEC = 150
SPEED_SCALE = 13      # PWM scaling factor (tune for your system)
SMOOTH_ALPHA = 0.5    # Exponential smoothing factor 0–1
MIN_DT = 0.005
CSV_PATH = "encoder_samples.csv"

# ★★★ Direction Correction (Important) ★★★
# If the replay runs in the opposite direction from the recording,
# set the corresponding side(s) to -1.
# Try -1, -1 first; if that’s wrong, flip only one side.
MOTOR_DIR_L = -1
MOTOR_DIR_R = -1
# =======================================

def clamp(x, lo, hi):
    return max(lo, min(x, hi))

def ask_bool(prompt, default=False):
    s = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    if s == "":
        return default
    return s in ("y", "yes", "1", "true", "t")

def ask_float(prompt, default):
    s = input(f"{prompt} [default {default}]: ").strip()
    return float(s) if s else float(default)

def load_samples(csv_path):
    rows = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            t = int(r["t_ms"])
            L = int(r["left_pos"])
            R = int(r["right_pos"])
            rows.append((t, L, R))
    if len(rows) < 2:
        raise RuntimeError("CSV data insufficient — at least 2 rows required.")
    return rows

def init_motoron(addr=None):
    mc = MotoronI2C() if addr is None else MotoronI2C(address=addr)
    mc.reinitialize()
    mc.clear_reset_flag()
    mc.clear_motor_fault()
    for ch in (1, 2):
        mc.set_max_acceleration(ch, ACC)
        mc.set_max_deceleration(ch, DEC)
        mc.set_braking(ch, 0)  # no electronic braking when stopped
    mc.coast_now()
    return mc

def main():
    print(" Reading CSV:", CSV_PATH)
    rows = load_samples(CSV_PATH)
    print(f" Loaded {len(rows)} rows.")

    reverse = ask_bool("Replay backward (return to start)?", default=False)
    k = ask_float("Tick→PWM scaling factor k (recommended 100–300)", SPEED_SCALE)

    if reverse:
        rows = list(reversed(rows))
        print(" Reverse playback enabled.")

    print(f" Direction factors: Left={MOTOR_DIR_L}, Right={MOTOR_DIR_R} "
          f"(change to +1 or -1 if directions are incorrect)")

    print(" Initializing Motoron ...")
    mc = init_motoron(MOTORON_ADDR)
    print(" Motoron ready. Press Ctrl+C to stop.")

    vL_prev = 0.0
    vR_prev = 0.0

    try:
        mc.set_speed(1, 0)
        mc.set_speed(2, 0)
        time.sleep(0.2)

        for i in range(1, len(rows)):
            t0, L0, R0 = rows[i - 1]
            t1, L1, R1 = rows[i]
            dt = max((t1 - t0) / 1000.0, MIN_DT)

            dL = (L1 - L0)
            dR = (R1 - R0)
            if reverse:
                dL, dR = -dL, -dR

            # === Apply direction correction here ===
            dL *= MOTOR_DIR_L
            dR *= MOTOR_DIR_R

            vL_cmd = clamp(int(dL * k), -MAX_PWM, MAX_PWM)
            vR_cmd = clamp(int(dR * k), -MAX_PWM, MAX_PWM)

            if SMOOTH_ALPHA > 0.0:
                vL_cmd = int((1.0 - SMOOTH_ALPHA) * vL_prev + SMOOTH_ALPHA * vL_cmd)
                vR_cmd = int((1.0 - SMOOTH_ALPHA) * vR_prev + SMOOTH_ALPHA * vR_cmd)

            mc.set_speed(1, vL_cmd)
            mc.set_speed(2, vR_cmd)

            vL_prev, vR_prev = vL_cmd, vR_cmd
            time.sleep(dt)

        mc.set_speed(1, 0)
        mc.set_speed(2, 0)
        time.sleep(0.2)
        mc.coast_now()
        print(" Path replay complete.")

    except KeyboardInterrupt:
        print("\n⏹ Interrupted by user — stopping motors ...")
        try:
            mc.set_speed(1, 0)
            mc.set_speed(2, 0)
            time.sleep(0.2)
            mc.coast_now()
        except Exception:
            pass

if __name__ == "__main__":
    main()
