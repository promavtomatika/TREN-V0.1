# Operator log — "Полная старт-стоп" capture

Verbatim commentary from the device owner (customer), describing what was
physically done during the capture. This is the ground truth for correlating
byte fields with machine state (plan step 7). Times are relative to the START
OF THE RECORDING (t=0). The capture is 29.59 s long; signal activity begins at
t≈1.71 s.

## Verbatim (RU)

> Там есть одна особенность: после старта записи через 2-3 секунды я нажал
> кнопку Старт. Но у пульта есть таймер обратного отсчёта с пищалкой — он
> секунд 5-6 добавляет к этому. Стоп же срабатывает более-менее мгновенно, но
> имеется плавное замедление скорости. Стоп я нажал через 2-3 секунды после
> того как дорожка пришла в движение.

## Reconstructed timeline (INFERRED from the commentary — approximate)

| Capture time (s) | Event | Source |
|------------------|-------|--------|
| 0.0              | Recording starts | fact |
| ~1.71            | First line activity (wake / handshake) | measured |
| ~2–3             | **Start button pressed** | operator |
| ~2–3 … ~8–9      | Panel countdown with beeper (~5–6 s), belt NOT yet moving | operator |
| ~8–9             | **Belt begins to move** | inferred (press + countdown) |
| ~10–12           | **Stop button pressed** (~2–3 s after belt started) | operator |
| ~10–12 → later   | Smooth speed ramp-down (deceleration), not instant | operator |

## Consequences for analysis

- The interval between Start press and belt motion (~5–6 s) is a **panel-side
  countdown**, not a treadmill-controller behaviour. During it the panel and
  controller are still exchanging frames — useful for isolating "commanded
  speed = 0 / armed" vs "running" states.
- A **speed field** should rise from zero only after ~t=8–9 s, then ramp DOWN
  smoothly after the Stop press rather than dropping to zero at once. That
  ramp is a signature to hunt for in any candidate numeric field.
- Stop is near-instant in command terms → look for a single discrete
  state/command change at the Stop instant, distinct from the gradual speed
  decay that follows it.
- All times are ±1–2 s (human estimate). Do not treat them as precise
  boundaries; use them to bracket, not to label individual frames.
