# TREN-V0.1 — protocol spec for the custom panel firmware

What the replacement panel must send and expect, drawn from the decoded
"Полная старт-стоп" capture and cross-checked in [FINDINGS.md](FINDINGS.md).
Tags: **[confirmed]** measured on real data, **[inferred]** consistent but not
proven, **[unknown]** needs the active test or more captures.

> This spec lets the panel build valid frames and run the normal start→run→stop
> cycle. The watchdog is now **measured** on hardware (≈2–3 s keep-alive, §7);
> open-loop repetition of a valid speed frame sustains the belt. Remaining gaps
> are refinements (§9), not blockers.

## 1. Physical layer  [confirmed]

- **2400 baud, 8 data bits, no parity, 1 stop bit.**
- **Inverted logic** (idle = physical LOW; a UART "mark" is driven low on the
  wire). If the UART peripheral cannot invert, invert in hardware.
- Levels ≈ **5 V**, DC. Not 12 V. The line also differs from plain TTL (level
  shift, and a separate current-loop line) — match the original panel's
  analog front end; this spec covers only the data protocol.
- The panel is the **master**: it transmits on its own schedule and the
  treadmill answers each frame (§5).

## 2. Frame format  [confirmed]

```
+------+---------------------------+---------------------+------+
| 0xFF |          body             |  CRC-16 (2 bytes)   | 0xFE |
| pre  |  (command id + payload)   |  little-endian      | term |
+------+---------------------------+---------------------+------+
```

- `0xFF` preamble and `0xFE` terminator are **not** covered by the CRC.
- Frames are sent back-to-back byte-wise (no inter-byte gap inside a frame).

### CRC-16/MCRF4XX  [confirmed on 18 distinct frames]

| poly | init | refin | refout | xorout | stored |
|------|------|-------|--------|--------|--------|
| 0x1021 | 0xFFFF | yes | yes | 0x0000 | little-endian (low byte first) |

Reference (C):

```c
uint16_t crc16_mcrf4xx(const uint8_t *d, size_t n) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < n; i++) {
        crc ^= d[i];
        for (int b = 0; b < 8; b++)
            crc = (crc & 1) ? (crc >> 1) ^ 0x8408 : (crc >> 1);
    }
    return crc;                 // append as: lo = crc & 0xFF, hi = crc >> 8
}
// input = body only (bytes between 0xFF and the CRC). Then frame =
// 0xFF, body..., lo, hi, 0xFE
```

(0x8408 is 0x1021 bit-reversed — the reflected form used with the shift-right
loop.)

## 3. Message catalog

Command id = first 1–2 body bytes. Same id is echoed in the reply. Panel
request bodies begin with the id; treadmill reply bodies begin with `00` then
the id (role of that `00` [unknown] — treat as fixed 0x00 on TX, ignore on RX).

| Id | Dir | Meaning | Body (panel) | Body (treadmill reply) |
|----|-----|---------|--------------|------------------------|
| `10 01` | both | **Start / run** | `10 01` | `00 10 01` |
| `10 00` | both | **Stop / idle** | `10 00` | `00 10 00` |
| `40 23` | both | **Speed set** | `40 23 <spd_lo> <spd_hi>` | `00 40 23` |
| `41 5B` | both | **Query** (status?) | `41 5B` | `00 41 5B 00 00` |

- **Speed** [scale confirmed on hardware at 1.0 and 2.0 km/h]: `spd_lo` in
  **units of 0.1 km/h** (0x0A = 1.0, 0x14 = 2.0 km/h — both verified live).
  `spd_hi` observed always `00`; assumed high byte of a 16-bit little-endian
  value (covers >25.5 km/h) — untested above 2.0 km/h.
- Treadmill's `40 23` reply is constant here (no speed echo); its `41 5B` reply
  carries a constant `00 00` data field. Meaning of the `41 5B` query and its
  `00 00` [unknown] — likely status/incline/distance; more captures needed.

## 4. Ready-made frames (verified bytes from the capture)

Send exactly these (CRC already correct). Also usable as the customer's active
watchdog-test stimulus.

| Purpose | Frame bytes |
|---------|-------------|
| Start | `FF 10 01 A0 74 FE` |
| Speed 1.0 km/h | `FF 40 23 0A 00 B9 04 FE` |
| Speed 0.0 km/h | `FF 40 23 00 00 C9 F9 FE` |
| Query | `FF 41 5B 50 43 FE` |
| Stop | `FF 10 00 29 65 FE` |

For an arbitrary speed, rebuild the CRC over `40 23 <lo> <hi>` (values 0x00–0x0A
already tabulated in `analysis/frames.jsonl`).

## 5. Timing contract  [confirmed]

- **Panel poll period: 100 ms** (measured 99–100 ms, very stable). The panel
  transmits one frame every 100 ms, on its own clock.
- The panel **alternates** the two run-time messages, so each repeats every
  **200 ms**:  `40 23` (speed) → 100 ms → `41 5B` (query) → 100 ms → `40 23` …
- **Treadmill turnaround: ~46 ms** after each panel frame (range 37–55 ms). The
  panel should accept a reply anywhere in roughly a 30–70 ms window and must
  not require it before ~35 ms.

## 6. Session state machine

```
POWER-ON / idle
   |
   |  send  10 01 (start)          <-- expect 00 10 01 reply
   v
RUN  (loop at 100 ms, alternating):
   |    40 23  <speed=setpoint>    <-- expect 00 40 23
   |    41 5B                      <-- expect 00 41 5B 00 00
   |  hold speed at setpoint (e.g. 0x0A = 1.0 km/h)
   |
   |  on STOP request:
   v
DECELERATE  [confirmed profile]:
   |  ramp the speed setpoint DOWN by 0x01 (0.1 km/h) every 200 ms
   |  (i.e. once per 40 23 message), 0x0A -> 0x00, ~2.0 s total,
   |  keeping the 41 5B query interleaved as in RUN
   v
   |  when speed reaches 0x00:
   |    send  10 00 (stop)         <-- expect 00 10 00  (observed sent twice)
   v
IDLE
```

Notes:
- The smooth stop is produced by the **panel ramping its own speed command**
  down 0.1 km/h per 200 ms — it is not the treadmill decelerating on its own
  [inferred]. Firmware should reproduce this ramp rather than command 0
  abruptly (abrupt-0 behaviour [unknown]).
- Start goes straight to the setpoint (no ramp-up seen in this capture at
  1.0 km/h); ramp-up behaviour at higher setpoints [unknown].

## 7. Watchdog — measured  [confirmed, customer bench 18.08]

The treadmill runs a **keep-alive watchdog of ≈ 2–3 s**. As long as it receives
a valid speed frame within that window it keeps the belt moving; ~2–3 s after
frames stop, it safety-cuts.

Confirmed on hardware: blindly repeating a single valid speed frame
(`FF 40 23 0A 00 B9 04 FE`) **every 1.5 s** sustained rotation for over a
minute. Consequences for firmware:

- **Open-loop is sufficient.** No handshake loop, no 100 ms cadence, no query,
  and **no reacting to the treadmill's replies** are required to stay alive —
  just a valid speed frame within the window.
- **Keep-alive rule: resend a valid speed frame at least every ~1.5 s** (safe
  margin under the 2–3 s watchdog). Sending faster (e.g. the original 100 ms)
  is fine but unnecessary.
- The original replay failed only because the recording ran out and the gap
  exceeded the watchdog — not a content/timing-sync problem.

**The CRC is enforced** [confirmed, customer bench]: a speed frame with a wrong
CRC was rejected and the belt stopped on the watchdog. So every keep-alive frame
must carry a correct CRC — a malformed frame does not reset the timer. Rebuild
the CRC whenever the speed byte changes (`analysis/make_frame.py` generates
correct frames for any speed).

Still being pinned down (asked of the customer): exact cut boundary (does 2 s /
2.5 s still hold?), and whether the speed frame alone starts the belt from
standstill or `10 01` must precede it.

**Safety note:** a ~2–3 s coast after loss of signal is inherent to the
machine. This does **not** replace the independent hardware E-stop / tether
(§8) — those must cut power immediately regardless of the data link.

## 8. Safety requirements (carry into hardware) [from customer + context]

- The custom panel **replaces the emergency-stop logic** of the original. The
  **safety tether key and a hardware E-stop must cut motor power independently
  of this board** — never gate them through the firmware. (Customer confirms
  the safety key now hard-cuts power.)
- All bring-up and tests on an **empty belt**, hand on the power E-stop.

## 9. Open items before firmware is trustworthy

1. Watchdog timeout — **measured ≈2–3 s, open-loop keep-alive confirmed (§7);
   CRC is enforced.** Refinements pending: exact cut boundary, and whether
   `10 01` is needed to start from standstill.
2. Speed scale at higher speeds / `spd_hi` behaviour (needs a capture >2.55 km/h
   — the analyzer-kills-line problem applies; scope-only screenshots exist for
   1.1–1.6 km/h but are not bit-readable).
3. Meaning of the `41 5B` query reply (`00 00`) and the treadmill body's leading
   `00`.
4. Ramp-up profile at start for setpoints above 1.0 km/h.
