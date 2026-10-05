"""Rotate the Evergreen menu photos upright before reading them.

The Evergreen photos were taken sideways (text runs top to bottom), so they
are turned 90 degrees counter-clockwise. Writes *_upright.jpeg next to them.
Only needed once, to transcribe menus/evergreen.json. Needs Pillow:
    pip install -r requirements-dev.txt
Usage: python menus/rotate_photos.py
"""
from pathlib import Path

from PIL import Image

here = Path(__file__).parent
for name in ("Evergreen_1", "Evergreen_2"):
    upright = Image.open(here / f"{name}.jpeg").rotate(90, expand=True)
    upright.save(here / f"{name}_upright.jpeg", quality=92)
    print(f"wrote {name}_upright.jpeg")
