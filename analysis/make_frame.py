"""Build valid protocol frames (correct CRC) for the custom panel / bench tests.

Frame = 0xFF | body | CRC16/MCRF4XX(body) little-endian | 0xFE.
Run directly to print a speed table.
"""


def crc16_mcrf4xx(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc


def build_frame(body):
    c = crc16_mcrf4xx(body)
    return [0xFF] + list(body) + [c & 0xFF, (c >> 8) & 0xFF, 0xFE]


def speed_frame(kmh):
    """Speed set frame (id 40 23). Speed is 16-bit little-endian, 0.1 km/h."""
    units = round(kmh * 10)
    return build_frame([0x40, 0x23, units & 0xFF, (units >> 8) & 0xFF])


def hexs(frame):
    return " ".join(f"{b:02X}" for b in frame)


NAMED = {
    "start (10 01)": [0x10, 0x01],
    "stop  (10 00)": [0x10, 0x00],
    "query (41 5B)": [0x41, 0x5B],
}


def main():
    print("Named frames:")
    for name, body in NAMED.items():
        print(f"  {name:14} {hexs(build_frame(body))}")
    print("\nSpeed frames (0.0 - 3.0 km/h):")
    kmh = 0.0
    while kmh <= 3.0001:
        print(f"  {kmh:4.1f} km/h  {hexs(speed_frame(kmh))}")
        kmh += 0.1


if __name__ == "__main__":
    main()
