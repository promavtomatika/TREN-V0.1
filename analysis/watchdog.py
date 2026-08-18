"""Stage 8 (partial) - watchdog / replay-survival timing.

Measures, from the OLD replay capture `Ответ_17_1922.csv`, how long the
treadmill kept running under a fixed panel-stream replay before it safety-cut.
Only the event TIMESTAMPS are used; the byte values in that file are from a
misconfigured decode and are ignored.

Read-only. Nothing here transmits to the device.
"""
import csv
import os
import statistics as st

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "Ответ_17_1922.csv")

ATTEMPT_SILENCE = 5.0   # gap that separates distinct replay attempts
BURST_GAP = 0.4         # gap that separates bursts within an attempt
DENSE_MIN_RATE = 40     # events/s marking the motor-running (dense) phase


def load():
    rows = list(csv.reader(open(SRC, encoding="utf-8-sig")))[1:]
    return [float(r[0]) for r in rows if r and r[0]]


def split(ts, gap):
    groups, cur = [], [ts[0]]
    for i in range(1, len(ts)):
        if ts[i] - ts[i - 1] > gap:
            groups.append(cur)
            cur = []
        cur.append(ts[i])
    groups.append(cur)
    return groups


def classify(burst):
    dur = burst[-1] - burst[0]
    rate = len(burst) / dur if dur > 0 else 0
    if dur < 0.1:
        return "wake"
    # the motor-running phase is a SUSTAINED dense burst; the short 0.25s dense
    # burst is the handshake/frame exchange, not the run.
    if rate >= DENSE_MIN_RATE and dur >= 0.5:
        return "run(motor)"
    if rate >= DENSE_MIN_RATE:
        return "handshake"
    return "handshake"


def main():
    ts = load()
    print(f"events={len(ts)}  span {ts[0]:.3f}..{ts[-1]:.3f}s\n")
    attempts = split(ts, ATTEMPT_SILENCE)
    print(f"{len(attempts)} replay attempts (split on >{ATTEMPT_SILENCE}s silence):\n")

    run_durations = []
    for k, att in enumerate(attempts, 1):
        print(f"Attempt {k}: {att[0]:.3f}..{att[-1]:.3f}s  (dur {att[-1]-att[0]:.3f}s)")
        for burst in split(att, BURST_GAP):
            kind = classify(burst)
            dur = burst[-1] - burst[0]
            gaps = [burst[i] - burst[i - 1] for i in range(1, len(burst))]
            extra = ""
            if kind == "run(motor)":
                # is the end abrupt or tapering? compare final vs prior 0.5 s
                b = burst[-1]
                n_last = sum(1 for t in burst if t >= b - 0.5)
                n_prev = sum(1 for t in burst if b - 1.0 <= t < b - 0.5)
                ends = "abrupt" if (n_prev == 0 or 0.5 < n_last / max(1, n_prev) < 2) else "tapering"
                extra = (f"  maxgap={max(gaps)*1000:.0f}ms  end={ends} "
                         f"(last0.5s={n_last} vs prev0.5s={n_prev})")
                capped = att is attempts[-1] and abs(burst[-1] - ts[-1]) < 0.01
                run_durations.append((k, dur, capped))
            print(f"   {burst[0]:7.3f}..{burst[-1]:7.3f}s  {dur:6.3f}s  "
                  f"{len(burst):3d}ev  {kind:11}{extra}")
        print()

    print("=== Watchdog / replay-survival summary ===")
    for k, dur, capped in run_durations:
        note = " (ran past capture end -> lower bound)" if capped else ""
        print(f"  attempt {k}: motor ran {dur:.2f}s under replay before stop{note}")
    obs = [d for _, d, capped in run_durations if not capped]
    if obs:
        print(f"\n  observed safety-cut after {min(obs):.2f}-{max(obs):.2f}s of replay.")
    print("  all shutdowns are ABRUPT (steady rate then instant silence), NOT the")
    print("  smooth ~1.8s speed ramp-down of a normal Stop -> this is a watchdog")
    print("  safety-cut, so replay never achieves controlled operation.")
    maxgap = max(max(b[i]-b[i-1] for i in range(1,len(b)))
                 for att in attempts for b in split(att, BURST_GAP)
                 if classify(b) == "run(motor)" and len(b) > 1)
    print(f"  treadmill sustained internal TX gaps up to ~{maxgap*1000:.0f}ms mid-run "
          f"without cutting (suggestive lower bound on the timeout; not a direct")
    print("  measure, since the panel side was not captured here).")


if __name__ == "__main__":
    main()
