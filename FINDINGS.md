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

## Framing

Both directions use the same frame shape: [M]

```
FF  <payload bytes>  FE
```

- `FF` = preamble/lead-in, `FE` = terminator. [I] — every FE-terminated group
  is a self-consistent frame; 53 frames decoded on each side, exactly paired.
- Treadmill response frames carry an extra `00` right after `FF` that the panel
  requests do not. [M] — role unknown (address? direction flag?). [open]

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
- Watchdog timeout (why replay stalls): not yet measured. [open]

## Open questions / not yet done

- Meaning of the treadmill's extra `00` byte after `FF`.
- **Checksum** — not started. Last 1–2 bytes before `FE` vary per frame
  (`B9 04`, `2B BD`, `CC 6C`, `C1 90`) and are the checksum candidates.
- **Speed field** — not yet located. The digital capture is a **single-speed
  run at 1 км/ч** (customer, 18.08). The usable signature is therefore the
  ramp **0 → 1 → 0 км/ч**: a response byte that rises from a stopped value as
  the belt spins up (~t=8–12 s) and decays smoothly after Stop. Candidate
  fields are the varying bytes in the treadmill `41 5B` response
  (`00 00 C1 90`). The oscilloscope screenshots cover 1.1–1.6 км/ч but are not
  bit-readable (too coarse); filename→speed mapping (`2Ksk11`=1.1 …
  `2Ksk16`=1.6) is a hypothesis pending confirmation.
- Sequence counter / monotonic field — not yet identified.
- Precise watchdog timeout from the replay capture.

## Discarded hypotheses

- "Treadmill runs at ~9600 baud" — a run-length fit artefact; the actual decode
  is unambiguously 2400 (0.47% vs >30% errors at other rates).
- "Panel data is ~10% corrupted by EMI" — false; it was the fixed-jump decoder
  bug skipping back-to-back frames. After edge-resync, 0.27%.
- "The 2400-baud assumption in the vendor export can't be trusted" — it can, for
  the byte *rate*; we independently confirmed it. The vendor's panel decode was
  still poor (9.5% errors) only because it mis-handled the idle-noise regions.
