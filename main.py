#!/usr/bin/env python3
"""THE SELF-CHARGING SOLAR TORCH - a catalogue photograph of an impossible gadget.

Draws a studio product shot in pure Python (standard library only) and writes
it as a PNG to /output/entry.png. No network, no randomness, no time dependence:
the same bytes come out on every run.

Scene: a chunky gunmetal flashlight, switched ON, shining its beam onto a solar
panel on a small stand, with a cable looping from the panel back into the
flashlight. The torch charges itself from its own light.
"""

import math
import os
import struct
import zlib

W = 1024
H = 1024


# ---------------------------------------------------------------------------
# PNG encoding (zlib + struct, no third-party code)
# ---------------------------------------------------------------------------

def _chunk(kind, data):
    out = struct.pack(">I", len(data)) + kind + data
    out += struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return out


def write_png(path, width, height, rgb):
    """rgb is a bytearray of width*height*3 bytes, row-major, filter 0."""
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        raw += rgb[y * stride:(y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", ihdr)
    png += _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += _chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


# ---------------------------------------------------------------------------
# Framebuffer + drawing helpers
# ---------------------------------------------------------------------------

def clamp(v, lo=0, hi=255):
    return lo if v < lo else hi if v > hi else v


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c0, c1, t):
    return (int(lerp(c0[0], c1[0], t)),
            int(lerp(c0[1], c1[1], t)),
            int(lerp(c0[2], c1[2], t)))


class Canvas:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.buf = bytearray(w * h * 3)

    def set(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.buf[i] = color[0]
            self.buf[i + 1] = color[1]
            self.buf[i + 2] = color[2]

    def blend(self, x, y, color, alpha):
        """Alpha-blend a colour over the pixel at (x, y); alpha 0..1."""
        if alpha <= 0.0 or not (0 <= x < self.w and 0 <= y < self.h):
            return
        i = (y * self.w + x) * 3
        b = self.buf
        if alpha >= 1.0:
            b[i] = color[0]
            b[i + 1] = color[1]
            b[i + 2] = color[2]
            return
        inv = 1.0 - alpha
        b[i] = int(color[0] * alpha + b[i] * inv)
        b[i + 1] = int(color[1] * alpha + b[i + 1] * inv)
        b[i + 2] = int(color[2] * alpha + b[i + 2] * inv)

    def hline(self, x0, x1, y, color, alpha=1.0):
        if not (0 <= y < self.h):
            return
        x0 = max(0, int(x0))
        x1 = min(self.w - 1, int(x1))
        if x1 < x0:
            return
        i = (y * self.w + x0) * 3
        n = x1 - x0 + 1
        if alpha >= 1.0:
            row = bytes(color) * n
            self.buf[i:i + n * 3] = row
        else:
            for x in range(x0, x1 + 1):
                self.blend(x, y, color, alpha)

    def fill_rect(self, x0, y0, x1, y1, color, alpha=1.0):
        for y in range(max(0, int(y0)), min(self.h, int(y1) + 1)):
            self.hline(x0, x1, y, color, alpha)

    def vgrad_rect(self, x0, y0, x1, y1, top, bottom):
        """Vertical gradient rectangle."""
        y0i = max(0, int(y0))
        y1i = min(self.h - 1, int(y1))
        span = max(1, y1 - y0)
        for y in range(y0i, y1i + 1):
            t = (y - y0) / span
            self.hline(x0, x1, y, mix(top, bottom, t))

    def hgrad_rect(self, x0, y0, x1, y1, left, right):
        span = max(1, x1 - x0)
        for x in range(max(0, int(x0)), min(self.w, int(x1) + 1)):
            t = (x - x0) / span
            c = mix(left, right, t)
            for y in range(max(0, int(y0)), min(self.h, int(y1) + 1)):
                self.set(x, y, c)

    def ellipse(self, cx, cy, rx, ry, color, alpha=1.0):
        """Filled ellipse."""
        if rx <= 0 or ry <= 0:
            return
        for y in range(max(0, int(cy - ry)), min(self.h, int(cy + ry) + 1)):
            dy = (y - cy) / ry
            dx = math.sqrt(max(0.0, 1.0 - dy * dy)) * rx
            self.hline(cx - dx, cx + dx, y, color, alpha)

    def soft_ellipse(self, cx, cy, rx, ry, color, peak_alpha, layers=6):
        """Layered translucent ellipses: a soft, feathered shadow/glow."""
        for k in range(layers, 0, -1):
            t = k / layers
            self.ellipse(cx, cy, rx * t, ry * t, color,
                         peak_alpha * (1.0 - t * 0.75) / layers * 2.2)

    def rounded_rect(self, x0, y0, x1, y1, r, top, bottom):
        """Rounded rectangle filled with a vertical gradient."""
        r = min(r, (x1 - x0) / 2.0, (y1 - y0) / 2.0)
        span = max(1.0, y1 - y0)
        for y in range(max(0, int(y0)), min(self.h, int(y1) + 1)):
            t = (y - y0) / span
            c = mix(top, bottom, t)
            xa, xb = x0, x1
            if y < y0 + r:
                dy = (y0 + r) - y
                dx = math.sqrt(max(0.0, r * r - dy * dy))
                xa, xb = x0 + r - dx, x1 - r + dx
            elif y > y1 - r:
                dy = y - (y1 - r)
                dx = math.sqrt(max(0.0, r * r - dy * dy))
                xa, xb = x0 + r - dx, x1 - r + dx
            self.hline(xa, xb, y, c)

    def disc(self, cx, cy, r, color, alpha=1.0):
        self.ellipse(cx, cy, r, r, color, alpha)

    def thick_line(self, x0, y0, x1, y1, width, color, alpha=1.0):
        """A line drawn as a chain of discs (round caps)."""
        dx, dy = x1 - x0, y1 - y0
        dist = math.hypot(dx, dy)
        steps = max(1, int(dist))
        r = width / 2.0
        for s in range(steps + 1):
            t = s / steps
            self.disc(x0 + dx * t, y0 + dy * t, r, color, alpha)

    def polygon(self, pts, color, alpha=1.0):
        """Scanline fill of a convex (or simple) polygon."""
        if len(pts) < 3:
            return
        ys = [p[1] for p in pts]
        y0 = max(0, int(math.ceil(min(ys))))
        y1 = min(self.h - 1, int(math.floor(max(ys))))
        n = len(pts)
        for y in range(y0, y1 + 1):
            xs = []
            for i in range(n):
                x0, y_a = pts[i]
                x1, y_b = pts[(i + 1) % n]
                if (y_a <= y < y_b) or (y_b <= y < y_a):
                    t = (y - y_a) / (y_b - y_a)
                    xs.append(x0 + t * (x1 - x0))
            if len(xs) >= 2:
                xs.sort()
                self.hline(xs[0], xs[-1], y, color, alpha)

    def quad(self, x0, y0, x1, y1, x2, y2, x3, y3, color, alpha=1.0):
        self.polygon([(x0, y0), (x1, y1), (x2, y2), (x3, y3)], color, alpha)


# ---------------------------------------------------------------------------
# Tiny 5x7 bitmap font (capitals, digits, space, dash, dot)
# ---------------------------------------------------------------------------

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
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00110", "01000", "10000", "11111"),
    "3": ("11111", "00010", "00100", "00010", "00001", "10001", "01110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    "-": ("00000", "00000", "00000", "01110", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
}


def text_width(text, scale):
    return len(text) * 6 * scale - scale


def draw_text(cv, x, y, text, scale, color, angle_deg=0.0, alpha=1.0):
    """Draw text at (x, y) = top-left of the first glyph; optional rotation
    (degrees, counter-clockwise) about the text's top-left corner."""
    ang = math.radians(angle_deg)
    ca, sa = math.cos(ang), math.sin(ang)
    cx = 0
    for ch in text:
        glyph = FONT.get(ch, FONT[" "])
        for gy in range(7):
            row = glyph[gy]
            for gx in range(5):
                if row[gx] == "1":
                    for sy in range(scale):
                        for sx in range(scale):
                            px = cx + gx * scale + sx
                            py = gy * scale + sy
                            rx = x + px * ca - py * sa
                            ry = y + px * sa + py * ca
                            cv.blend(int(round(rx)), int(round(ry)),
                                    color, alpha)
        cx += 6 * scale


# ---------------------------------------------------------------------------
# Scene: studio backdrop
# ---------------------------------------------------------------------------

def draw_backdrop(cv):
    # Seamless light-grey studio backdrop: soft vertical gradient, brighter
    # toward the centre-top where the key light sits.
    cv.vgrad_rect(0, 0, W - 1, H - 1, (240, 241, 244), (203, 205, 210))
    # Gentle radial lift behind the product.
    for r in range(420, 0, -28):
        t = r / 420.0
        cv.ellipse(512, 430, r, int(r * 0.78), (246, 246, 248),
                   0.10 * (1.0 - t))
    # Floor line and a slightly darker floor band for grounding.
    cv.vgrad_rect(0, 742, W - 1, H - 1, (196, 198, 203), (178, 180, 186))
    cv.hline(0, W - 1, 742, (168, 170, 176), 0.55)
    # Soft elliptical floor shadow under the whole product group.
    cv.soft_ellipse(500, 790, 350, 40, (60, 62, 70), 0.34)
    cv.soft_ellipse(500, 788, 250, 28, (60, 62, 70), 0.30)


# ---------------------------------------------------------------------------
# Scene: the torch (hero, left) — switched ON
# ---------------------------------------------------------------------------

# Torch geometry (all in canvas pixels).
TORCH_X0, TORCH_X1 = 128, 560   # body ends where the bezel begins
TORCH_Y0, TORCH_Y1 = 428, 566   # body top / bottom
BEZEL_X1 = 648                  # front face of the head
LENS_CX, LENS_CY = 640, 497     # lens centre


def draw_torch(cv):
    # -- tail cap (left end): slightly darker, with knurled rings.
    cv.rounded_rect(TORCH_X0, TORCH_Y0, TORCH_X0 + 66, TORCH_Y1, 20,
                    (58, 62, 70), (30, 32, 38))
    for rx in (TORCH_X0 + 18, TORCH_X0 + 34, TORCH_X0 + 50):
        cv.fill_rect(rx, TORCH_Y0 + 4, rx + 5, TORCH_Y1 - 4, (22, 24, 28),
                     0.85)

    # -- main body: brushed gunmetal, bright on top, dark underneath.
    cv.rounded_rect(TORCH_X0 + 58, TORCH_Y0, TORCH_X1, TORCH_Y1, 26,
                    (96, 101, 112), (34, 37, 44))
    # Brushed-metal sheen: a pale highlight stripe along the top third.
    cv.rounded_rect(TORCH_X0 + 66, TORCH_Y0 + 10, TORCH_X1 - 8,
                    TORCH_Y0 + 34, 12, (150, 156, 168), (96, 101, 112))
    # A thin bright edge line right under the top rim.
    cv.hline(TORCH_X0 + 70, TORCH_X1 - 10, TORCH_Y0 + 6, (188, 192, 202),
             0.7)
    # Darker belly for a cylindrical read.
    cv.rounded_rect(TORCH_X0 + 66, TORCH_Y1 - 30, TORCH_X1 - 8, TORCH_Y1 - 4,
                    12, (40, 43, 50), (20, 22, 27))

    # -- rubber grip rings: two matte black bands around the body.
    for gx in (300, 348):
        cv.fill_rect(gx, TORCH_Y0 + 2, gx + 22, TORCH_Y1 - 2, (18, 19, 22),
                     0.95)
        cv.fill_rect(gx + 3, TORCH_Y0 + 2, gx + 6, TORCH_Y1 - 2,
                     (52, 54, 60), 0.8)
        cv.fill_rect(gx + 16, TORCH_Y0 + 2, gx + 19, TORCH_Y1 - 2,
                     (52, 54, 60), 0.8)

    # -- red power button on top, with a small chrome ring.
    cv.rounded_rect(408, 408, 452, 428, 9, (170, 172, 178), (120, 123, 130))
    cv.rounded_rect(414, 411, 446, 425, 7, (214, 52, 48), (150, 26, 24))
    cv.ellipse(430, 416, 10, 3, (255, 120, 110), 0.8)

    # -- product label on the body, small clean caps.
    label = "SOLAR TORCH 3000"
    sc = 2
    lw = text_width(label, sc)
    draw_text(cv, 400 - lw // 2, 512, label, sc, (205, 208, 214), alpha=0.95)
    # Small "ON" tick under the button.
    draw_text(cv, 424, 388, "ON", 2, (120, 60, 58), alpha=0.9)

    # -- head / bezel: wider, darker ring around the lens.
    cv.rounded_rect(TORCH_X1 - 6, TORCH_Y0 - 16, BEZEL_X1, TORCH_Y1 + 16, 24,
                    (74, 78, 88), (26, 28, 34))
    cv.rounded_rect(TORCH_X1 + 2, TORCH_Y0 - 10, BEZEL_X1 - 6,
                    TORCH_Y1 + 10, 18, (110, 115, 126), (44, 47, 55))
    # Chrome ring right at the front face.
    cv.rounded_rect(BEZEL_X1 - 14, TORCH_Y0 - 12, BEZEL_X1, TORCH_Y1 + 12,
                    14, (196, 200, 208), (120, 124, 132))

    # -- lens: warm glass, glowing white-hot in the centre.
    cv.ellipse(LENS_CX, LENS_CY, 13, 66, (255, 244, 214))
    cv.ellipse(LENS_CX, LENS_CY, 9, 52, (255, 252, 238))
    cv.ellipse(LENS_CX - 2, LENS_CY, 5, 40, (255, 255, 255))
    # Lens rim highlight.
    cv.ellipse(LENS_CX + 6, LENS_CY - 30, 4, 18, (255, 240, 190), 0.8)
    # Hot glow spilling just past the lens onto the bezel and the air.
    cv.soft_ellipse(LENS_CX + 6, LENS_CY, 60, 84, (255, 214, 130), 0.55)
    cv.soft_ellipse(LENS_CX + 20, LENS_CY, 110, 100, (255, 200, 110), 0.28)


# ---------------------------------------------------------------------------
# Scene: beam, solar panel, cable, instruction card
# ---------------------------------------------------------------------------

# Panel geometry (slightly tilted parallelogram, facing the beam).
PANEL = ((800, 372), (962, 344), (962, 612), (800, 640))


def draw_beam(cv):
    # Warm translucent cone from the lens to the panel face, feathered by
    # layering several nested cones of falling alpha.
    lx, ly = LENS_CX + 8, LENS_CY
    for k, (spread, alpha) in enumerate(((150, 0.10), (120, 0.12),
                                         (92, 0.14), (64, 0.16),
                                         (38, 0.20))):
        cv.polygon([(lx, ly - 34), (800, 372 + 150 - spread),
                    (800, 640 - 150 + spread), (lx, ly + 34)],
                   (255, 208, 110), alpha)
    # Bright core: the hottest part of the beam.
    cv.polygon([(lx, ly - 16), (800, 440), (800, 560), (lx, ly + 16)],
               (255, 232, 160), 0.30)
    # Where the beam lands: a hot oval of light on the panel face.
    cv.soft_ellipse(878, 492, 74, 108, (255, 226, 150), 0.55)


def draw_panel(cv):
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = PANEL
    # Metal frame: draw the panel slightly larger first, in silver.
    cv.quad(x0 - 10, y0 - 8, x1 + 10, y1 - 8, x2 + 10, y2 + 8, x3 - 10,
            y3 + 8, (176, 180, 188))
    cv.quad(x0 - 6, y0 - 5, x1 + 6, y1 - 5, x2 + 6, y2 + 5, x3 - 6, y3 + 5,
            (120, 124, 132))
    # Cell face: deep blue-black with a vertical gradient (lighter at top).
    cv.quad(x0, y0, x1, y1, x2, y2, x3, y3, (16, 26, 52))
    # Per-cell shading: 4 columns x 5 rows of cells, each a slightly
    # different deep blue, so the panel reads as manufactured cells.
    for col in range(4):
        for row in range(5):
            # Interpolate the four corners of this cell.
            def pt(tx, ty):
                top = (lerp(x0, x1, tx), lerp(y0, y1, tx))
                bot = (lerp(x3, x2, tx), lerp(y3, y2, tx))
                return (lerp(top[0], bot[0], ty), lerp(top[1], bot[1], ty))
            ax, ay = pt(col / 4.0, row / 5.0)
            bx, by = pt((col + 1) / 4.0, row / 5.0)
            cx, cy = pt((col + 1) / 4.0, (row + 1) / 5.0)
            dx, dy = pt(col / 4.0, (row + 1) / 5.0)
            shade = 22 + ((col * 5 + row) % 3) * 5
            cv.quad(ax + 2, ay + 2, bx - 2, by + 2, cx - 2, cy - 2, dx + 2,
                    dy - 2, (14, shade + 8, 58 + shade // 2))
    # Thin silver grid lines between cells.
    for col in range(1, 4):
        tx = col / 4.0
        cv.thick_line(lerp(x0, x1, tx), lerp(y0, y1, tx),
                      lerp(x3, x2, tx), lerp(y3, y2, tx), 2,
                      (168, 174, 186), 0.9)
    for row in range(1, 5):
        ty = row / 5.0
        cv.thick_line(lerp(x0, x3, ty), lerp(y0, y3, ty),
                      lerp(x1, x2, ty), lerp(y1, y2, ty), 2,
                      (168, 174, 186), 0.9)
    # Glare: a soft diagonal band of reflected light across the cells.
    cv.quad(830, 360, 900, 348, 850, 620, 780, 628, (255, 255, 255), 0.10)
    cv.quad(860, 356, 890, 350, 845, 616, 812, 622, (255, 255, 255), 0.08)
    # Small junction box at the panel's lower back edge.
    cv.quad(806, 600, 838, 596, 838, 622, 806, 626, (52, 56, 64))
    # Stand: one pole down to a foot bar on the floor.
    cv.thick_line(881, 640, 881, 768, 10, (58, 62, 70))
    cv.thick_line(881, 640, 881, 768, 4, (110, 114, 122), 0.8)
    cv.thick_line(828, 772, 934, 772, 9, (58, 62, 70))
    cv.disc(881, 768, 8, (40, 42, 48))
    # Shadow of the stand on the floor.
    cv.soft_ellipse(881, 782, 70, 10, (60, 62, 70), 0.30)


def draw_cable(cv):
    # A short coiled cable: from the panel's junction box, sagging in a loop
    # down to the floor and back up into the torch's tail cap.
    pts = []
    steps = 60
    # Quadratic bezier: start (822, 612) -> control (560, 830) -> end
    # (176, 556); plus a second sag so the cable visibly loops.
    x0, y0, cx, cy, x1, y1 = 822, 612, 560, 836, 178, 552
    for s in range(steps + 1):
        t = s / steps
        bx = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1
        by = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1
        pts.append((bx, by))
    # Cable body, then a lighter top edge so it reads as a round cord.
    for i in range(len(pts) - 1):
        cv.thick_line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1],
                      8, (30, 32, 36))
    for i in range(0, len(pts) - 1, 2):
        cv.disc(pts[i][0], pts[i][1] - 2, 2, (74, 78, 86), 0.8)
    # Connector plug where the cable meets the torch tail.
    cv.rounded_rect(150, 540, 182, 566, 6, (96, 100, 110), (52, 56, 64))
    # Connector plug where the cable meets the panel.
    cv.rounded_rect(806, 596, 836, 622, 5, (96, 100, 110), (52, 56, 64))


def draw_card(cv):
    # The one accessory: a small white instruction card, leaning against
    # nothing at bottom-left, tilted a few degrees.
    cx, cy = 232, 856
    ang = -7.0
    # Card body: a rotated rounded rectangle, drawn as a rotated quad with
    # a soft drop shadow first.
    def rot(px, py, ox=0, oy=0):
        a = math.radians(ang)
        dx, dy = px - cx + ox, py - cy + oy
        return (cx + dx * math.cos(a) - dy * math.sin(a),
                cy + dx * math.sin(a) + dy * math.cos(a))
    hw, hh = 118, 62
    corners = [rot(cx - hw, cy - hh), rot(cx + hw, cy - hh),
               rot(cx + hw, cy + hh), rot(cx - hw, cy + hh)]
    shadow = [(x + 6, y + 8) for (x, y) in corners]
    cv.polygon(shadow, (60, 62, 70), 0.25)
    cv.polygon(corners, (250, 250, 248))
    cv.polygon(corners, (200, 202, 206), 0.0)  # no-op keeps shape explicit
    # Thin grey border, drawn as four rotated edges.
    for i in range(4):
        x_a, y_a = corners[i]
        x_b, y_b = corners[(i + 1) % 4]
        cv.thick_line(x_a, y_a, x_b, y_b, 2, (196, 198, 202), 0.9)
    # Two lines of small clean caps, rotated with the card.
    line1 = "SOLAR TORCH 3000"
    line2 = "CHARGE IN SUNLIGHT"
    sc = 2
    w1 = text_width(line1, sc)
    w2 = text_width(line2, sc)
    # Top-left of each line in the card's own (unrotated) frame, then rotate
    # the anchor by the same transform used for the corners.
    ax1, ay1 = rot(cx - hw + 14, cy - hh + 16)
    ax2, ay2 = rot(cx - hw + 14, cy - hh + 40)
    draw_text(cv, ax1, ay1, line1, sc, (52, 56, 64), angle_deg=ang)
    draw_text(cv, ax2, ay2, line2, sc, (120, 60, 58), angle_deg=ang)


def main():
    cv = Canvas(W, H)
    draw_backdrop(cv)
    draw_beam(cv)
    draw_panel(cv)
    draw_torch(cv)
    draw_cable(cv)
    draw_card(cv)
    os.makedirs("/output", exist_ok=True)
    write_png("/output/entry.png", W, H, cv.buf)
    print("wrote /output/entry.png")


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
