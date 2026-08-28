"""Wrap `ui/index.html` into a standalone page for static hosting.

`ui/index.html` is authored as an Artifact fragment: the Artifact runtime
supplies the `<!doctype>`, `<head>` and `<body>` wrapper and a small CSS reset,
so the source file starts at `<title>`. GitHub Pages supplies none of that, so
the same content needs wrapping before it can be served as a plain file.

Keeping one source and generating the other is the point -- two hand-maintained
copies of the same page diverge silently, and the divergence is invisible until
someone reads the stale one.

    python ui/build_public.py path/to/output/index.html
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "index.html"

HEAD = """<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="How accurately a model reproduces what twelve UK home insurers charge, measured on held-out weeks. Synthetic sample data.">
<meta name="robots" content="index, follow">
<style>
  *, *::before, *::after { box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body { margin: 0; }
  img, svg, video { display: block; max-width: 100%; }
  table { border-collapse: collapse; }
</style>
"""

TAIL = """
</body>
</html>
"""


def build(dest: Path) -> Path:
    src = SRC.read_text(encoding="utf-8")
    # The fragment opens with <title> and the font <link>s, which belong in
    # <head>; everything from the first <style> onward is body-safe as written.
    cut = src.index("<style>")
    head_part, body_part = src[:cut], src[cut:]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(HEAD + head_part + "</head>\n<body>\n" + body_part + TAIL,
                    encoding="utf-8")
    return dest


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("public/index.html")
    print(f"wrote {build(out)}")
