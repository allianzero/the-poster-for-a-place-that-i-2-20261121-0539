#!/usr/bin/env python3
"""VELMORA -- a travel poster for a place that isn't there.

A deterministic, dependency-free (Python standard library only) program
that draws a 1024x1024 travel poster and writes it to /output/entry.png.

The invented place: VELMORA, floating isles above an amber sea at dusk.
No network, no external assets, no randomness: every pixel is a fixed
function of the constants below, so two runs produce byte-identical PNGs.

Run:  python3 main.py
Out:  /output/entry.png  (or $POSTER_OUT, or ./output/entry.png as fallback)
"""

import hashlib
import math
import os
import struct
import sys
import zlib

W = 1024
H = 1024
HORIZON = 640  # where the amber sea begins

# ---------------------------------------------------------------- palette
SKY_STOPS = [
    (0, (24, 20, 62)),      # deep indigo night at the top
    (240, (74, 44, 112)),   # violet
    (420, (150, 72, 116)),  # rose
    (540, (216, 116, 92)),  # ember
    (HORIZON, (250, 178, 96)),  # amber at the horizon
]
SEA_STOPS = [
    (HORIZON, (30, 88, 100)),   # teal where the sea meets the sky
    (800, (22, 64, 90)),
    (H - 1, (12, 32, 62)),      # deep water at the bottom
]
SUN_COLOR = (255, 214, 138)
SUN_GLOW = (255, 190, 120)
ISLE_COLOR = (34, 26, 66)
TREE_COLOR = (20, 34, 52)
RIM_COLOR = (232, 176, 96)      # warm rim light on the isles
FALL_COLOR = (238, 214, 168)    # waterfalls
MIST_COLOR = (250, 226, 188)
TEXT_COLOR = (255, 240, 210)    # cream lettering
TEXT_SHADOW = (40, 26, 70)
BIRD_COLOR = (30, 24, 54)

# ---------------------------------------------------------------- tiny PRNG
# A fixed-seed linear congruential generator: deterministic on every
# interpreter, no dependency on the `random` module's version.


class LCG:
    def __init__(self, seed=20261121):
        self.s = seed

    def next(self):
        self.s = (1103515245 * self.s + 12345) & 0x7FFFFFFF
        return self.s

    def randrange(self, n):
        return self.next() % n

    def uniform(self):
        return self.next() / 0x7FFFFFFF


# ---------------------------------------------------------------- 5x7 font
# Hand-drawn bitmap glyphs (5 columns x 7 rows), one string per row.
FONT = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
}


def lerp(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def gradient(stops, y):
    """Colour at row y from a list of (y, colour) stops."""
    if y <= stops[0][0]:
        return stops[0][1]
    for (y0, c0), (y1, c1) in zip(stops, stops[1:]):
        if y <= y1:
            return lerp(c0, c1, (y - y0) / max(1, y1 - y0))
    return stops[-1][1]


# ---------------------------------------------------------------- canvas
class Canvas:
    def __init__(self):
        self.rows = [bytearray(W * 3) for _ in range(H)]

    def fill_row(self, y, color):
        self.rows[y][:] = bytes(color) * W

    def span(self, y, x0, x1, color):
        """Fill row y, columns [x0, x1), clamped."""
        if y < 0 or y >= H:
            return
        x0 = max(0, x0)
        x1 = min(W, x1)
        if x1 <= x0:
            return
        self.rows[y][x0 * 3:x1 * 3] = bytes(color) * (x1 - x0)

    def px(self, y, x, color):
        if 0 <= x < W and 0 <= y < H:
            self.rows[y][x * 3:x * 3 + 3] = bytes(color)

    def ellipse_span(self, y, cx, cy, rx, ry, color):
        """One horizontal slice of a filled ellipse."""
        dy = (y - cy) / ry
        if abs(dy) >= 1.0:
            return
        dx = rx * math.sqrt(1.0 - dy * dy)
        self.span(y, int(cx - dx), int(cx + dx) + 1, color)

    def disc(self, cx, cy, r, color, y_lo=0, y_hi=H, band_gap=None):
        """Filled disc; band_gap=(y_start, period, width) cuts retro slits."""
        for y in range(max(0, cy - r, y_lo), min(H, cy + r + 1, y_hi)):
            if band_gap is not None:
                ys, period, width = band_gap
                if y > ys and (y - ys) % period < width:
                    continue
            dy = y - cy
            dx = int(math.sqrt(max(0, r * r - dy * dy)))
            self.span(y, cx - dx, cx + dx + 1, color)


# ---------------------------------------------------------------- text
def draw_text(cv, text, x0, y0, scale, color):
    """Draw text with the 5x7 font, scaled, via filled run rectangles."""
    x = x0
    for ch in text:
        glyph = FONT.get(ch)
        if glyph is None:
            x += 6 * scale
            continue
        for r, bits in enumerate(glyph):
            c = 0
            while c < 5:
                if bits[c] == "1":
                    c1 = c
                    while c1 < 5 and bits[c1] == "1":
                        c1 += 1
                    for dy in range(scale):
                        cv.span(y0 + r * scale + dy,
                                x + c * scale, x + c1 * scale, color)
                    c = c1
                else:
                    c += 1
        x += 6 * scale


def text_width(text, scale):
    return len(text) * 6 * scale - scale


def diamond(cv, cx, cy, r, color):
    for dy in range(-r, r + 1):
        w = r - abs(dy)
        cv.span(cy + dy, cx - w, cx + w + 1, color)


# ---------------------------------------------------------------- scene
def draw_isle(cv, cx, top, hw, bot, trees, pavilion=False):
    """A floating island: flat top, rocky underside tapering to a point."""
    # Rocky body: rounded top corners, then a taper to the point.
    for y in range(top, bot + 1):
        if y < top + 18:
            t = (y - top) / 18.0
            half = hw * (0.55 + 0.45 * t)
        else:
            v = (y - top - 18) / max(1, bot - top - 18)
            half = hw * (1.0 - v) ** 0.8
        # Slight wobble so the rock edge is not a perfect cone.
        half *= 1.0 + 0.03 * math.sin(y * 0.35 + cx * 0.01)
        cv.span(y, int(cx - half), int(cx + half) + 1, ISLE_COLOR)
    # Warm rim light along the flat top.
    for y in range(top, top + 3):
        t = (y - top) / 18.0
        half = hw * (0.55 + 0.45 * t)
        cv.span(y, int(cx - half) + 2, int(cx + half) - 1, RIM_COLOR)
    # Pine silhouettes standing on the top.
    for (tx, th, tw) in trees:
        for y in range(top - th, top + 1):
            f = (y - (top - th)) / max(1, th)
            half = (tw / 2.0) * f
            cv.span(y, int(tx - half), int(tx + half) + 1, TREE_COLOR)
        cv.span(top, tx - 1, tx + 2, TREE_COLOR)  # trunk
    if pavilion:
        # A small domed pavilion with a spire, gold roof.
        px, py = cx, top
        cv.span(py - 16, px - 9, px + 10, RIM_COLOR)          # dome base
        for y in range(py - 24, py - 16):                      # dome
            dy = (y - (py - 24)) / 8.0
            half = 9.0 * math.sqrt(max(0.0, 1.0 - (1.0 - dy) ** 2))
            cv.span(y, int(px - half), int(px + half) + 1, RIM_COLOR)
        cv.span(py - 30, px - 1, px + 2, RIM_COLOR)           # spire
        cv.span(py - 15, px - 7, px + 8, ISLE_COLOR)          # walls
        cv.span(py - 14, px - 7, px + 8, ISLE_COLOR)
        cv.px(py - 13, px, (255, 226, 150))                  # lit window


def draw_waterfall(cv, cx, y0, length, phase):
    for i, y in enumerate(range(y0, y0 + length)):
        wob = int(3 * math.sin(i * 0.16 + phase))
        w = 7 if i % 3 else 10
        cv.span(y, cx - w + wob, cx + w + wob + 1, FALL_COLOR)
    # Mist where the fall meets the sea air.
    my = y0 + length
    for y in range(my - 6, my + 8):
        dy = (y - my) / 8.0
        if abs(dy) >= 1.0:
            continue
        dx = 46 * math.sqrt(1.0 - dy * dy)
        cv.span(y, int(cx - dx), int(cx + dx) + 1, MIST_COLOR)


def build_poster():
    cv = Canvas()
    rng = LCG(20261121)

    # 1. Sky gradient.
    for y in range(HORIZON):
        cv.fill_row(y, gradient(SKY_STOPS, y))

    # 2. Stars in the upper sky (drawn before the lettering covers them).
    for _ in range(110):
        x = rng.randrange(W)
        y = rng.randrange(330)
        s = 2 if rng.randrange(4) == 0 else 1
        col = (255, 244, 214) if rng.randrange(3) else (198, 188, 224)
        for dy in range(s):
            cv.span(y + dy, x, x + s, col)

    # 3. Low sun with a soft glow, clipped at the horizon, retro slits
    #    across its lower half.
    sun_cx, sun_cy, sun_r = 640, 545, 140
    cv.disc(sun_cx, sun_cy, 195, lerp(gradient(SKY_STOPS, sun_cy), SUN_GLOW, 0.30),
            y_hi=HORIZON)
    cv.disc(sun_cx, sun_cy, sun_r, SUN_COLOR, y_hi=HORIZON,
            band_gap=(sun_cy + 20, 26, 7))

    # 4. Clouds: pale amber ellipses, warmer than the sky behind them.
    #    Each cloud is two overlapping puffs so no edge reads as a flat disc.
    for (cx, cy, rx, ry) in [(250, 345, 120, 22), (830, 318, 95, 18),
                             (180, 606, 170, 15), (880, 590, 130, 13)]:
        for y in range(cy - ry, cy + ry + 1):
            col = lerp(gradient(SKY_STOPS, y), (255, 198, 142), 0.38)
            cv.ellipse_span(y, cx, cy, rx, ry, col)
        for y in range(cy - ry - 8, cy - ry + 12):
            col = lerp(gradient(SKY_STOPS, y), (255, 205, 150), 0.42)
            cv.ellipse_span(y, cx - rx // 3, cy - ry + 4, rx // 2, ry // 2 + 4, col)

    # 5. The sea, with the sun's amber road on the water.
    for y in range(HORIZON, H):
        sea = gradient(SEA_STOPS, y)
        cv.fill_row(y, sea)
        depth = (y - HORIZON) / (H - HORIZON)
        half = int(115 * (1.0 - 0.35 * depth))
        fade = 0.55 * (1.0 - depth) + 0.08
        cv.span(y, sun_cx - half, sun_cx + half + 1,
                lerp(sea, (238, 150, 74), fade))

    # 6. Shimmer dashes on the water (fixed-seed, deterministic).
    for y in range(656, 1010, 9):
        for _ in range(3):
            x = sun_cx - 110 + rng.randrange(220)
            ln = 18 + rng.randrange(46)
            cv.span(y, x, x + ln, (255, 205, 130))
        for _ in range(2):
            x = rng.randrange(W - 60)
            ln = 14 + rng.randrange(30)
            cv.span(y + 4, x, x + ln, (70, 130, 140))

    # 7. The floating isles, waterfalls and mist.
    draw_isle(cv, 370, 430, 190, 580,
              trees=[(255, 34, 26), (310, 44, 30), (420, 38, 26),
                     (470, 30, 22), (505, 24, 18)],
              pavilion=True)
    draw_isle(cv, 845, 470, 105, 565,
              trees=[(810, 30, 22), (880, 24, 18)])
    draw_isle(cv, 130, 500, 80, 570,
              trees=[(130, 26, 20)])
    draw_waterfall(cv, 370, 580, 52, 0.0)
    draw_waterfall(cv, 845, 565, 62, 1.7)
    draw_waterfall(cv, 130, 570, 58, 3.1)

    # 8. Birds crossing the dusk sky.
    for (bx, by) in [(250, 300), (285, 318), (700, 280), (740, 305),
                     (880, 360), (150, 360), (560, 330), (920, 300)]:
        for i in range(6):
            cv.px(by + i, bx - 6 + i, BIRD_COLOR)
            cv.px(by + i, bx + 6 - i, BIRD_COLOR)

    # 9. The place's name, large in the open sky, with a soft shadow and
    #    a gold rule beneath it. Nothing else is written on the poster.
    name = "VELMORA"
    scale = 16
    tw = text_width(name, scale)
    tx = (W - tw) // 2
    ty = 150
    draw_text(cv, name, tx + 7, ty + 8, scale, TEXT_SHADOW)
    draw_text(cv, name, tx, ty, scale, TEXT_COLOR)
    rule_y = ty + 7 * scale + 28
    cv.span(rule_y, 300, 725, RIM_COLOR)
    cv.span(rule_y + 1, 300, 725, RIM_COLOR)
    diamond(cv, 284, rule_y, 6, RIM_COLOR)
    diamond(cv, 740, rule_y, 6, RIM_COLOR)

    return cv


# ---------------------------------------------------------------- PNG out
def png_bytes(cv):
    raw = bytearray()
    for row in cv.rows:
        raw.append(0)  # filter: None
        raw += row
    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def out_path():
    if os.environ.get("POSTER_OUT"):
        return os.environ["POSTER_OUT"]
    try:
        os.makedirs("/output", exist_ok=True)
        probe = "/output/.poster_write_test"
        with open(probe, "wb") as f:
            f.write(b"")
        os.remove(probe)
        return "/output/entry.png"
    except OSError:
        os.makedirs("output", exist_ok=True)
        return os.path.join("output", "entry.png")


def main():
    cv = build_poster()
    data = png_bytes(cv)
    path = out_path()
    with open(path, "wb") as f:
        f.write(data)
    digest = hashlib.sha256(data).hexdigest()
    print(f"wrote {path}: {len(data)} bytes, sha256 {digest}")
    if len(data) > 1048576:
        print("ERROR: over the 1 MiB gate", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
