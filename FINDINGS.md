# FINDINGS — TREN-V0.1 treadmill protocol

Conclusions with the evidence for each. Every number here is reproducible from
`analysis/` over the raw capture. **[M]** = directly measured, **[I]** =
inferred. Background in [PROTOCOL_CONTEXT.md](PROTOCOL_CONTEXT.md); customer
dialog in [CUSTOMER_DIALOG.md](CUSTOMER_DIALOG.md); operator timeline in
[analysis/operator_timeline.md](analysis/operator_timeline.md).

## Data source

The live results below come from the **"Полная старт-стоп"** capture, present
in the repo three ways (all the same recording): `digital.csv` (raw Saleae
transitions export, the source we decode), `Полная старт-стоп.sal` (native
capture), `Обмен` (vendor decoder export, both sides labelled). Saleae Logic,
**24 MS/s**, 8 channels, only Ch0 and Ch1 active. [M]

The older `Ответ_17_1922.csv` is a separate, earlier, treadmill-only capture
with a badly misconfigured decode — superseded, kept only for history.

## Physical / link layer

- **Two active channels. Ch0 = treadmill ("Дорожка"), Ch1 = panel
  ("Пульт").** [M] — Ch0's decoded bytes match the vendor-labelled `Дорожка`
  stream byte-for-byte; first-edge timestamps line up with the labelled export.
- **Both directions: 2400 baud, 8 data bits, no parity, 1 stop bit, inverted
  logic (idle = physical LOW).** [M] — recovered by our own config sweep
  (`analysis/decode.py`), ranked by framing-error rate:
  - Treadmill: 2400-8N1-inverted → **0.47% framing errors** (2 of 423 bytes).
  - Panel: 2400-8N1-inverted → **0.27% framing errors** (1 of 369 bytes).
  - No other baud/polarity/parity/stop combination comes close (next best
    >16%). Bit-period fit on clean edges: 415.96 µs = 2404 baud, residual
    0.002 (`analysis/bitrate.py`). [M]
- **Logic levels ≈ 5 V, DC-coupled.** [M] — from the oscilloscope screenshots
  (2 V/div, ~5 Vpp). Not 12 V.
- **Panel line carries heavy 16–32 kHz noise during idle gaps** (bursts of
  31/62 µs pulses while the line sits at idle-low), consistent with motor-stage
  EMI pickup. [M/I] — visible in the raw Ch1 waveform; it inflates the raw edge
  count to 184k vs 3k on Ch0. It does **not** corrupt the data: it lands only
  between transmission bursts and is rejected by start-bit validation. Earlier
  "≈10% panel corruption" was a decoder artefact, not real. [I]

## Framing — fully resolved

Both directions use the same frame shape: [M]

```
FF | body | CRC16(body) little-endian (2 bytes) | FE
```

- `FF` = preamble/sync, `FE` = terminator; neither is covered by the CRC. [M]
- `body` = everything between them except the 2 CRC bytes. Panel bodies start
  with the command id; treadmill bodies start with an extra `00` then the
  command id (the `00` **is** inside the CRC body). [M] — role of the `00`
  still open (address / direction / status), but it is not framing overhead.
- Frame boundaries confirmed two ways: gap histogram (4 ms within a frame,
  59–81 ms between) and the FF.../...FE markers agree. [M]

## Checksum — cracked (CRC-16/MCRF4XX)

Brute-force over the IR (`analysis/checksum.py`) found **exactly one** algorithm
that fits, and it fits **all 18 distinct frames across both directions and all
four frame lengths** — independently re-verified in
`analysis/checksum.py` output. [M]

| Parameter | Value |
|-----------|-------|
| Width / poly | 16 / `0x1021` |
| Init | `0xFFFF` |
| RefIn / RefOut | true / true |
| XorOut | `0x0000` |
| Storage | little-endian (low byte first, before `FE`) |
| Covered bytes | `body` only (from after `FF` up to the CRC bytes) |

This is the standard **CRC-16/MCRF4XX**. No other poly/init/reflection/sum/XOR
combination matched. 18 independent constraints (incl. an 11-frame single-byte
sweep) make this a strong result, not a coincidental fit. We can now generate
valid frames.

## Speed field — identified

Panel `40 23` frame, **byte index 3**, is the speed in **units of 0.1 km/h**.
[M] Evidence (`analysis/frames.py` time series):

- Holds at `0x0A` = 1.0 km/h through the run — matches the operator's stated
  1 км/ч start speed.
- After Stop (~t=14.6 s) it ramps **0x0A → 0x00** one 0.1 km/h step per ~200 ms
  poll — matches the operator's "плавное замедление" (smooth deceleration).
- Byte index 4 stays `00` (likely the high byte of a 16-bit speed, or a
  reserved field). [I]

## Conversation structure (request ↔ response)

Panel polls, treadmill answers ~50 ms later, **echoing the command ID**: [M]

| Panel request                 | Treadmill response              |
|-------------------------------|---------------------------------|
| `FF 40 23 0A 00 B9 04 FE`     | `FF 00 40 23 CC 6C FE`          |
| `FF 41 5B 50 43 FE`           | `FF 00 41 5B 00 00 C1 90 FE`    |

- Steady state alternates these two request types. [M]
- Initial handshake before the run: panel `FF 10 01 A0 74 FE` / treadmill
  `FF 00 10 01 2B BD FE` at t≈1.92 s. [M]
- Command IDs seen so far: `10 01`, `40 23`, `41 5B`, `50 43`. [M]
- Polling begins in earnest at t≈11.8 s, matching the operator's
  Start(~2–3 s)+countdown(~5–6 s) ≈ belt-moving window. [M/I]

## Timing (for firmware)

- Request→response turnaround ≈ **50 ms**. [M] — needs tightening into a
  min/typ/max once the IR exists. [open]
- Poll cadence: request pairs repeat roughly every ~0.2 s in the run region.
  [M, coarse]
- **Replay survival (watchdog), from the old `Ответ_17_1922.csv`**
  (`analysis/watchdog.py`): three replay attempts; the motor ran **1.66 s** and
  **0.97 s** before an abrupt stop, a third ran **≥4.24 s** (capture ended
  first). [M]
  - **Every shutdown is abrupt** — steady event rate to the last event, then
    instant silence — categorically unlike a normal Stop (smooth 1.0→0.0 km/h
    ramp over ~1.8 s). So under replay the treadmill performs a **watchdog
    safety-cut**, never a controlled stop. **Replay cannot drive this machine;
    an interactive responder is required.** [M/I]
  - Survival varies with the attempt (0.97 → ≥4.24 s), so the trigger is *not*
    a fixed timer from motor-start — it fires when the replayed stream diverges
    from what the controller expects (timing phase and/or content). [I]
  - The treadmill sustained internal TX gaps up to **~245 ms** mid-run without
    cutting — a soft lower bound on the tolerance, but not a direct watchdog
    measurement (the panel side is absent from this capture). [M/I]
  - **Exact timeout needs an active test** (progressively delay/omit responses
    and watch), which requires transmitting — out of scope for this read-only
    phase. [note]

## Command ids (partial)

Seen so far, same ids echoed both directions: [M]
- `10 xx` — start/stop control. `10 01` at session start (run), `10 00` later
  (stop). [I] — second byte looks like a run flag.
- `40 23` — speed set/report (carries the speed byte). [M/I]
- `41 5B` — query; treadmill answers with a `00 00` data field (incline /
  distance / status?). [open]

## Open questions / not yet done

- **Why does a fixed replay fail?** In steady running the panel `40 23` frame
  is byte-identical every poll (speed `0x0A`), with a valid CRC and **no
  visible sequence counter or echo of the treadmill's data**. A plain replay
  should therefore satisfy a content watchdog — yet it stalls. So the trigger
  is likely timing/handshake, or a counter/echo that only moves during events
  not in this capture. This is the key firmware-architecture question.
- Role of the treadmill body's leading `00`.
- Meaning of the `41 5B` query and its `00 00` response field.
- Sequence counter / monotonic field — searched in `40 23`, none found; confirm
  across all frame types.

## Discarded hypotheses

- "Treadmill runs at ~9600 baud" — a run-length fit artefact; the actual decode
  is unambiguously 2400 (0.47% vs >30% errors at other rates).
- "Panel data is ~10% corrupted by EMI" — false; it was the fixed-jump decoder
  bug skipping back-to-back frames. After edge-resync, 0.27%.
- "The 2400-baud assumption in the vendor export can't be trusted" — it can, for
  the byte *rate*; we independently confirmed it. The vendor's panel decode was
  still poor (9.5% errors) only because it mis-handled the idle-noise regions.
