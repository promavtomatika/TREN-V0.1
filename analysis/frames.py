"""Stage 4 - normalized intermediate representation.

Decode both channels, segment the per-channel byte streams into frames, and
emit one JSONL record per frame (time-ordered across both directions). Every
later stage reads frames.jsonl, never the raw capture.

Frame segmentation is gap-based: within a frame bytes are back-to-back (one
byte-time apart at 2400 baud = 4.17 ms); between frames the line goes idle for
longer. We pick the split threshold from the actual inter-byte gap histogram
and cross-check it against the FF.../...FE markers.
"""
import json
import os

from common import SR, Channel, load_transitions, SIDE
from decode import debounce, decode_frames, GLITCH_US

BAUD = 2400
BYTE_MS = 10.0 / BAUD * 1000.0  # 4.1667 ms, one 8N1 frame
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frames.jsonl")


def channel_bytes(data, ch):
    s, l = debounce(*data[ch], int(GLITCH_US * SR / 1e6))
    return decode_frames(Channel(s, l), SR / BAUD, True, 8, "N", 1)


def gap_report(byte_streams):
    print("inter-byte gap histogram (ms bucket -> count), per channel:")
    for ch, bs in byte_streams.items():
        from collections import Counter
        gaps = [(bs[i][0] - bs[i - 1][0]) * 1000 for i in range(1, len(bs))]
        c = Counter(round(g) for g in gaps)
        top = sorted(c.items())
        print(f"  Ch{ch} ({SIDE[ch]}): " +
              ", ".join(f"{ms}ms:{n}" for ms, n in top if n >= 2))


def segment(bs, direction, gap_ms):
    """Split (t,val,ok) list into frames on gaps > gap_ms. One byte-time is
    ~4.17 ms; a gap well above that starts a new frame."""
    frames = []
    cur = []
    for i, (t, v, ok) in enumerate(bs):
        gap = None if i == 0 else (t - bs[i - 1][0]) * 1000 - BYTE_MS
        if cur and gap is not None and gap > gap_ms:
            frames.append(cur)
            cur = []
        cur.append((t, v, ok))
    if cur:
        frames.append(cur)
    return frames


def build(gap_ms=8.0):
    data = load_transitions()
    byte_streams = {ch: channel_bytes(data, ch) for ch in (0, 1)}
    gap_report(byte_streams)

    records = []
    prev_end = {0: None, 1: None}
    for ch in (0, 1):
        direction = SIDE[ch]
        frames = segment(byte_streams[ch], direction, gap_ms)
        for fr in frames:
            t_start = fr[0][0]
            t_end = fr[-1][0] + BYTE_MS / 1000.0
            vals = [v for _, v, _ in fr]
            gap_before = None
            if prev_end[ch] is not None:
                gap_before = round((t_start - prev_end[ch]) * 1000, 3)
            prev_end[ch] = t_end
            records.append({
                "t_start": round(t_start, 6),
                "t_end": round(t_end, 6),
                "direction": direction,
                "n_bytes": len(vals),
                "bytes_hex": " ".join(f"{v:02X}" for v in vals),
                "gap_before_ms": gap_before,
                "starts_ff": vals[0] == 0xFF,
                "ends_fe": vals[-1] == 0xFE,
                "framing_ok": all(ok for _, _, ok in fr),
            })
    records.sort(key=lambda r: r["t_start"])
    with open(OUT, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    npanel = sum(1 for r in records if r["direction"] == "panel")
    ntread = sum(1 for r in records if r["direction"] == "treadmill")
    clean = sum(1 for r in records if r["starts_ff"] and r["ends_fe"])
    print(f"\nwrote {len(records)} frames to {os.path.basename(OUT)} "
          f"(panel {npanel}, treadmill {ntread}); "
          f"{clean} are well-formed FF..FE")
    print("\nfirst 14 frames (time-ordered):")
    for r in records[:14]:
        g = f"{r['gap_before_ms']:.0f}ms" if r["gap_before_ms"] is not None else "  -"
        print(f"  {r['t_start']:8.4f} {r['direction']:9} gap {g:>6}  {r['bytes_hex']}")
    return records


if __name__ == "__main__":
    build()
