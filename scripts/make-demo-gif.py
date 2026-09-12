#!/usr/bin/env python3
"""Render assets/demo.gif from a script of real whichrome output.

Every line of output in DEMO below was captured from a real run of the CLI
(see scripts/capture-demo.sh). Nothing here is mocked up; the registry it ran
against holds example accounts on purpose so a public GIF leaks nothing.

    python scripts/make-demo-gif.py
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "demo.gif"

# Paper terminal, matching the field-guide identity.
PAPER = (237, 230, 214)
INK = (31, 26, 20)
DIM = (124, 113, 99)
RED = (192, 57, 43)
GREEN = (58, 94, 58)

W, H = 900, 590
PAD = 26
LINE = 21
FONT_PATH = "C:/Windows/Fonts/consola.ttf"
FONT_SIZE = 15

# (kind, text)  kind: cmd | out | dim | good | red | blank
DEMO = [
    ("dim", "# Claude's extension tells you this much:"),
    ("cmd", "cat connected.json"),
    ("out", '[{"deviceId":"1ec7d06e-...","name":"Browser 1"},'),
    ("out", ' {"deviceId":"ba237d7c-...","name":"Browser 2"},'),
    ("out", ' {"deviceId":"9653c8f9-...","name":"Browser 3"},'),
    ("out", ' {"deviceId":"09b0a7ec-...","name":"Browser 4"}]'),
    ("blank", ""),
    ("dim", "# Whichrome remembers which is which, and where:"),
    ("cmd", "whichrome roster --connected connected.json"),
    ("out", "This computer: Desk PC (DESKPC)"),
    ("good", "* 1ec7d06e  cyborg    you@example.com       Desk PC   THIS computer"),
    ("out", "  ba237d7c  cyborg-2  you@example.com       Desk PC   recorded here, not proved"),
    ("red", "  9653c8f9  work      work@example.com      Work laptop   REMOTE"),
    ("out", "  09b0a7ec  personal  personal@example.com  Desk PC   recorded here, not proved"),
    ("blank", ""),
    ("cmd", "whichrome resolve cyborg --quiet"),
    ("good", "1ec7d06e-6042-43e8-b2c4-611bd9ec5afe"),
    ("blank", ""),
    ("dim", "# and it proves a browser is really on this machine:"),
    ("cmd", "whichrome beacon start --port 8803 --nonce ctest &"),
    ("out", '{"listening": "http://127.0.0.1:8803/ctest", "nonce": "ctest"}'),
    ("dim", "# whatever you point at that URL must be on this box to reach it"),
    ("cmd", "whichrome beacon check --nonce ctest --port 8803"),
    ("good", '{"hits": 1, "local": true, "nonce": "ctest"}'),
    ("good", "exit 0   proved local"),
]

COLORS = {"cmd": INK, "out": INK, "dim": DIM, "good": GREEN, "red": RED, "blank": INK}


def load_font(size: int):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except OSError:
        for alt in ("C:/Windows/Fonts/cour.ttf", "/System/Library/Fonts/Menlo.ttc",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
            try:
                return ImageFont.truetype(alt, size)
            except OSError:
                continue
        return ImageFont.load_default()


FONT = load_font(FONT_SIZE)
FONT_B = load_font(FONT_SIZE)
TITLE = load_font(13)


def frame(lines, typing=None, cursor=True):
    """lines: list of (kind, text) already 'printed'. typing: partial command being typed."""
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W - 1, H - 1], outline=(200, 190, 172), width=1)
    d.rectangle([8, 8, W - 9, H - 9], outline=(31, 26, 20), width=1)
    d.text((PAD, 16), "whichrome  ·  know which Chrome you're driving", font=TITLE, fill=DIM)
    d.line([PAD, 36, W - PAD, 36], fill=(206, 196, 178), width=1)

    y = 48
    visible = lines[-28:] if len(lines) > 28 else lines
    for kind, text in visible:
        if kind == "blank":
            y += LINE // 2
            continue
        if kind == "cmd":
            d.text((PAD, y), "$", font=FONT, fill=RED)
            d.text((PAD + 16, y), text, font=FONT, fill=INK)
        else:
            d.text((PAD + 16, y), text, font=FONT, fill=COLORS[kind])
        y += LINE

    if typing is not None:
        d.text((PAD, y), "$", font=FONT, fill=RED)
        d.text((PAD + 16, y), typing, font=FONT, fill=INK)
        if cursor:
            wpx = d.textlength(typing, font=FONT)
            d.rectangle([PAD + 16 + wpx + 1, y + 2, PAD + 16 + wpx + 9, y + FONT_SIZE + 3], fill=INK)
    return img


def build():
    frames, durations = [], []
    printed: list[tuple[str, str]] = []

    def push(img, ms):
        frames.append(img)
        durations.append(ms)

    push(frame(printed), 700)
    for kind, text in DEMO:
        if kind == "cmd":
            step = 3
            for i in range(0, len(text) + 1, step):
                push(frame(printed, typing=text[:i]), 26)
            push(frame(printed, typing=text), 260)
            printed.append((kind, text))
            push(frame(printed), 200)
        else:
            printed.append((kind, text))
            # let the eye rest on the lines that carry the point
            hold = 560 if kind in ("good", "red") else (420 if kind == "dim" else 150)
            push(frame(printed), hold)

    push(frame(printed), 2400)  # final beat before the loop

    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        OUT, save_all=True, append_images=frames[1:], duration=durations,
        loop=0, optimize=True, disposal=2,
    )
    kb = OUT.stat().st_size / 1024
    print(f"wrote {OUT} · {len(frames)} frames · {sum(durations)/1000:.1f}s · {kb:.0f} KB")
    if kb > 9000:
        print("WARNING: over 9 MB, GitHub may refuse to render it inline")


if __name__ == "__main__":
    build()
