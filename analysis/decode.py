"""Our own UART decoder over the raw capture, with a config sweep.

We do not trust the vendor decode. For each channel we:
  1. glitch-filter runs shorter than GLITCH_US (edge ringing is sub-us; real
     bits are >=100 us, so this is safe),
  2. sweep {bit rate} x {polarity} x {data bits} x {parity} x {stop bits},
  3. decode by sampling each bit at its centre,
  4. rank configs by framing-error rate, then by payload byte-entropy.

A config that is genuinely UART shows a low framing-error rate AND non-trivial
entropy (not all 0x00/0xFF). Both are reported so a weak fit is visible.
"""
import math
from collections import Counter

from common import SR, Channel, load_transitions, SIDE

GLITCH_US = 10.0  # runs shorter than this are ringing, not bits


def debounce(samples, levels, min_run):
    s, l = samples[:], levels[:]
    changed = True
    while changed:
        changed = False
        ns, nl = [s[0]], [l[0]]
        i = 1
        while i < len(s):
            nxt = s[i + 1] if i + 1 < len(s) else s[i] + min_run
            if nxt - s[i] < min_run and i + 1 < len(s):
                i += 2
                changed = True
                continue
            ns.append(s[i])
            nl.append(l[i])
            i += 1
        s, l = ns, nl
    return s, l


def decode_frames(chan, bit_samples, invert, databits, parity, stopbits):
    """Return a list of (t_start_s, value, ok) per decoded byte. LSB-first.

    Edge-driven: only real 1->0 logical transitions are start-bit candidates,
    each bit is sampled at its centre, and after every byte we resync on the
    next real start edge (searching from mid-stop-bit) rather than jumping a
    fixed 10 bits -- back-to-back frames jitter sub-bit and a hard jump skips
    them. O(frames), not O(samples).
    """
    from bisect import bisect_left, bisect_right
    s, lv = chan.samples, chan.levels

    def L(phys):
        return (1 - phys) if invert else phys

    def logic_at(x):
        i = bisect_right(s, x) - 1
        if i < 0:
            i = 0
        return L(lv[i])

    frame_bits = 1 + databits + (1 if parity != "N" else 0) + stopbits
    starts = [s[j] for j in range(len(s))
              if L(lv[j]) == 0 and (j == 0 or L(lv[j - 1]) == 1)]

    out = []
    pos = s[0]
    si = 0
    while si < len(starts):
        S = starts[si]
        if S < pos:
            si += 1
            continue

        def bit_at(k):
            return logic_at(int(S + (k + 0.5) * bit_samples))

        if bit_at(0) != 0:
            si += 1
            continue
        val = 0
        for b in range(databits):
            if bit_at(1 + b):
                val |= (1 << b)
        idx = 1 + databits
        ok = True
        if parity != "N":
            pbit = bit_at(idx)
            idx += 1
            ones = bin(val).count("1") + pbit
            if parity == "E" and ones % 2 != 0:
                ok = False
            if parity == "O" and ones % 2 != 1:
                ok = False
        for sconf in range(stopbits):
            if bit_at(idx + sconf) != 1:
                ok = False
        out.append((S / SR, val, ok))
        pos = S + (frame_bits - 0.5) * bit_samples
        si = bisect_left(starts, pos)
    return out


def decode(chan, bit_samples, invert, databits, parity, stopbits):
    """Back-compat wrapper: (bytes list, n_frames, n_framing_errors)."""
    fr = decode_frames(chan, bit_samples, invert, databits, parity, stopbits)
    vals = [v for _, v, _ in fr]
    ferr = sum(0 if ok else 1 for _, _, ok in fr)
    return vals, len(fr), ferr


def entropy(vals):
    if not vals:
        return 0.0
    c = Counter(vals)
    n = len(vals)
    return -sum((k / n) * math.log2(k / n) for k in c.values())


def sweep(chan, label):
    bauds = [1200, 2400, 4800, 9600, 19200, 3200, 4808]
    # also the data-fitted rate for this channel
    results = []
    for baud in bauds:
        bs = SR / baud
        for invert in (False, True):
            for databits in (8, 7):
                for parity in ("N", "E", "O"):
                    for stopbits in (1, 2):
                        vals, fr, fe = decode(chan, bs, invert, databits,
                                              parity, stopbits)
                        if fr < 20:
                            continue
                        rate = fe / fr
                        results.append((rate, -entropy(vals), baud, invert,
                                        databits, parity, stopbits, fr, fe,
                                        entropy(vals), vals))
    results.sort(key=lambda r: (r[0], r[1]))
    print(f"\n===== {label} : top configs (ranked by framing-error rate) =====")
    print(f"{'baud':>6} {'inv':>3} {'d':>1} {'par':>3} {'stp':>3} "
          f"{'frames':>6} {'ferr%':>6} {'entropy':>7}  distinct")
    for r in results[:8]:
        (rate, negH, baud, inv, db, par, sb, fr, fe, H, vals) = r
        distinct = len(set(vals))
        print(f"{baud:>6} {int(inv):>3} {db:>1} {par:>3} {sb:>3} "
              f"{fr:>6} {rate * 100:>5.1f}% {H:>7.2f}  {distinct} distinct")
    return results[0] if results else None


def main():
    data = load_transitions()
    best = {}
    for ch in (0, 1):
        s, l = debounce(*data[ch], int(GLITCH_US * SR / 1e6))
        chan = Channel(s, l)
        best[ch] = sweep(chan, f"Channel {ch} ({SIDE[ch]})")
    # dump the winning byte stream head for each channel
    for ch in (0, 1):
        if not best[ch]:
            continue
        vals = best[ch][-1]
        baud = best[ch][2]
        print(f"\nChannel {ch} ({SIDE[ch]}) @ {baud} baud, first 40 bytes:")
        print(" ".join(f"{v:02X}" for v in vals[:40]))


if __name__ == "__main__":
    main()
