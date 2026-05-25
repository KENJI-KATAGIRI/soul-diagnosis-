#!/usr/bin/env python3
"""static/*.png から同名 .webp を生成する（元PNGは削除しない）。要: pip install Pillow"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent / "static"
QUALITY = 88


def main() -> None:
    for png in sorted(ROOT.glob("*.png")):
        img = Image.open(png)
        if img.mode == "P":
            img = img.convert("RGBA")
        elif img.mode != "RGBA":
            img = img.convert("RGB")
        out = png.with_suffix(".webp")
        img.save(out, "WEBP", quality=QUALITY, method=6)
        print(f"{png.name} -> {out.name}")


if __name__ == "__main__":
    main()
