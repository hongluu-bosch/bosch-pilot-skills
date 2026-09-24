#!/usr/bin/env python3
"""Refresh marked logo images from the canonical asset; requires only Python."""
import base64
import re
import sys
from pathlib import Path

ASSET = Path(__file__).resolve().parents[1] / 'assets' / 'bosch-logo.svg'

def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: embed_logo.py <artifact.html>')
    path = Path(sys.argv[1])
    encoded = 'data:image/svg+xml;base64,' + base64.b64encode(ASSET.read_bytes()).decode('ascii')
    count = 0
    def refresh(match):
        nonlocal count
        tag = match.group()
        if not re.search(r'\bdata-brand-asset\s*=\s*([\'"])assets/bosch-logo\.svg\1', tag):
            return tag
        count += 1
        if re.search(r'\bsrc\s*=', tag):
            return re.sub(r'\bsrc\s*=\s*([\'"])(.*?)\1', lambda _: 'src="'+encoded+'"', tag, flags=re.S)
        return tag[:-1] + ' src="' + encoded + '">'
    updated = re.sub(r'<img\b[^>]*>', refresh, path.read_text(), flags=re.I)
    if not count:
        raise SystemExit('FAIL: no marked logo <img>; add data-brand-asset="assets/bosch-logo.svg"')
    path.write_text(updated, encoding='utf-8')
    print(f'Embedded canonical asset in {count} logo images.')

if __name__ == '__main__':
    main()
