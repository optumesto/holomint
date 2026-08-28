#!/usr/bin/env python3
"""
Synthetic lot photos with known card corners, for testing card detection.

    python3 lotfixtures.py .lotfix        # write the fixture set + ground truth

Exists because a card detector cannot be developed against a description of a
photo. Every fixture here carries the exact quad of every card in it, so a run
can say "found 9 of 11, missed two, and one box is 0.42 IoU" instead of "looks
about right". The cases are the four Mason named: rough rows, fanned and
overlapping, a listing screenshot, and a binder page.

Deliberately NOT photographs. These are stand-ins that reproduce the geometry a
detector has to survive -- rotation, uneven spacing, occlusion, clutter, cards
running off the frame -- and nothing about real card ART. Passing here means the
geometry works; it says nothing about whether a real photo's lighting, glare or
sleeve reflections will behave, which is what the real sample images are for.
"""
import os
import sys
import json
import math
import random

from PIL import Image, ImageDraw, ImageFilter

# 2.5 x 3.5 inches. Everything downstream keys off this ratio.
CARD_W, CARD_H = 250, 350
RATIO = CARD_W / CARD_H


def _card_face(seed):
    """A card-ish rectangle: border, art box, text band. Distinct per seed so a
    detector cannot pass by finding one repeated template."""
    rnd = random.Random(seed)
    img = Image.new("RGB", (CARD_W, CARD_H), (250, 245, 230))
    d = ImageDraw.Draw(img)
    edge = (rnd.randint(150, 230), rnd.randint(120, 200), rnd.randint(30, 90))
    d.rectangle([0, 0, CARD_W - 1, CARD_H - 1], fill=edge)
    d.rectangle([10, 10, CARD_W - 11, CARD_H - 11], fill=(248, 244, 232))
    art = (rnd.randint(40, 200), rnd.randint(40, 200), rnd.randint(40, 200))
    d.rectangle([24, 46, CARD_W - 25, 210], fill=art)
    for _ in range(rnd.randint(3, 7)):           # texture inside the art box
        x0 = rnd.randint(28, CARD_W - 60); y0 = rnd.randint(50, 170)
        d.ellipse([x0, y0, x0 + rnd.randint(16, 48), y0 + rnd.randint(16, 48)],
                  fill=(rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(0, 255)))
    d.rectangle([24, 226, CARD_W - 25, 300], fill=(236, 230, 214))
    for i in range(4):                            # text lines
        d.rectangle([32, 236 + i * 16, CARD_W - 40 - rnd.randint(0, 40), 242 + i * 16],
                    fill=(90, 85, 75))
    return img


def _paste_rot(bg, card, cx, cy, deg, scale):
    """Paste a card rotated about its centre; return its four corners in bg space."""
    w, h = int(CARD_W * scale), int(CARD_H * scale)
    c = card.resize((w, h), Image.LANCZOS)
    rot = c.rotate(deg, expand=True, resample=Image.BICUBIC)
    # Alpha so the background shows outside the rotated card, not a black box.
    mask = Image.new("L", (w, h), 255).rotate(deg, expand=True, resample=Image.BICUBIC)
    bg.paste(rot, (int(cx - rot.width / 2), int(cy - rot.height / 2)), mask)
    r = math.radians(-deg)
    cs, sn = math.cos(r), math.sin(r)
    pts = []
    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        pts.append([round(cx + dx * cs - dy * sn, 1), round(cy + dx * sn + dy * cs, 1)])
    return pts


def _bg(w, h, kind, seed):
    rnd = random.Random(seed)
    if kind == "table":
        base = (rnd.randint(90, 130), rnd.randint(70, 105), rnd.randint(50, 80))
    elif kind == "carpet":
        base = (rnd.randint(40, 70), rnd.randint(45, 75), rnd.randint(55, 90))
    else:
        base = (245, 245, 247)
    img = Image.new("RGB", (w, h), base)
    d = ImageDraw.Draw(img)
    if kind in ("table", "carpet"):               # grain, so it is not a flat fill
        for _ in range(w * h // 220):
            x, y = rnd.randint(0, w - 1), rnd.randint(0, h - 1)
            j = rnd.randint(-18, 18)
            d.point((x, y), fill=tuple(max(0, min(255, c + j)) for c in base))
        img = img.filter(ImageFilter.GaussianBlur(0.6))
    return img


def rough_rows(seed=1):
    """Cards in loose rows: uneven gaps, small angles, not filling the frame."""
    rnd = random.Random(seed)
    W, H = 1000, 750
    bg = _bg(W, H, "table", seed)
    truth = []
    n = 0
    for row in range(3):
        cols = rnd.choice([3, 4])
        y = 150 + row * 230 + rnd.randint(-12, 12)
        x = 150 + rnd.randint(-20, 20)
        for _ in range(cols):
            truth.append(_paste_rot(bg, _card_face(seed * 100 + n), x, y,
                                    rnd.uniform(-7, 7), 0.52))
            x += int(CARD_W * 0.52) + rnd.randint(20, 55)
            n += 1
    return bg, truth, "rough_rows"


def fanned(seed=2):
    """A fan: heavy rotation and each card partly covering the last."""
    rnd = random.Random(seed)
    W, H = 1000, 700
    bg = _bg(W, H, "carpet", seed)
    truth = []
    n = 8
    for i in range(n):
        deg = -46 + i * (92 / (n - 1))
        r = 250
        cx = W / 2 + math.sin(math.radians(deg)) * r * 0.85
        cy = H / 2 + 140 - math.cos(math.radians(deg)) * r * 0.30
        truth.append(_paste_rot(bg, _card_face(seed * 100 + i), cx, cy, -deg, 0.55))
    return bg, truth, "fanned"


def scattered(seed=3):
    """Dropped on a table: free rotation, some overlap, two running off-frame."""
    rnd = random.Random(seed)
    W, H = 1000, 800
    bg = _bg(W, H, "table", seed)
    truth = []
    spots = [(220, 200, -18), (520, 170, 9), (830, 230, 24), (170, 520, 31),
             (470, 560, -6), (780, 600, -29), (980, 430, 12), (60, 330, -8)]
    for i, (cx, cy, deg) in enumerate(spots):
        truth.append(_paste_rot(bg, _card_face(seed * 100 + i), cx, cy, deg, 0.5))
    return bg, truth, "scattered"


def binder(seed=4):
    """A 3x3 page: the regular case the current grid code already handles."""
    W, H = 900, 1150
    bg = _bg(W, H, "flat", seed)
    truth = []
    for r in range(3):
        for c in range(3):
            truth.append(_paste_rot(bg, _card_face(seed * 100 + r * 3 + c),
                                    150 + c * 300, 190 + r * 380, 0, 0.55))
    return bg, truth, "binder"


def listing(seed=5):
    """A marketplace screenshot: UI chrome, text blocks, thumbnails in a strip.
    The thumbnails ARE cards; the chrome is what must not be mistaken for one."""
    W, H = 800, 1000
    bg = _bg(W, H, "flat", seed)
    d = ImageDraw.Draw(bg)
    d.rectangle([0, 0, W, 64], fill=(24, 26, 32))           # app bar
    d.rectangle([16, 24, 300, 44], fill=(210, 214, 222))
    truth = []
    for i in range(3):                                       # thumbnail strip
        truth.append(_paste_rot(bg, _card_face(seed * 100 + i),
                                140 + i * 230, 260, 0, 0.42))
    d.rectangle([40, 470, W - 40, 500], fill=(40, 44, 52))   # title
    for i in range(6):                                       # body text
        d.rectangle([40, 540 + i * 34, W - 60 - (i % 3) * 90, 560 + i * 34],
                    fill=(150, 155, 165))
    d.rectangle([40, 800, 260, 860], fill=(60, 130, 240))    # a big button
    return bg, truth, "listing"


def _persp(img, truth, lean=0.16, tilt=0.06):
    """Re-shoot the whole page from an angle.

    Modelled on Mason's actual photos, which are binder pages held at an angle
    rather than flat scans -- every card becomes a trapezoid, which a uniform
    grid cannot express at all. One homography is applied to the page and the
    SAME homography maps the ground-truth corners, so the truth stays true.
    """
    import numpy as np
    w, h = img.width, img.height
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[w * lean, h * tilt], [w * (1 - lean * 0.35), 0],
                      [w, h * (1 - tilt)], [w * 0.04, h]])

    def solve(a, b):
        M = []
        for (x, y), (u, v) in zip(a, b):
            M.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
            M.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        return np.linalg.solve(np.asarray(M, float), np.asarray(b, float).flatten())

    fwd = solve(src, dst)                     # src -> dst, for the truth points
    inv = solve(dst, src)                     # dst -> src, which is what PIL wants
    out = img.transform((w, h), Image.PERSPECTIVE, inv, resample=Image.BICUBIC,
                        fillcolor=(28, 28, 32))

    def mapf(p):
        a, b_, c, d, e, f, g, hh = fwd
        den = g * p[0] + hh * p[1] + 1
        return [round((a * p[0] + b_ * p[1] + c) / den, 1),
                round((d * p[0] + e * p[1] + f) / den, 1)]

    return out, [[mapf(p) for p in card] for card in truth]


def _sleeve(bg, quadpts, pad=7):
    """A pale sleeve rim just outside each card, like a binder pocket.

    Matters because the detector can lock onto the SLEEVE instead of the card,
    and dHash is framing-sensitive enough that a rim of clear plastic shifts
    every bit. If a fixture has no sleeves, that whole failure never shows up.
    """
    d = ImageDraw.Draw(bg, "RGBA")
    for q in quadpts:
        cx = sum(p[0] for p in q) / 4
        cy = sum(p[1] for p in q) / 4
        grown = [[p[0] + (p[0] - cx) * pad / 100, p[1] + (p[1] - cy) * pad / 100]
                 for p in q]
        d.polygon([tuple(p) for p in grown], outline=(232, 236, 242, 190), width=3)


def binder_angled(seed=6):
    """Image 2 / 3: a 3x3 page shot at an angle, sleeved, on a desk."""
    W, H = 950, 1150
    bg = _bg(W, H, "flat", seed)
    truth = []
    for r in range(3):
        for c in range(3):
            truth.append(_paste_rot(bg, _card_face(seed * 100 + r * 3 + c),
                                    165 + c * 310, 200 + r * 385, 0, 0.56))
    _sleeve(bg, truth)
    return _persp(bg, truth) + ("binder_angled",)


def binder_partial(seed=7):
    """Image 4: zoomed on a page, so cards run off both edges mid-card.

    The case that breaks a uniform grid hardest -- the frame is not the page, so
    equal cells slice through cards rather than between them.
    """
    W, H = 800, 900
    bg = _bg(W, H, "carpet", seed)
    truth, n = [], 0
    for r in range(3):
        for c in range(-1, 3):                # -1 and 2 hang off the edges
            x = 120 + c * 290
            pts = _paste_rot(bg, _card_face(seed * 100 + n), x, 170 + r * 300,
                             0, 0.52)
            n += 1
            # Only score cards that are genuinely mostly visible; a 20%-visible
            # sliver is not something the matcher could ever identify.
            vis = sum(1 for p in pts if 0 <= p[0] <= W and 0 <= p[1] <= H)
            if vis == 4:
                truth.append(pts)
    _sleeve(bg, truth)
    return bg, truth, "binder_partial"


def binder_glare(seed=8):
    """Foil cards under a light: bright hotspots straight across the page.

    Aimed squarely at the global Otsu threshold, which assumes one light level
    for the whole image. If a hotspot splits a card from its own background,
    this is where it shows.
    """
    W, H = 900, 1000
    bg = _bg(W, H, "flat", seed)
    truth = []
    for r in range(3):
        for c in range(3):
            truth.append(_paste_rot(bg, _card_face(seed * 100 + r * 3 + c),
                                    155 + c * 295, 175 + r * 330, 0, 0.5))
    _sleeve(bg, truth)
    gl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(gl)
    g.ellipse([-120, 90, 620, 380], fill=(255, 255, 255, 120))     # sweep one
    g.ellipse([420, 520, 1020, 760], fill=(255, 255, 255, 96))     # sweep two
    gl = gl.filter(ImageFilter.GaussianBlur(48))
    bg = Image.alpha_composite(bg.convert("RGBA"), gl).convert("RGB")
    return bg, truth, "binder_glare"


CASES = [rough_rows, fanned, scattered, binder, listing,
         binder_angled, binder_partial, binder_glare]


def build(outdir):
    os.makedirs(outdir, exist_ok=True)
    manifest = {}
    for fn in CASES:
        img, truth, name = fn()
        path = os.path.join(outdir, name + ".png")
        img.save(path)
        manifest[name] = {"file": name + ".png", "w": img.width, "h": img.height,
                          "cards": truth}
        print(f"  {name:12s} {img.width}x{img.height}  {len(truth)} cards")
    with open(os.path.join(outdir, "truth.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    print(f"\n{len(CASES)} fixtures -> {outdir}")


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else ".lotfix")
