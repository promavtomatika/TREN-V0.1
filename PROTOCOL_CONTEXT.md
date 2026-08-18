# TREN-V0.1 — protocol reverse-engineering context

Drop this file in the repo root. It carries everything established so far so a
fresh session does not have to re-derive it.

## Goal

Replace the stock control panel of a treadmill with custom hardware. The panel
and the treadmill controller exchange data continuously over a serial line. We
need: frame structure, checksum algorithm, field semantics of requests and
responses, and the timing rules the treadmill enforces.

The custom panel hardware already exists. What is missing is the protocol.

## Hardware context (from the device owner, not yet independently verified)

- No public documentation for the machine or its protocol.
- Physical layer differs from plain TTL UART: different voltage levels, signal
  inversion, and an additional line carrying a current loop.
- Communication is bidirectional and continuous — the treadmill is not just
  listening for commands.
- **Attaching a logic analyzer stops the exchange**, despite a reasonably high
  input impedance. Only an oscilloscope works, and it cannot record.
- A replay experiment was done: the recorded panel-side stream was played back
  into the port through an adapter with original timing preserved. The treadmill
  starts accelerating and then stops after a short time. The treadmill's
  responses during that experiment were captured.

## Established findings

Derived from `Ответ_17_1922.csv`, a Saleae Async Serial **decoder-results**
export (columns: `Time [s], Value, Parity Error, Framing Error`). 844 events,
capture span 3.64 s → 66.77 s. Timestamps quantize exactly at 24 MHz, so the
capture ran at 24 MS/s.

### The decode in that file is wrong — baud was misconfigured

- 771 of 844 bytes (91%) carry a framing error. Parity errors: zero, so parity
  checking was disabled.
- Only five distinct values appear across 63 seconds: `0x00` (779), `0xF0` (30),
  `0x70` (18), `0xFF` (16), `0x01` (1). This is aliasing — a decoder configured
  much faster than the line slices long runs of one level into a handful of
  degenerate values.
- All transitions in the structured regions land on a **417.3 µs grid**.
  Measured inter-event intervals: 1251.9 / 1669.3 / 2087.0 / 2503.8 / 3338 /
  4173 µs = exactly 3, 4, 5, 6, 8, 10 × 417.3.

417.3 µs → 2396 baud, i.e. nominal **2400 8N1** (0.15% off, normal crystal
drift).

Competing hypothesis, self-consistent but less likely: base unit 83.4 µs
(≈12000 baud), for which 417.3 µs = 5 bit times. Cannot be ruled out from a
decoded export. Resolve it from raw samples or from a cursor measurement of the
narrowest pulse on the scope.

### Session structure

Three start attempts, each following the same shape:

| t (s)       | Content                                          |
|-------------|--------------------------------------------------|
| 3.64        | run of `FF` — line waking up                     |
| 9.36–9.58   | three structured frames                          |
| 11.69–13.35 | 1.7 s of dense `0x00` with framing errors        |
| 48.71       | run of `FF` again                                |
| 53.32–53.54 | the same frames                                  |
| 56.02–56.98 | dense `0x00` again                               |
| 62.53–62.76 | the same frames                                  |
| 63.08–66.77 | dense `0x00` to end of capture                   |

### Deterministic handshake

The frames at t=9.357 and t=53.324 are identical **byte for byte and in
timing** — same sequence `F0 F0 70 70 70 70 00 00 00`, same inter-byte
intervals to within 1.5 µs. A second frame, `F0 70 00 F0 F0 00 00 00 00 F0 00`,
repeats at least four times unchanged.

(These byte values are decode artifacts, not real payload — but their exact
repeatability proves the protocol is deterministic and the start sequence is
fixed content, not a varying counter at this stage.)

### Timing parameters worth carrying into firmware

- **Turnaround ≈ 7.5 ms.** Each frame is preceded, exactly 7.5 ms earlier
  (18 × 417.3 µs), by a short single event — either the tail of the panel's
  request or a sync/break. Holds to within 0.1 ms across all seven instances.
- **Responses arrive in bursts of three**, with gaps of 77.1 ms and 143.3 ms,
  identically in both sessions. 143.3 ≈ 2 × 71.7, suggesting a poll period
  around 70–77 ms with one response lost.

### Why the analyzer may be killing the line

In the dense-`0x00` regions a periodicity of **1001.6 µs (≈998 Hz)** dominates,
and it does **not** fall on the 417 µs grid — so it is not the same signal.
Those regions begin after the start frames, when the motor is already turning.
Consistent with pickup from the power stage's PWM rather than data.

If so the capture problem is partly electromagnetic, not purely resistive
loading, and a series resistor into a Schmitt trigger will not fix it —
optoisolation with separate supply on the analyzer side plus a short twisted
pair would be needed. Separately: bonding the analyzer's ground can break the
current loop's isolation or create a ground loop, and clamp diodes in cheap
analyzers pull the line hard if levels are 5/12 V or inverted, making the
effective impedance orders of magnitude lower than the datasheet figure.

### Why the old file cannot be salvaged

The decoder already discarded the samples and the idle gaps, and
resynchronization behaviour after a framing error is ambiguous — each byte maps
to several valid edge patterns. Packet contents are not recoverable from it.

## Watchdog hypothesis

The treadmill accelerating and then stopping under replay is almost certainly a
watchdog: it expects a valid response inside a timeout window — a monotonic
counter, or an echo of its own reported speed. A fixed recording desynchronizes
after a few cycles and the controller enters safety stop. **Replay cannot work
at any interval precision; an interactive state machine is required.** The time
to shutdown is itself a useful measurement — it bounds the timeout.

## What to do, in order

1. **Inventory the repo before anything else.** Do not trust filenames or
   assume the previous file's format carries over. For each data file
   determine: raw samples vs decoder results, channel count, sample rate,
   encoding, byte order. Report the inventory before analyzing.
2. **Identify which captures cover which side.** The earlier drop contained
   only the treadmill's responses. The panel-side stream ("ария пульта") is
   required for request↔response correlation, which is what yields field
   semantics. If it is absent, say so explicitly rather than working around it.
3. **Write our own UART decoder** over raw samples. Do not rely on any vendor
   decoder export. Recover the bit rate from the data itself: histogram
   edge-to-edge run lengths, take the GCD / fundamental of the distribution,
   and report the fit quality rather than a single number. Sweep both
   polarities, 7/8 data bits, N/E/O parity, 1/2 stop bits, and rank candidate
   configurations by framing-error rate and by payload entropy.
4. **Emit a normalized intermediate representation** — one JSONL record per
   frame: `{t_start, t_end, direction, bytes_hex, gap_before_ms}`. Every later
   stage reads this, not the raw files.
5. **Recover framing**: preamble/sync, length field, address, terminator, and
   the idle-gap threshold that separates frames.
6. **Brute-force the checksum.** Sweep XOR, sum mod 256 with varying offsets,
   two's complement of sum, CRC-8 and CRC-16 across polynomials, init values,
   reflect-in/reflect-out, and the covered byte range. Report every candidate
   that fits all frames, not just the first hit — and report how many frames
   were available, since a single algorithm fitting a small sample is weak
   evidence.
7. **Correlate fields with state** using the operator's labels (what was
   pressed, when). Look for the speed field, a sequence counter, and any field
   that echoes a value from the opposite direction.
8. **Measure the timing contract**: poll period, turnaround, watchdog timeout.
   These constrain the firmware more tightly than the byte layout does.

## Working constraints

- Put scripts in `analysis/`, keep them re-runnable and deterministic. Someone
  else must be able to reproduce every number.
- Record conclusions in `FINDINGS.md` with the evidence for each, and keep a
  separate list of open questions and discarded hypotheses.
- **Distinguish measurement from inference in every claim.** Say which is
  which. Where a number came from curve-fitting, give the residual.
- Do not silently fill gaps with plausible values. Missing data is a finding.
- Read-only with respect to the treadmill. Nothing in this repo should transmit
  to the device.
- Do not commit, push, or touch the git remote. Local files only.

## Safety note to carry forward

A custom panel also replaces the logic responsible for emergency stop. The
safety tether key and a hardware E-stop must stay in the circuit independently
of the new board, and all tests run on an empty belt.
