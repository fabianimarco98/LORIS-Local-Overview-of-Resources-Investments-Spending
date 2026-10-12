#!/usr/bin/env python3
"""
Genera l'icona nativa ad alta risoluzione di macOS (AppIcon.icns) per LORIS.
Raffigura il primate Slow Loris (famiglia Lorisidae / Nycticebus) con i suoi enormi
e suggestivi occhi notturni ambrati, mascherina e morbida pelliccia.
"""

import os
import shutil
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw

BASE_DIR = Path(__file__).resolve().parent
CLEAN_PNG = BASE_DIR / "loris_cropped_clean.png"
SOURCE_JPG = Path("/Users/USER/.gemini/antigravity-cli/brain/48fb6923-90b3-4984-8d24-d5665d596256/slow_loris_app_icon_clean_1791663676125.jpg")


def build_icon():
    # 1. Se loris_cropped_clean.png non esiste ma il source JPG sì, rigeneralo
    if not CLEAN_PNG.exists() and SOURCE_JPG.exists():
        img = Image.open(SOURCE_JPG).convert("RGBA")
        cropped = img.crop((168, 168, 856, 856))
        resized = cropped.resize((1024, 1024), Image.Resampling.LANCZOS)

        size = 1024
        margin = 44
        radius = 216
        mask = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle([margin, margin, size - margin, size - margin], radius=radius, fill=255)

        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(resized, (0, 0), mask)

        border_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        b_draw = ImageDraw.Draw(border_img)
        b_draw.rounded_rectangle(
            [margin + 2, margin + 2, size - margin - 2, size - margin - 2],
            radius=radius - 2,
            outline=(56, 189, 248, 130),
            width=5
        )
        out.alpha_composite(border_img)
        out.save(CLEAN_PNG)

    # 2. Carica l'immagine 1024x1024
    if CLEAN_PNG.exists():
        base_icon = Image.open(CLEAN_PNG).convert("RGBA")
    else:
        # Fallback a creazione procedurale
        base_icon = Image.new("RGBA", (1024, 1024), (15, 23, 42, 255))

    iconset_dir = BASE_DIR / "LORIS.iconset"
    if iconset_dir.exists():
        shutil.rmtree(iconset_dir)
    iconset_dir.mkdir(parents=True, exist_ok=True)

    sizes = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]

    for fname, dim in sizes:
        resized = base_icon.resize((dim, dim), Image.Resampling.LANCZOS)
        resized.save(iconset_dir / fname, "PNG")

    icns_path = BASE_DIR / "AppIcon.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)], check=True)
    print(f"✅ AppIcon.icns aggiornata con primate Loris: {icns_path}")


if __name__ == "__main__":
    build_icon()
