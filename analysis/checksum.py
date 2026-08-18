"""Stage 6 - brute-force the frame checksum over the normalized IR.

We take every well-formed distinct frame (FF ... K FE), treat the last w bytes
before FE as the checksum, and search a wide space of algorithms x parameters x
covered-byte-ranges for any that reproduce the checksum on ALL frames at once.

We report every candidate that fits, plus how many DISTINCT frames constrained
it -- a fit on few frames is a lead, not a proof. Read-only over frames.jsonl.
"""
import json
import os
from collections import Counter

IR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frames.jsonl")

CRC16_POLYS = [0x1021, 0x8005, 0x3D65, 0x8408, 0xA001, 0xC867, 0x0589, 0x1DCF]
CRC8_POLYS = [0x07, 0x31, 0x1D, 0x9B, 0x2F, 0x39, 0xD5, 0x8D, 0xA7, 0x4D]
INITS16 = [0x0000, 0xFFFF, 0x1D0F, 0xB2AA]
INITS8 = [0x00, 0xFF, 0xAB, 0x3E]
XOROUTS16 = [0x0000, 0xFFFF]
XOROUTS8 = [0x00, 0xFF]


def reflect(x, width):
    r = 0
    for i in range(width):
        if x & (1 << i):
            r |= 1 << (width - 1 - i)
    return r


def crc(data, width, poly, init, refin, refout, xorout):
    reg = init
    topbit = 1 << (width - 1)
    mask = (1 << width) - 1
    for b in data:
        if refin:
            b = reflect(b, 8)
        reg ^= (b << (width - 8)) & mask
        for _ in range(8):
            if reg & topbit:
                reg = ((reg << 1) ^ poly) & mask
            else:
                reg = (reg << 1) & mask
    if refout:
        reg = reflect(reg, width)
    return (reg ^ xorout) & mask


def load_frames():
    recs = [json.loads(l) for l in open(IR)]
    seen = {}
    for r in recs:
        if not (r["starts_ff"] and r["ends_fe"] and r["framing_ok"]):
            continue
        b = tuple(int(x, 16) for x in r["bytes_hex"].split())
        seen.setdefault((r["direction"], b), r["direction"])
    # group distinct frames by direction
    out = {"panel": [], "treadmill": [], "all": []}
    for (d, b) in seen:
        out[d].append(b)
        out["all"].append(b)
    return out


def covered(frame, start, w):
    """bytes covered by checksum: [start : len-1-w) (FF..payload, before cksum,
    excluding the FE terminator)."""
    return frame[start:len(frame) - 1 - w]


def cksum_field(frame, w, endian):
    raw = frame[len(frame) - 1 - w:len(frame) - 1]
    if w == 1:
        return raw[0]
    return (raw[0] << 8) | raw[1] if endian == "big" else (raw[1] << 8) | raw[0]


def fits_simple(frames, start, w, fn):
    for fr in frames:
        if len(fr) < start + 1 + w + 1:
            return False
        data = covered(fr, start, w)
        got = cksum_field(fr, w, "big")  # simple sums are endian-agnostic for w=1
        if fn(data) != got:
            return False
    return True


def search(frames, label):
    hits = []
    starts = range(0, 4)

    # --- 1-byte simple ---
    for start in starts:
        defs = {
            "sum8": lambda d: sum(d) & 0xFF,
            "sum8_2c": lambda d: (-sum(d)) & 0xFF,
            "sum8_inv": lambda d: (~sum(d)) & 0xFF,
            "xor8": lambda d: (lambda a: [a.__setitem__(0, a[0] ^ x) for x in d] and a[0])([0]),
        }
        for name, fn in defs.items():
            if all(len(fr) >= start + 3 for fr in frames) and fits_simple(frames, start, 1, fn):
                hits.append(f"{name} start={start} (1B)")

    # --- 2-byte simple ---
    for start in starts:
        for endian in ("big", "little"):
            def s16(d):
                return sum(d) & 0xFFFF
            ok = True
            for fr in frames:
                if len(fr) < start + 4:
                    ok = False
                    break
                if s16(covered(fr, start, 2)) != cksum_field(fr, 2, endian):
                    ok = False
                    break
            if ok:
                hits.append(f"sum16 start={start} endian={endian} (2B)")

    # --- CRC-8 ---
    for start in starts:
        for poly in CRC8_POLYS:
            for init in INITS8:
                for refin in (False, True):
                    for refout in (False, True):
                        for xorout in XOROUTS8:
                            ok = True
                            for fr in frames:
                                if len(fr) < start + 3:
                                    ok = False
                                    break
                                d = covered(fr, start, 1)
                                if crc(d, 8, poly, init, refin, refout, xorout) != cksum_field(fr, 1, "big"):
                                    ok = False
                                    break
                            if ok:
                                hits.append(f"CRC8 poly=0x{poly:02X} init=0x{init:02X} "
                                            f"refin={int(refin)} refout={int(refout)} "
                                            f"xorout=0x{xorout:02X} start={start}")

    # --- CRC-16 ---
    for start in starts:
        for poly in CRC16_POLYS:
            for init in INITS16:
                for refin in (False, True):
                    for refout in (False, True):
                        for xorout in XOROUTS16:
                            for endian in ("big", "little"):
                                ok = True
                                for fr in frames:
                                    if len(fr) < start + 4:
                                        ok = False
                                        break
                                    d = covered(fr, start, 2)
                                    if crc(d, 16, poly, init, refin, refout, xorout) != cksum_field(fr, 2, endian):
                                        ok = False
                                        break
                                if ok:
                                    hits.append(f"CRC16 poly=0x{poly:04X} init=0x{init:04X} "
                                                f"refin={int(refin)} refout={int(refout)} "
                                                f"xorout=0x{xorout:04X} endian={endian} start={start}")

    print(f"\n===== {label}: {len(frames)} distinct frames =====")
    lens = Counter(len(f) for f in frames)
    print("  frame lengths:", dict(sorted(lens.items())))
    if hits:
        for h in hits:
            print("  FIT:", h)
    else:
        print("  no candidate fit all frames")
    return hits


def main():
    fr = load_frames()
    # The 40-23 panel family varies by one byte -> strongest single test.
    fam = [f for f in fr["panel"] if len(f) >= 3 and f[1] == 0x40 and f[2] == 0x23]
    search(fam, "panel 40 23 family (speed sweep)")
    search(fr["panel"], "panel (all distinct)")
    search(fr["treadmill"], "treadmill (all distinct)")
    search(fr["all"], "both directions (all distinct)")


if __name__ == "__main__":
    main()
