"""Shared loaders for the raw two-channel capture.

Source of truth is digital.csv: a Saleae *transitions* export of the
"Полная старт-стоп" capture, 24 MS/s, 8 channels of which only Ch0 and Ch1
carry signal. Each row is a timestamp at which at least one channel changed
level; the listed level holds until the next row that changes it.

Everything downstream works in integer sample units (index = round(t * SR)) so
that results are exact and reproducible rather than subject to float drift.
"""
import csv
import os
from bisect import bisect_right

SR = 24_000_000  # samples/s, from meta.json (sampleRate.digital) and Δt=41.67 ns
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIGITAL_CSV = os.path.join(REPO, "digital.csv")

# Which physical channel is which side of the link. Inferred from coincident
# first-edge timestamps against the labelled "Обмен" decoder export:
#   Ch1 -> Пульт (panel/console),  Ch0 -> Дорожка (treadmill).
SIDE = {0: "treadmill", 1: "panel"}


def load_transitions(path=DIGITAL_CSV, channels=(0, 1)):
    """Return {ch: (samples, levels)} where samples[i] is the integer sample
    index of the i-th transition on that channel and levels[i] the level that
    begins at that index. Includes the initial level at sample 0.
    """
    out = {ch: ([], []) for ch in channels}
    with open(path) as f:
        r = csv.reader(f)
        header = next(r)
        col = {ch: header.index(f"Channel {ch}") for ch in channels}
        prev = {ch: None for ch in channels}
        for row in r:
            if not row:
                continue
            si = round(float(row[0]) * SR)
            for ch in channels:
                v = int(row[col[ch]])
                if v != prev[ch]:
                    samples, levels = out[ch]
                    samples.append(si)
                    levels.append(v)
                    prev[ch] = v
    return out


class Channel:
    """Random-access level lookup over one channel's transition list."""

    def __init__(self, samples, levels):
        self.samples = samples
        self.levels = levels

    def level_at(self, sample_index):
        i = bisect_right(self.samples, sample_index) - 1
        if i < 0:
            return self.levels[0]
        return self.levels[i]

    def run_lengths(self):
        """Consecutive sample counts each level is held (in sample units).
        Skips the final open-ended run."""
        s = self.samples
        return [s[i + 1] - s[i] for i in range(len(s) - 1)]

    @property
    def first(self):
        return self.samples[0]

    @property
    def last(self):
        return self.samples[-1]
