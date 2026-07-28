"""
Генератор иконки приложения — оранжевый пин карты на тёмном фоне.
Как логотип в шапке сайта. Сохраняет .ico (multi-size) и .png (512).
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter


# Палитра (как на сайте)
BG_DARK = (10, 10, 12)          # #0a0a0c — глубокий графит
BG_CARD = (24, 24, 28)          # карточка
ACCENT = (245, 158, 11)         # #f59e0b — янтарный
ACCENT_GLOW = (245, 158, 11, 90)
WHITE = (245, 245, 245)


def draw_icon(size: int) -> Image.Image:
    """Рисует иконку заданного размера."""
    # 2x supersampling для сглаживания
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Скруглённый квадрат — фон
    radius = int(s * 0.22)
    d.rounded_rectangle(
        [(0, 0), (s - 1, s - 1)],
        radius=radius,
        fill=BG_DARK,
    )

    # Лёгкая внутренняя карточка (объём)
    pad = int(s * 0.08)
    d.rounded_rectangle(
        [(pad, pad), (s - pad, s - pad)],
        radius=int(radius * 0.7),
        fill=BG_CARD,
    )

    # Пин-маркер (teardrop): круг + треугольник внизу
    cx, cy = s // 2, int(s * 0.42)
    r = int(s * 0.20)            # радиус круга пина

    # Свечение под пином
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse(
        [(cx - r * 2, cy - r * 2), (cx + r * 2, cy + r * 2)],
        fill=ACCENT_GLOW,
    )
    glow = glow.filter(ImageFilter.GaussianBlur(s * 0.04))
    img = Image.alpha_composite(img, glow)
    d = ImageDraw.Draw(img)

    # Тело пина: круг + хвост
    pin_bottom = int(s * 0.78)
    # Треугольник (хвост пина)
    d.polygon(
        [(cx - r * 0.7, cy + r * 0.5),
         (cx + r * 0.7, cy + r * 0.5),
         (cx, pin_bottom)],
        fill=ACCENT,
    )
    # Круг пина
    d.ellipse(
        [(cx - r, cy - r), (cx + r, cy + r)],
        fill=ACCENT,
    )

    # Внутренний белый круг (дырка пина)
    inner_r = int(r * 0.45)
    d.ellipse(
        [(cx - inner_r, cy - inner_r), (cx + inner_r, cy + inner_r)],
        fill=BG_DARK,
    )

    # Downsampling к целевому размеру
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    out_dir = Path(__file__).resolve().parent.parent / "desktop" / "build"
    out_dir.mkdir(parents=True, exist_ok=True)

    # .ico — electron-builder требует минимум 256x256.
    # PIL корректно пишет multi-size только если первое изображение 256.
    sizes = [256, 128, 64, 48, 32, 24, 16]
    icons = [draw_icon(sz) for sz in sizes]
    ico_path = out_dir / "icon.ico"
    icons[0].save(
        ico_path,
        format="ICO",
        sizes=[(sz, sz) for sz in sizes],
    )
    print(f"saved: {ico_path}  (sizes: {sizes})")

    # PNG 512 для preview / electron-builder fallback
    png_512 = draw_icon(512)
    png_path = out_dir / "icon.png"
    png_512.save(png_path, format="PNG")
    print(f"saved: {png_path}  (512x512)")


if __name__ == "__main__":
    main()
