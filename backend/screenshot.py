"""
Делает скриншот окна приложения по его заголовку.
Использует ctypes (встроенный) + Pillow (ImageGrab).
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
import time
from pathlib import Path

from PIL import ImageGrab

user32 = ctypes.windll.user32

# Сигнатуры Win32 API
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, wintypes.INT]
user32.ShowWindow.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL

OUT_DIR = Path(r"C:\ggf\docs\screenshots")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SW_RESTORE = 9


def find_and_foreground(title: str) -> wintypes.HWND:
    h = user32.FindWindowW(None, title)
    if not h:
        raise RuntimeError(f"окно '{title}' не найдено")
    if user32.IsIconic(h):
        user32.ShowWindow(h, SW_RESTORE)
        time.sleep(0.4)
    user32.SetForegroundWindow(h)
    time.sleep(0.8)
    return h


def grab_window(title: str, out_name: str) -> Path:
    h = find_and_foreground(title)
    rect = wintypes.RECT()
    user32.GetWindowRect(h, ctypes.byref(rect))
    bbox = (rect.left, rect.top, rect.right, rect.bottom)
    print(f"окно bbox: {bbox}  ({rect.right-rect.left}x{rect.bottom-rect.top})")
    img = ImageGrab.grab(bbox=bbox, all_screens=True)
    out = OUT_DIR / out_name
    img.save(out)
    print(f"saved: {out}  size={img.size}")
    return out


if __name__ == "__main__":
    import sys
    title = sys.argv[1] if len(sys.argv) > 1 else "Yandex Maps Scraper"
    name = sys.argv[2] if len(sys.argv) > 2 else "01-main.png"
    grab_window(title, name)
