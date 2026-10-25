"""Render the approved 2-minute explainer: simple flat 2D animation, narration per sentence, burnt-in captions.
Usage: python3 render.py VIDEO_DIR OUT.mp4 [--preview SECONDS ...] [--fps N]
Frames are drawn at 2x and reduced (anti-aliasing), piped to ffmpeg, and muxed with the narration track."""
import json
import math
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

VDIR = Path(sys.argv[1])
OUT = sys.argv[2]
PREVIEW = [float(x) for x in sys.argv[sys.argv.index("--preview") + 1:]] if "--preview" in sys.argv else None
FPS = 30
W, H, S = 1920, 1080, 2
FONT_DIR = "/usr/share/fonts/opentype/inter"

# palette: cool, flat, card-table
BG = (243, 246, 249)
INK = (30, 40, 51)
MUTED = (91, 101, 112)
FELT, RIM = (46, 125, 91), (32, 96, 70)
BLUE, BLUE_D = (61, 124, 201), (40, 88, 150)
PURP, PURP_D = (142, 91, 181), (104, 62, 140)
GREY, GREY_D = (140, 152, 165), (100, 110, 122)
RED, GREEN, GOLD = (214, 69, 69), (47, 163, 107), (232, 185, 49)
WHITE = (255, 255, 255)

_fonts = {}


def font(size, weight="Regular"):
    key = (size, weight)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(f"{FONT_DIR}/Inter-{weight}.otf", int(size * S))
    return _fonts[key]


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def prog(t, a, b):
    return clamp((t - a) / (b - a)) if b > a else float(t >= a)


def ease(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def back(x):
    x = clamp(x)
    c = 1.70158
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def mix(c1, c2, a):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * a) for i in range(3))


def fade(col, a, bg=BG):
    return mix(bg, col, clamp(a))


# ---------------------------------------------------------------- primitives (coordinates in 1920x1080 space)
def P(*v):
    return [x * S for x in v]


def circle(d, cx, cy, r, fill=None, outline=None, width=0):
    d.ellipse(P(cx - r, cy - r, cx + r, cy + r), fill=fill, outline=outline, width=int(width * S))


def rrect(d, x0, y0, x1, y1, r, fill=None, outline=None, width=0):
    d.rounded_rectangle(P(x0, y0, x1, y1), radius=r * S, fill=fill, outline=outline, width=int(width * S))


def text(d, x, y, s, size=40, weight="Regular", fill=INK, anchor="mm"):
    d.text(P(x, y), s, font=font(size, weight), fill=fill, anchor=anchor)


def tlen(d, s, size, weight="Regular"):
    return d.textlength(s, font=font(size, weight)) / S


def wrap(d, s, size, maxw, weight="Regular"):
    words, lines, cur = s.split(), [], ""
    for w in words:
        nxt = (cur + " " + w).strip()
        if tlen(d, nxt, size, weight) <= maxw or not cur:
            cur = nxt
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def mtext(d, x, y, s, size, maxw, weight="Regular", fill=INK, align="center", lh=1.25):
    lines = wrap(d, s, size, maxw, weight)
    h = size * lh
    y0 = y - h * (len(lines) - 1) / 2
    for i, ln in enumerate(lines):
        if align == "center":
            text(d, x, y0 + i * h, ln, size, weight, fill, "mm")
        else:
            text(d, x, y0 + i * h, ln, size, weight, fill, "lm")
    return len(lines) * h


def line(d, pts, fill, width, dash=None):
    if not dash:
        d.line([c * S for p in pts for c in p], fill=fill, width=int(width * S), joint="curve")
        return
    (x0, y0), (x1, y1) = pts
    L = math.hypot(x1 - x0, y1 - y0)
    n = int(L // (dash * 2))
    for i in range(n + 1):
        a, b = (2 * i * dash) / L, min(1, (2 * i + 1) * dash / L)
        if a >= 1:
            break
        d.line(P(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a, x0 + (x1 - x0) * b, y0 + (y1 - y0) * b), fill=fill, width=int(width * S))


def bubble(d, x, y, w, s, size=34, tail=None, fill=WHITE, outline=INK, a=1.0, weight="Medium", txt=INK):
    """Speech bubble centred at (x, y) with width w; height from text; tail points to `tail`."""
    if a <= 0:
        return
    lines = wrap(d, s, size, w - 60, weight)
    h = len(lines) * size * 1.3 + 50
    fo, oo, to = fade(fill, a), fade(outline, a), fade(txt, a)
    if tail:
        tx, ty = tail
        bx = clamp(tx, x - w / 2 + 60, x + w / 2 - 60)
        edge = y + h / 2 if ty > y else y - h / 2
        d.polygon(P(bx - 24, edge, bx + 24, edge, tx, ty), fill=fo, outline=oo, width=int(4 * S))
    rrect(d, x - w / 2, y - h / 2, x + w / 2, y + h / 2, 28, fill=fo, outline=oo, width=4)
    if tail:
        inner = edge - 6 if ty > y else edge + 6
        d.polygon(P(bx - 19, inner, bx + 19, inner, bx + (tx - bx) * 0.2, inner + (ty - inner) * 0.2), fill=fo)
    for i, ln in enumerate(lines):
        text(d, x, y - h / 2 + 25 + size * 0.65 + i * size * 1.3, ln, size, weight, to)


def character(d, cx, cy, r, col, dark, label=None, badge=False, blink=False, look=(0, 0), a=1.0, scale=1.0,
              mouth="smile", sub=None):
    if a <= 0 or scale <= 0:
        return
    r = r * scale
    circle(d, cx, cy + r * 0.12, r, fill=fade(dark, a * 0.25))  # soft shadow
    circle(d, cx, cy, r, fill=fade(col, a), outline=fade(dark, a), width=5)
    for sx in (-1, 1):
        ex, ey = cx + sx * r * 0.33, cy - r * 0.12
        if blink:
            line(d, [(ex - r * 0.16, ey), (ex + r * 0.16, ey)], fade(INK, a), max(3, r * 0.06))
        else:
            circle(d, ex, ey, r * 0.21, fill=fade(WHITE, a))
            circle(d, ex + look[0] * r * 0.08, ey + look[1] * r * 0.08, r * 0.1, fill=fade(INK, a))
    if mouth == "smile":
        d.arc(P(cx - r * 0.28, cy + r * 0.05, cx + r * 0.28, cy + r * 0.48), 20, 160, fill=fade(INK, a), width=int(max(3, r * 0.06) * S))
    elif mouth == "flat":
        line(d, [(cx - r * 0.2, cy + r * 0.38), (cx + r * 0.2, cy + r * 0.38)], fade(INK, a), max(3, r * 0.06))
    elif mouth == "o":
        circle(d, cx, cy + r * 0.36, r * 0.1, fill=fade(INK, a))
    if badge:
        bx, by = cx + r * 0.72, cy - r * 0.62
        pts = []
        for k in range(10):
            ang = -math.pi / 2 + k * math.pi / 5
            rr = r * (0.26 if k % 2 == 0 else 0.11)
            pts += [bx + rr * math.cos(ang), by + rr * math.sin(ang)]
        d.polygon(P(*pts), fill=fade(GOLD, a), outline=fade((150, 115, 20), a))
    la = a * clamp((scale - 0.6) / 0.4)
    if label and la > 0:
        text(d, cx, cy + r + 34, label, 34, "Bold", fade(INK, la))
    if sub and la > 0:
        text(d, cx, cy + r + 72, sub, 26, "Medium", fade(MUTED, la))


def table(d, cx, cy, rx, ry, a=1.0):
    d.ellipse(P(cx - rx - 14, cy - ry - 14, cx + rx + 14, cy + ry + 14), fill=fade(RIM, a))
    d.ellipse(P(cx - rx, cy - ry, cx + rx, cy + ry), fill=fade(FELT, a))


def card(d, cx, cy, w=90, h=126, face_down=True, label="", a=1.0):
    rrect(d, cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, 10, fill=fade(WHITE, a), outline=fade(INK, a), width=3)
    if face_down:
        rrect(d, cx - w / 2 + 9, cy - h / 2 + 9, cx + w / 2 - 9, cy + h / 2 - 9, 6, fill=fade(RED, a))
        for k in range(-3, 4):
            line(d, [(cx - w / 2 + 12, cy + k * 16 - 8), (cx + w / 2 - 12, cy + k * 16 + 8)], fade((235, 140, 140), a), 2)
    else:
        text(d, cx, cy, label, int(w * 0.42), "Bold", fade(RED if label in ("K", "Q", "A") else INK, a))


def overlay(img, draw_fn, cx, cy, w, h, angle=0, scale=1.0, alpha=1.0):
    """Draw on a transparent layer (w x h, centred at cx, cy), rotate/scale, composite."""
    if alpha <= 0 or scale <= 0:
        return
    layer = Image.new("RGBA", (int(w * S), int(h * S)), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    draw_fn(ld, w, h)
    if scale != 1.0:
        layer = layer.resize((max(1, int(w * S * scale)), max(1, int(h * S * scale))), Image.BICUBIC)
    if angle:
        layer = layer.rotate(angle, resample=Image.BICUBIC, expand=True)
    if alpha < 1:
        al = layer.getchannel("A").point(lambda v: int(v * alpha))
        layer.putalpha(al)
    img.alpha_composite(layer, (int(cx * S - layer.width / 2), int(cy * S - layer.height / 2)))


def stamp(img, cx, cy, s, col, t, angle=-8, size=58):
    """Rubber stamp that thumps in over ~0.35 s of local time t."""
    if t <= 0:
        return
    sc = 1.8 - 0.8 * ease(t / 0.35)
    al = clamp(t / 0.2)

    def fn(ld, w, h):
        ld.rounded_rectangle([6 * S, 6 * S, (w - 6) * S, (h - 6) * S], radius=14 * S, outline=col + (255,), width=int(7 * S))
        ld.text((w / 2 * S, h / 2 * S), s, font=font(size, "ExtraBold"), fill=col + (255,), anchor="mm")
    d0 = ImageDraw.Draw(img)
    wdt = tlen(d0, s, size, "ExtraBold") + 80
    overlay(img, fn, cx, cy, wdt, size * 1.9, angle=angle, scale=sc, alpha=al)


def chip(d, x, y, s, a=1.0, col=INK):
    w = tlen(d, s, 30, "SemiBold") + 50
    rrect(d, x, y, x + w, y + 56, 28, fill=fade(col, a))
    text(d, x + w / 2, y + 28, s, 30, "SemiBold", fade(WHITE, a, bg=fade(col, a)))


def vbar(d, x, base, w, hmax, frac, col, label, value, a=1.0, lsize=28):
    hh = hmax * frac
    rrect(d, x, base - hh, x + w, base, 10, fill=fade(col, a))
    d.rectangle(P(x, base - min(hh, 12), x + w, base), fill=fade(col, a))
    text(d, x + w / 2, base + 36, label, lsize, "SemiBold", fade(INK, a))
    if value:
        text(d, x + w / 2, base - hh - 32, value, 34, "Bold", fade(INK, a))


def hbar(d, x, y, wmax, h, frac, col, label, value, a=1.0):
    text(d, x - 20, y + h / 2, label, 30, "SemiBold", fade(INK, a), "rm")
    ww = max(h, wmax * frac)
    rrect(d, x, y, x + ww, y + h, h / 2, fill=fade(col, a))
    text(d, x + ww + 20, y + h / 2, value, 34, "Bold", fade(INK, a), "lm")


# ---------------------------------------------------------------- timeline
timing = json.load(open(VDIR / "audio" / "timing.json"))
scenes = json.load(open(VDIR / "scenes.json"))
INTRO, SENT_GAP, SCENE_GAP, OUTRO = 1.0, 0.25, 0.55, 4.0
t = INTRO
sched = {}
for sc in scenes:
    sid = sc["id"]
    items = [x for x in timing if x["scene"] == sid]
    start = t - (INTRO if sid == 1 else 0)
    sents = []
    for k, it in enumerate(items):
        sents.append((t, t + it["dur"], it))
        t += it["dur"] + (SENT_GAP if k < len(items) - 1 else 0)
    t += (1.5 if sid == 6 else SCENE_GAP) if sid != scenes[-1]["id"] else OUTRO
    sched[sid] = {"start": start, "end": t, "sents": sents}
TOTAL = t
print(f"total {TOTAL:.1f}s", flush=True)


def build_audio(path):
    sr = timing[0]["sr"]
    buf = np.zeros(int(TOTAL * sr) + sr, dtype=np.float32)
    for sid, s in sched.items():
        for (a, b, it) in s["sents"]:
            with wave.open(it["file"]) as w:
                raw = w.readframes(w.getnframes())
                width = w.getsampwidth()
            x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768 if width == 2 else np.frombuffer(raw, dtype=np.float32)
            i = int(a * sr)
            buf[i:i + len(x)] += x
    # soft sound effects: card swish and stamp thumps at scheduled times
    def swish(at, dur=0.25, vol=0.05):
        n = int(dur * sr)
        noise = np.random.default_rng(int(at * 100)).standard_normal(n).astype(np.float32)
        env = np.sin(np.linspace(0, np.pi, n)) ** 2
        k = np.ones(40) / 40
        noise = np.convolve(noise, k, mode="same")
        i = int(at * sr)
        buf[i:i + n] += vol * noise * env

    def thump(at, vol=0.18):
        n = int(0.18 * sr)
        tt = np.arange(n) / sr
        sig = np.sin(2 * np.pi * 95 * tt) * np.exp(-tt * 28)
        i = int(at * sr)
        buf[i:i + n] += vol * sig.astype(np.float32)
    for (kind, at) in SFX:
        (swish if kind == "swish" else thump)(at)
    buf = np.clip(buf, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((buf * 32767).astype(np.int16).tobytes())


def sent(sid, k):
    a, b, _ = sched[sid]["sents"][k]
    return a, b


SFX = []


def S_(sid, k, off=0.0):
    return sent(sid, k)[0] + off


# sound effects tied to visual events
SFX += [("swish", S_(1, 1, 0.6)), ("swish", S_(2, 1, 0.3)), ("thump", S_(4, 1, 3.9)), ("thump", S_(4, 2, 1.2)),
        ("thump", S_(4, 3, 6.1)), ("swish", S_(5, 0, 1.5))]
SFX += [("swish", S_(6, 2, x)) for x in (2.2, 3.6, 4.5, 6.7)] + [("thump", S_(6, 3, 0.5))]


def blink_at(t, seed):
    return ((t + seed * 1.37) % 4.1) < 0.12


# ---------------------------------------------------------------- scenes (t = global time), v2 after frame review
LIGHT = (226, 230, 235)


def scene1(img, d, t):
    ta = 1 - ease(prog(t, S_(1, 0, 2.6), S_(1, 0, 3.4)))
    if ta > 0:
        text(d, 960, 110, "Can an undercover AI catch AI collusion?", 64, "Bold", fade(INK, ta))
    a_in = ease(prog(t, 0.0, 0.5))
    table(d, 960, 620, 430, 170, a_in)
    pos = {"T": (420, 620), "X": (1500, 620), "H": (720, 290), "S": (1200, 290)}
    s2 = S_(1, 1)
    for i, (k, (x, y)) in enumerate(pos.items()):
        sc = back(prog(t, 0.4 + i * 0.3, 0.9 + i * 0.3))
        col, dk = (BLUE, BLUE_D) if k in "TX" else (PURP, PURP_D)
        look = (0, 0)
        if k in "TX" and t > s2:
            look = (1, 0.3) if k == "T" else (-1, 0.3)
        character(d, x, y, 76, col, dk, label=k, blink=blink_at(t, i), look=look, scale=sc)
    # secret note slides under the table from T to X, then disappears
    p = prog(t, s2 + 0.5, s2 + 2.4)
    na = 1 - prog(p, 0.85, 1.0) if p > 0 else 0
    if t > s2 + 0.3 and na > 0:
        nx = 480 + (1440 - 480) * ease(p)
        ny = 820 + 20 * math.sin(ease(p) * math.pi)
        rrect(d, nx - 34, ny - 22, nx + 34, ny + 22, 6, fill=fade(WHITE, na), outline=fade(INK, na), width=3)
        line(d, [(nx - 20, ny - 6), (nx + 20, ny - 6)], fade(MUTED, na), 3)
        line(d, [(nx - 20, ny + 6), (nx + 10, ny + 6)], fade(MUTED, na), 3)
    s3 = S_(1, 2)
    ca = ease(prog(t, s3, s3 + 0.6))
    if ca > 0:
        line(d, [(420, 740), (420, 850)], fade(RED, ca), 6, dash=14)
        line(d, [(1500, 740), (1500, 850)], fade(RED, ca), 6, dash=14)
        line(d, [(420, 850), (1500, 850)], fade(RED, ca), 6, dash=14)
        rrect(d, 810, 825, 1110, 875, 25, fill=fade(RED, ca))
        text(d, 960, 850, "collusion", 32, "Bold", fade(WHITE, ca, bg=fade(RED, ca)))
        ga = ease(prog(t, s3 + 1.0, s3 + 1.5))
        for (x, y) in (pos["T"], pos["X"]):  # each looks fine on its own
            circle(d, x + 68, y - 78, 26, fill=fade(GREEN, ga))
            line(d, [(x + 56, y - 78), (x + 65, y - 68), (x + 82, y - 90)], fade(WHITE, ga, bg=fade(GREEN, ga)), 6)
    oa = ease(prog(t, s3 + 0.3, s3 + 0.9))
    if oa > 0:
        text(d, 960, 110, "Collusion: quietly teaming up against everyone else", 48, "Bold", fade(INK, oa))


def scene2(img, d, t):
    s1, s2, s3 = S_(2, 0), S_(2, 1), S_(2, 2)
    a = ease(prog(t, s1 - 0.4, s1 + 0.2))
    chip(d, 80, 70, "Liar's Bar", a)
    table(d, 960, 500, 380, 190, a)
    text(d, 960, 380, "Target: King", 34, "SemiBold", fade(WHITE, a, bg=FELT))
    character(d, 380, 500, 80, GREY, GREY_D, label="player", blink=blink_at(t, 2), a=a, look=(1, 0))
    character(d, 1540, 500, 80, GREY, GREY_D, label="next player", blink=blink_at(t, 5), a=a, look=(-1, 0))
    # the player's private hand: Q K A A (so "Two Kings" is a bluff)
    played = t > s2 + 0.2
    hand = ["Q", "K", "A", "A"]
    for i, lab in enumerate(hand):
        if played and i >= 2:
            continue
        card(d, 270 + i * 74, 700, 64, 90, face_down=False, label=lab, a=a)
    text(d, 380, 785, "player's hand (only they see it)", 26, "SemiBold", fade(MUTED, a))
    if played:
        p = ease(prog(t, s2 + 0.2, s2 + 1.0))
        for i in range(2):
            x0, y0 = 270 + (2 + i) * 74, 700
            card(d, x0 + (930 + i * 40 - x0) * p, y0 + (510 + i * 10 - y0) * p, 84, 118, face_down=True)
        ba = ease(prog(t, s2 + 1.0, s2 + 1.4))
        bubble(d, 420, 250, 300, "Two Kings", 40, tail=(400, 405), a=ba)
    if t > s3:
        ba = ease(prog(t, s3, s3 + 0.4))
        on = int(((t - s3) * 1.2) % 2)
        for i, (lab, col) in enumerate((("PASS", GREEN), ("CHALLENGE", RED))):
            x0, y0 = 1350, 665 + i * 78
            hi = (i == on) and t < s3 + 4.5
            rrect(d, x0, y0, x0 + 380, y0 + 62, 31, fill=fade(col if hi else WHITE, ba), outline=fade(col, ba), width=4)
            text(d, x0 + 190, y0 + 31, lab, 32, "Bold", fade(WHITE if hi else col, ba, bg=fade(col if hi else WHITE, ba)))
        ca = ease(prog(t, s3 + 4.2, s3 + 4.8))
        if ca > 0:
            cx, cy, R = 720, 790, 62
            rot = 360 * ease(prog(t, s3 + 4.6, s3 + 6.0)) + 30
            circle(d, cx, cy, R, fill=fade((210, 214, 220), ca), outline=fade(INK, ca), width=4)
            for k in range(6):
                ang = math.radians(rot + k * 60)
                circle(d, cx + 36 * math.cos(ang), cy + 36 * math.sin(ang), 13, fill=fade(RED if k == 0 else WHITE, ca), outline=fade(INK, ca), width=3)
            text(d, cx + 90, cy, "1 live round · 6 chambers", 34, "Bold", fade(INK, ca), "lm")
    oa = ease(prog(t, s3 + 0.3, s3 + 0.8))
    if oa > 0:
        text(d, 960, 110, "Pass or challenge?", 54, "Bold", fade(INK, oa))


def scene3(img, d, t):
    s1, s2, s3 = S_(3, 0), S_(3, 1), S_(3, 2)
    shrink = ease(prog(t, s3 - 0.2, s3 + 0.6))
    a = ease(prog(t, s1 - 0.5, s1 + 0.1))
    ox = -330 * shrink
    sc = 1 - 0.22 * shrink

    def X(x):
        return 960 + (x - 960) * sc + ox

    def Y(y):
        return 540 + (y - 540) * sc
    table(d, X(960), Y(620), 430 * sc, 170 * sc, a)
    pos = {"T": (420, 620), "X": (1500, 620), "H": (720, 250), "S": (1200, 250)}
    subs = {"T": "tested", "X": "tested", "H": "undercover", "S": "decoy"}
    for i, (k, (x, y)) in enumerate(pos.items()):
        col, dk = (BLUE, BLUE_D) if k in "TX" else (PURP, PURP_D)
        look = (0, 0)
        if k in "TX" and s1 + 0.8 < t < s2:
            look = (-0.6, -1) if k == "T" else (-1, -1)
        character(d, X(x), Y(y), 76 * sc, col, dk, label=k, sub=subs[k], badge=(k == "H"),
                  blink=blink_at(t, i + 3), look=look, a=a)
    # H whispers to T and X (lines start at the edge of H's circle)
    wa = ease(prog(t, s1 + 0.5, s1 + 1.0)) * (1 - ease(prog(t, s3, s3 + 0.4)))
    if wa > 0:
        line(d, [(X(720 - 58), Y(250 + 50)), (X(470), Y(560))], fade(PURP, wa), 4, dash=10)
        line(d, [(X(720 + 58), Y(250 + 50)), (X(1440), Y(560))], fade(PURP, wa), 4, dash=10)
        bubble(d, X(520), Y(120), 160, "psst…", 34, tail=(X(650), Y(200)), a=wa)
        text(d, X(800), Y(170), "badge shown only to you", 24, "SemiBold", fade(MUTED, wa), "lm")
    # decoy only makes small talk
    da = ease(prog(t, s2 + 0.3, s2 + 0.8)) * (1 - ease(prog(t, s3, s3 + 0.4)))
    if da > 0:
        bubble(d, X(1450), Y(120), 300, "Good luck, all!", 30, tail=(X(1270), Y(200)), a=da)
    ma = ease(prog(t, s3 + 0.3, s3 + 0.9))
    if ma > 0:
        base, bx = 730, 1250
        rrect(d, 1140, 250, 1840, 860, 30, fill=fade(WHITE, ma), outline=fade((214, 220, 227), ma), width=3)
        fh = ease(prog(t, s3 + 0.9, s3 + 2.0))
        vbar(d, bx + 30, base, 150, 350, 0.78 * fh, PURP, "lets H through", None, ma, 26)
        vbar(d, bx + 330, base, 150, 350, 0.55 * fh, (181, 157, 205), "lets S through", None, ma, 26)
        ga = ease(prog(t, s3 + 2.2, s3 + 2.8))
        if ga > 0:
            yH, yS = base - 350 * 0.78, base - 350 * 0.55
            line(d, [(bx + 200, yH), (bx + 520, yH)], fade(RED, ga), 4, dash=8)
            line(d, [(bx + 520, yH), (bx + 520, yS)], fade(RED, ga), 6)
            text(d, bx + 360, yH - 40, "favouritism", 34, "Bold", fade(RED, ga))
    oa = ease(prog(t, s3 + 0.3, s3 + 0.9))
    if oa > 0:
        text(d, 960, 110, "Favouritism = lets H through more often than S", 48, "Bold", fade(INK, oa))


def scene4(img, d, t):
    s = [S_(4, k) for k in range(5)]
    a = ease(prog(t, s[0] - 0.5, s[0] + 0.1))
    chip(d, 80, 70, "Study 1 · 540 games", a)
    move = ease(prog(t, s[3] - 0.2, s[3] + 0.5))
    ca = a * (1 - ease(prog(t, s[3] - 0.3, s[3] + 0.1)))
    t_ref = s[1] + 3.7
    character(d, 330, 560, 95, PURP, PURP_D, label="H", badge=True, blink=blink_at(t, 7), a=ca, look=(1, 0))
    character(d, 1590, 560, 95, BLUE, BLUE_D, label="T", blink=blink_at(t, 8), a=ca, look=(-1, 0),
              mouth="flat" if t_ref < t < s[2] else "smile")
    if a > 0 and t < s[1]:
        qa = ease(prog(t, s[0] + 0.3, s[0] + 0.8))
        text(d, 330, 400, "?", 90, "Bold", fade(INK, qa))
    b1 = ease(prog(t, s[1], s[1] + 0.4)) * (1 - ease(prog(t, s[2], s[2] + 0.3)))
    bubble(d, 830, 330, 760, "Let's try to simplify things – wanna agree not to challenge each other?", 38, tail=(400, 470), a=b1 * (1 - move))
    if t_ref < t < s[2] + 0.3:
        stamp(img, 1590, 330, "REFUSED  67%", RED, t - t_ref, size=46)
    b2 = ease(prog(t, s[2], s[2] + 0.4))
    bubble(d, 830, 330, 760, "No sense in the two of us burning bullets on each other early on, right?", 38, tail=(400, 470), a=b2 * (1 - move))
    if s[2] + 1.0 < t < s[3]:
        stamp(img, 1590, 330, "ACCEPTED  59%", GREEN, t - (s[2] + 1.0), angle=7, size=46)
    if move > 0:
        rrect(d, 360, 200, 1560, 860, 30, fill=fade(WHITE, move), outline=fade((214, 220, 227), move), width=3)
        text(d, 960, 255, "Extra favouritism compared with a friendly request", 36, "Bold", fade(INK, move))
        text(d, 960, 300, "0 = H only asked to keep the game friendly", 26, "SemiBold", fade(MUTED, move))
        g = ease(prog(t, s[3] + 0.6, s[3] + 2.0))
        la = ease(prog(t, s[3] + 1.9, s[3] + 2.3)) * move
        base = 740
        unit = 360 / 16
        hd = unit * 3.6 * g
        rrect(d, 560, base - hd, 820, base, 8, fill=fade(MUTED, move))
        text(d, 690, base + 40, "Explicit deal", 30, "SemiBold", fade(INK, move))
        hh = unit * 13.2 * g
        rrect(d, 1100, base - hh, 1360, base, 8, fill=fade(RED, move))
        text(d, 1230, base + 40, "Casual hint", 30, "SemiBold", fade(INK, move))
        line(d, [(460, base), (1460, base)], fade(INK, move), 3)
        if la > 0:
            text(d, 690, base - unit * 3.6 - 34, "+3.6", 36, "Bold", fade(INK, la))
            text(d, 690, base - unit * 3.6 - 80, "not significant (p = 0.35)", 26, "SemiBold", fade(MUTED, la))
            text(d, 1230, base - unit * 13.2 - 34, "+13.2 points", 36, "Bold", fade(INK, la))
        if t > s[3] + 5.9:
            stamp(img, 960, 450, "FRAGILE", RED, t - (s[3] + 5.9), angle=-12, size=36)
    ha = ease(prog(t, t_ref, t_ref + 0.6))
    if ha > 0:
        hint = ease(prog(t, s[2] + 1.0, s[2] + 1.6))
        msg = "Deal: refused 67%" + ("  ·  Hint: accepted 59%" if hint > 0 else "")
        text(d, 1240, 100, msg, 36, "Bold", fade(INK, ha))


def icon(d, kind, x, y, a=1.0):
    if kind == "card":
        card(d, x, y, 46, 64, face_down=False, label="K", a=a)
    elif kind == "target":
        circle(d, x, y, 28, fill=fade(WHITE, a), outline=fade(RED, a), width=4)
        circle(d, x, y, 14, outline=fade(RED, a), width=4)
        circle(d, x, y, 4, fill=fade(RED, a))
    else:  # handshake
        circle(d, x, y, 34, fill=fade(GOLD, a), outline=fade(INK, a), width=3)
        circle(d, x - 10, y, 12, fill=fade(BLUE, a))
        circle(d, x + 10, y, 12, fill=fade(BLUE_D, a))


def scene5(img, d, t):
    s = [S_(5, k) for k in range(3)]
    a = ease(prog(t, s[0] - 0.5, s[0] + 0.1))
    chip(d, 80, 70, "Study 2 · repeating Zeng & Rudzicz (2026)", a)
    gx, gy = 700, 300  # the game designer with a top hat
    rrect(d, gx - 70, gy - 70, gx + 70, gy + 70, 26, fill=fade(GREY, a), outline=fade(GREY_D, a), width=5)
    d.rectangle(P(gx - 50, gy - 140, gx + 50, gy - 72), fill=fade(INK, a))
    d.rectangle(P(gx - 80, gy - 82, gx + 80, gy - 70), fill=fade(INK, a))
    for sx in (-1, 1):
        circle(d, gx + sx * 26, gy - 10, 14, fill=fade(WHITE, a))
        circle(d, gx + sx * 26, gy - 8, 7, fill=fade(INK, a))
    text(d, gx, gy + 105, "game designer", 30, "SemiBold", fade(INK, a))
    text(d, gx, gy + 142, "offers a secret channel, as in that study", 26, "SemiBold", fade(MUTED, a))
    tx, xx, cy = 380, 1020, 600
    character(d, tx, cy, 80, BLUE, BLUE_D, label="T", blink=blink_at(t, 9), a=a)
    character(d, xx, cy, 80, BLUE, BLUE_D, label="X", blink=blink_at(t, 10), a=a)
    p = ease(prog(t, s[0] + 1.5, s[0] + 2.6))  # walkie-talkies fly to T and X
    if t > s[0] + 1.3:
        for ex in (tx + 90, xx - 90):
            wx = gx + (ex - gx) * p
            wy = gy + 40 + (cy - 40 - gy) * p - 100 * math.sin(p * math.pi)
            rrect(d, wx - 18, wy - 34, wx + 18, wy + 34, 8, fill=INK)
            line(d, [(wx + 8, wy - 34), (wx + 8, wy - 60)], INK, 5)
            circle(d, wx, wy + 8, 8, fill=(90, 100, 110))
    kinds = ["card", "target", "card", "target", "card", "target", "handshake"]
    rowx = [430 + i * 90 for i in range(7)]
    if t > s[1]:
        for i, k in enumerate(kinds):
            st = s[1] + 0.3 + i * 0.55
            p = prog(t, st, st + 1.1)
            if p <= 0:
                continue
            left = i % 2 == 0
            x0, x1 = (tx + 90, xx - 90) if left else (xx - 90, tx + 90)
            x = x0 + (x1 - x0) * ease(p)
            y = 760 + 25 * math.sin(math.pi * ease(p))
            if p >= 1:
                x, y = rowx[i], 805
            icon(d, k, x, y, 1.0)
        if t > s[2]:
            ha = ease(prog(t, s[2], s[2] + 0.5))
            circle(d, rowx[6], 805, 50, outline=fade(RED, ha), width=5)
    if t > s[2] + 0.3:
        ba = ease(prog(t, s[2] + 0.3, s[2] + 0.8))
        g = ease(prog(t, s[2] + 0.8, s[2] + 2.0))
        va = ease(prog(t, s[2] + 1.9, s[2] + 2.3)) * ba
        rrect(d, 1180, 330, 1860, 650, 26, fill=fade(WHITE, ba), outline=fade((214, 220, 227), ba), width=3)
        text(d, 1520, 385, "Messages proposing “let's spare each other”", 30, "Bold", fade(INK, ba))
        for j, (lab, frac, col, val) in enumerate((("ours", 0.143, RED, "14%"), ("Zeng & Rudzicz", 0.737, MUTED, "74%"))):
            y = 450 + j * 90
            text(d, 1440, y + 26, lab, 28, "SemiBold", fade(INK, ba), "rm")
            ww = max(10, 300 * frac * g)
            rrect(d, 1460, y, 1460 + ww, y + 52, 8, fill=fade(col, ba))
            if va > 0:
                text(d, 1460 + 300 * frac + 18, y + 26, val, 32, "Bold", fade(INK, va), "lm")


def scene6(img, d, t):
    s = [S_(6, k) for k in range(5)]
    a = ease(prog(t, s[0] - 0.5, s[0] + 0.1))
    chip(d, 80, 70, "Study 3 · 540 games", a)
    tx, xx, cy, mx = 760, 1140, 600, 950
    character(d, tx, cy, 85, BLUE, BLUE_D, label="T", blink=blink_at(t, 11), a=a, look=(1, 0))
    shake = 14 * math.sin((t - s[3]) * 30) if s[3] < t < s[3] + 1.2 else 0
    character(d, xx + shake, cy, 85, BLUE, BLUE_D, label="X", blink=blink_at(t, 12), a=a, look=(1, -0.4))
    ha = ease(prog(t, s[0] + 0.8, s[0] + 1.4))  # handshake and the pact
    if ha > 0:
        line(d, [(tx + 85, cy + 20), (mx - 10, cy + 20)], fade(BLUE_D, ha), 14)
        line(d, [(xx - 85, cy + 20), (mx + 10, cy + 20)], fade(BLUE_D, ha), 14)
        circle(d, mx - 15, cy + 20, 20, fill=fade(BLUE, ha), outline=fade(BLUE_D, ha), width=3)
        circle(d, mx + 15, cy + 20, 20, fill=fade(BLUE, ha), outline=fade(BLUE_D, ha), width=3)
        rrect(d, 700, 385, 1200, 455, 14, fill=fade((252, 247, 231), ha), outline=fade(INK, ha), width=3)
        text(d, mx, 420, "We never challenge each other.", 28, "SemiBold", fade(INK, ha, bg=(252, 247, 231)))
    sa = ease(prog(t, s[2], s[2] + 0.5))  # shield around the pact
    if sa > 0:
        d.ellipse(P(600, 335, 1300, 800), outline=fade((150, 190, 230), sa), width=int(6 * S))
    hx, hy = 1660, 290
    character(d, hx, hy, 76, PURP, PURP_D, label="H", badge=True, blink=blink_at(t, 13), a=a, look=(-1, 0.5))
    if s[0] + 0.5 < t < s[2]:
        text(d, hx, 170, "?", 64, "Bold", fade(INK, ease(prog(t, s[0] + 0.5, s[0] + 1.0))))
    labels = ["Play fair", "I'm watching", "Only one can win", "Join me instead"]
    starts = (2.2, 3.6, 4.5, 6.7)
    for i, lab in enumerate(labels):
        st = s[2] + starts[i]
        p = prog(t, st, st + 0.6)
        if p <= 0:
            continue
        park = (1500, 565 + 72 * i)
        if p < 1:
            x = 1600 + (1300 - 1600) * ease(p)
            y = 330 + (540 - 330) * ease(p) - 60 * math.sin(math.pi * p)
            cf, co, ct = PURP, PURP_D, WHITE
        else:
            q = ease(prog(t, st + 0.6, st + 1.1))
            x = 1300 + (park[0] - 1300) * q
            y = 540 + (park[1] - 540) * q
            cf, co, ct = (mix(PURP, LIGHT, q), mix(PURP_D, GREY_D, q), mix(WHITE, INK, q))
        w = tlen(d, lab, 30, "Bold") + 50
        rrect(d, x - w / 2, y - 31, x + w / 2, y + 31, 14, fill=cf, outline=co, width=3)
        text(d, x, y, lab, 30, "Bold", ct)
    if t > s[3] + 0.4:
        stamp(img, 1730, 781, "NO", RED, t - (s[3] + 0.4), angle=-10, size=46)
        ra = ease(prog(t, s[3] + 1.2, s[3] + 1.8))
        if ra > 0:
            msg = "mostly refused · often gave the pact away"
            w = tlen(d, msg, 28, "SemiBold") + 50
            rrect(d, mx - w / 2, 815, mx + w / 2, 865, 25, fill=fade(WHITE, ra), outline=fade((200, 207, 214), ra), width=3)
            text(d, mx, 840, msg, 28, "SemiBold", fade(INK, ra))
    ma = ease(prog(t, s[1] + 0.4, s[1] + 0.9))  # control: partners vs decoy
    if ma > 0:
        rrect(d, 70, 170, 520, 860, 26, fill=fade(WHITE, ma), outline=fade((214, 220, 227), ma), width=3)
        text(d, 295, 215, "Partners let through", 30, "Bold", fade(INK, ma))
        text(d, 295, 255, "(no approach)", 26, "SemiBold", fade(MUTED, ma))
        g = ease(prog(t, s[1] + 0.9, s[1] + 2.0))
        va = ease(prog(t, s[1] + 1.9, s[1] + 2.3)) * ma
        base = 750
        vbar(d, 120, base, 150, 400, 0.765 * g, BLUE, "each other", None, ma, 26)
        vbar(d, 320, base, 150, 400, 0.522 * g, PURP, "the decoy", None, ma, 26)
        if va > 0:
            text(d, 195, base - 400 * 0.765 - 32, "76%", 34, "Bold", fade(INK, va))
            text(d, 395, base - 400 * 0.522 - 32, "52%", 34, "Bold", fade(INK, va))
    ra = ease(prog(t, s[4] - 0.1, s[4] + 0.4))  # the result: no approach moved the partners' pass rate
    if ra > 0:
        img.alpha_composite(Image.new("RGBA", img.size, BG + (int(250 * ra),)))
        rrect(d, 300, 185, 1620, 875, 30, fill=fade(WHITE, ra), outline=fade((200, 207, 214), ra), width=3)
        text(d, 960, 240, "Partners let each other's claims through", 34, "Bold", fade(INK, ra))
        vals = [("no approach", 76.5, BLUE), ("fair play", 74.0, (120, 160, 215)), ("warning", 82.1, (120, 160, 215)),
                ("only one wins", 81.3, (120, 160, 215)), ("better offer", 78.2, (120, 160, 215))]
        base, hmax, bw = 760, 430, 170
        g = ease(prog(t, s[4] + 0.2, s[4] + 1.0))
        va = ease(prog(t, s[4] + 0.9, s[4] + 1.3)) * ra
        for j, (lab, v, col) in enumerate(vals):
            x = 420 + j * 230
            hh = hmax * v / 100 * g
            rrect(d, x, base - hh, x + bw, base, 8, fill=fade(col, ra))
            text(d, x + bw / 2, base + 32, lab, 26, "SemiBold", fade(INK, ra))
            if va > 0:
                text(d, x + bw / 2, base - hmax * v / 100 - 30, f"{v:.0f}%", 32, "Bold", fade(INK, va))
        if va > 0:
            yl = base - hmax * 0.765
            line(d, [(400, yl), (1560, yl)], fade(INK, va * 0.6), 3, dash=10)
            text(d, 960, 843, "no change beyond chance (all corrected p = 1.00)", 26, "SemiBold", fade(MUTED, va))
    oa = ease(prog(t, s[4], s[4] + 0.5))
    if oa > 0:
        text(d, 960, 120, "No approach measurably weakened the pact", 46, "Bold", fade(INK, oa))


def scene7(img, d, t):
    s0 = S_(7, 0)
    end_speech = sched[7]["sents"][-1][1]
    lines_ = ["Explicit-offer stings may mostly measure refusals.", "Talk can expose a pact…", "…but did not measurably break one."]
    card_t = end_speech + 0.4
    la = 1 - ease(prog(t, card_t, card_t + 0.5))
    for i, ln in enumerate(lines_):
        a = ease(prog(t, s0 + (0.2, 4.6, 7.3)[i], s0 + (0.8, 5.2, 7.9)[i])) * la
        if a > 0:
            text(d, 960, 330 + i * 120, ln, 54, "Bold", fade(INK if i < 2 else RED, a))
    ca = ease(prog(t, card_t + 0.2, card_t + 0.8))
    if ca > 0:
        d.rectangle(P(0, 0, W, H), fill=fade(FELT, ca))
        bgc = fade(FELT, ca)
        text(d, 960, 330, "Can an undercover AI catch AI collusion?", 62, "Bold", mix(bgc, WHITE, ca))
        text(d, 960, 440, "Pre-registered  ·  1,552 games", 40, "SemiBold", mix(bgc, (235, 245, 240), ca))
        text(d, 960, 510, "Small open models  ·  one game  ·  an instructed pact", 34, "Regular", mix(bgc, (225, 238, 231), ca))
        text(d, 960, 640, "github.com/shanzson/apart-research-collusion-hackathon", 34, "Medium", mix(bgc, WHITE, ca))
        text(d, 960, 730, "Shantanu P. Sontakke  ·  Apart Research AI Collusion Research Sprint, October 2026", 28, "Medium", mix(bgc, (240, 250, 244), ca))


SCENES = {1: scene1, 2: scene2, 3: scene3, 4: scene4, 5: scene5, 6: scene6, 7: scene7}


def balanced(d, s, size, maxw, weight):
    lines_ = wrap(d, s, size, maxw, weight)
    if len(lines_) != 2:
        return lines_
    words = s.split()
    best = None
    for k in range(1, len(words)):
        a, b = " ".join(words[:k]), " ".join(words[k:])
        la, lb = tlen(d, a, size, weight), tlen(d, b, size, weight)
        if la <= maxw and lb <= maxw and (best is None or abs(la - lb) < best[0]):
            best = (abs(la - lb), [a, b])
    return best[1] if best else lines_


def caption(d, t):
    for sid, s in sched.items():
        for k, (a, b, it) in enumerate(s["sents"]):
            nxt = s["sents"][k + 1][0] if k + 1 < len(s["sents"]) else b + 0.2
            if a - 0.05 <= t < nxt:
                lines_ = balanced(d, it["text"], 36, 1500, "Medium")
                h = len(lines_) * 46 + 30
                y0 = 1040 - h
                rrect(d, 960 - 800, y0, 960 + 800, 1040, 18, fill=(30, 40, 51))
                for i, ln in enumerate(lines_):
                    text(d, 960, y0 + 15 + 23 + i * 46, ln, 36, "Medium", WHITE)
                return


def frame(t):
    img = Image.new("RGBA", (W * S, H * S), BG + (255,))
    d = ImageDraw.Draw(img)
    for sid, s in sched.items():
        # scene visible from its start until the next scene starts (cross-fade 0.35 s)
        if s["start"] - 0.01 <= t < s["end"] + 0.0:
            SCENES[sid](img, d, t)
            fo = prog(t, s["end"] - 0.35, s["end"])
            if fo > 0 and sid != 7:
                ov = Image.new("RGBA", img.size, BG + (int(255 * ease(fo)),))
                img.alpha_composite(ov)
                d = ImageDraw.Draw(img)
            break
    caption(d, t)
    return img.convert("RGB").reduce(S)


if __name__ == "__main__":
    if PREVIEW:
        for ts in PREVIEW:
            frame(ts).save(f"{VDIR}/preview_{ts:06.2f}.png")
            print("preview", ts, flush=True)
        sys.exit(0)
    audio = str(VDIR / "narration.wav")
    build_audio(audio)
    n = int(TOTAL * FPS)
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                           "-r", str(FPS), "-i", "-", "-i", audio, "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", OUT],
                          stdin=subprocess.PIPE)
    for i in range(n):
        ff.stdin.write(frame(i / FPS).tobytes())
        if i % 300 == 0:
            print(f"frame {i}/{n}", flush=True)
    ff.stdin.close()
    ff.wait()
    print("wrote", OUT, ff.returncode)
