#!/usr/bin/env python3
"""Build web/static/img/icons.svg (an SVG <symbol> sprite) from Phosphor icons.

The generated sprite is committed, so you only need this script when you add an icon.

    npm install --prefix /tmp/icons @phosphor-icons/core
    python scripts/build_icons.py /tmp/icons/node_modules/@phosphor-icons/core/assets

Icons are referenced in HTML as:
    <svg class="icon" aria-hidden="true"><use href="/static/img/icons.svg#i-pulse"></use></svg>
Bold weight is the default; fill weight uses the "-fill" suffix (e.g. #i-star-fill).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BOLD = """
arrow-left arrow-right arrow-up-right barbell battery-charging-vertical bell brain broadcast buildings
calendar-blank camera caret-down chart-line-up check check-circle clock copy cpu credit-card database
device-mobile download-simple envelope-simple eye eye-slash file-arrow-down fingerprint first-aid-kit gear
heartbeat hexagon info lightning link list lock-key magnifying-glass minus moon paper-plane-right pause play
plus prohibit pulse receipt robot scales share-network shield-check sign-out sparkle star target trash user
user-circle users-three warning watch x
""".split()

FILL = "star check-circle sparkle hexagon".split()

OUT = Path(__file__).resolve().parent.parent / "web" / "static" / "img" / "icons.svg"


def inner(svg_text: str) -> str:
    match = re.search(r"<svg[^>]*>(.*)</svg>", svg_text, re.S)
    if not match:
        raise ValueError("unexpected icon format")
    return re.sub(r"\s+", " ", match.group(1)).strip()


def main(root: Path) -> None:
    symbols: list[str] = []
    missing: list[str] = []
    for weight, names in (("bold", BOLD), ("fill", FILL)):
        for name in names:
            src = root / weight / (f"{name}-{weight}.svg")
            if not src.exists():
                missing.append(f"{weight}/{name}")
                continue
            sid = f"i-{name}" if weight == "bold" else f"i-{name}-fill"
            symbols.append(f'<symbol id="{sid}" viewBox="0 0 256 256">{inner(src.read_text())}</symbol>')
    if missing:
        sys.exit(f"Missing icons: {', '.join(missing)}")
    OUT.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" style="display:none">\n'
        + "\n".join(symbols)
        + "\n</svg>\n"
    )
    print(f"Wrote {len(symbols)} symbols to {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
