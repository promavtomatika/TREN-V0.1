"""Recover the line bit rate from the raw signal, without assuming a value.

Method: every UART edge lands on a bit-period boundary, so the gap between
consecutive edges is an integer number of bit periods. Histogram those gaps;
the fundamental (their approximate GCD) is one bit period. We report the whole
distribution and how cleanly the gaps fit integer multiples, rather than a
single number.
"""
from collections import Counter

from common import SR, Channel, load_transitions, SIDE


def summarize(ch_name, chan):
    runs = chan.run_lengths()
    hist = Counter(runs)
    print(f"\n=== {ch_name} ===")
    print(f"edges: {len(chan.samples)}   run-length values: {len(hist)}")

    shortest = min(runs)
    print(f"shortest run: {shortest} samples = {shortest / SR * 1e6:.2f} us "
          f"-> if 1 bit, {SR / shortest:.1f} baud")

    # Candidate bit period = shortest run. Score how well ALL runs fit an
    # integer multiple of it.
    print("\n most common runs (samples / us / multiple-of-shortest / residual):")
    for run, n in sorted(hist.items(), key=lambda kv: -kv[1])[:12]:
        mult = run / shortest
        resid = abs(mult - round(mult))
        print(f"   {run:6d}  {run / SR * 1e6:8.2f}us  x{mult:6.3f}  "
              f"resid {resid:.3f}   (n={n})")

    # Fit quality: fraction of edges whose gap is within 5% of an integer
    # multiple of the candidate bit period, swept over plausible periods.
    print("\n bit-period fit sweep (period_us -> baud -> %% edges on grid):")
    best = None
    for period in range(shortest - 40, shortest + 41):
        if period <= 0:
            continue
        onbeat = 0
        for run in runs:
            mult = run / period
            if abs(mult - round(mult)) <= 0.05 and round(mult) >= 1:
                onbeat += 1
        frac = onbeat / len(runs)
        if best is None or frac > best[1]:
            best = (period, frac)
    period, frac = best
    print(f"   best period {period} samples = {period / SR * 1e6:.2f} us "
          f"-> {SR / period:.1f} baud   ({frac * 100:.1f}% of edges on grid)")
    for std in (2400, 4800, 9600, 1200):
        p = SR / std
        onbeat = sum(1 for run in runs
                     if abs(run / p - round(run / p)) <= 0.05 and round(run / p) >= 1)
        print(f"   vs {std:5d} baud (period {p:.0f}): {onbeat / len(runs) * 100:5.1f}% on grid")
    return period


def main():
    data = load_transitions()
    for ch, (samples, levels) in data.items():
        summarize(f"Channel {ch} ({SIDE.get(ch, '?')})", Channel(samples, levels))


if __name__ == "__main__":
    main()
