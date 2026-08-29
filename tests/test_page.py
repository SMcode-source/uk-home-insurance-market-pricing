"""The published page cannot go quietly stale.

Three ways it could, all silent, all cheap to rule out:

  * a metric is renamed in `evaluate/compare.py` and `ui/render.py` still asks
    for the old name -- the page breaks only when someone regenerates it;
  * a `<!-- gen: -->` marker is removed from the page while `render.py` still
    splices into it, or added while nothing writes it;
  * a chart scale goes back to a hardcoded divisor, so a larger error in a
    future run overflows its track and the bar understates it.

None of these need a model fit, so this file stays fast and runs even when the
machine has no memory to spare for LightGBM.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from mktpricing.evaluate.compare import AGG_COLUMNS

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "ui" / "index.html"


def _render():
    """Load `ui/render.py` by path -- it is a script, not part of the package."""
    spec = importlib.util.spec_from_file_location("render", ROOT / "ui" / "render.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_render_only_asks_for_metrics_the_pipeline_produces():
    render = _render()
    # `regime` is a grouping key rather than a metric, so it is the one name in
    # NEEDS_SUMMARY that legitimately sits outside AGG_COLUMNS.
    asked = set(render.NEEDS_SUMMARY) - {"regime"}
    unknown = asked - set(AGG_COLUMNS)
    assert not unknown, (
        f"ui/render.py reads {sorted(unknown)}, which evaluate/compare.py does "
        "not produce. Either the metric was renamed or the page is asking for "
        "something that never existed."
    )


def test_every_marker_the_renderer_writes_exists_in_the_page():
    """A missing marker makes `render.py` exit; a stray one is dead weight."""
    render = _render()
    src = (ROOT / "ui" / "render.py").read_text(encoding="utf-8")

    written = set(re.findall(r'splice\(page,\s*"([\w-]+)"', src))
    present = set(re.findall(r"<!-- gen:([\w-]+) -->", PAGE.read_text(encoding="utf-8")))

    assert written, "no splice() calls found -- the parser, not the page, is wrong"
    assert written == present, (
        f"render.py writes {sorted(written)} but the page has {sorted(present)}. "
        "Markers and builders are added and removed together."
    )
    assert render.splice  # the function the markers exist for


def test_marker_regions_are_balanced():
    page = PAGE.read_text(encoding="utf-8")
    for name in re.findall(r"<!-- gen:([\w-]+) -->", page):
        assert page.count(f"<!-- gen:{name} -->") == 1
        assert page.count(f"<!-- /gen:{name} -->") == 1, (
            f"gen:{name} is opened but never closed, so splice() would eat the "
            "rest of the page"
        )


def test_chart_scales_stay_data_driven():
    """A hardcoded divisor silently understates any bar that outgrows it."""
    page = PAGE.read_text(encoding="utf-8")
    for prop in ("--was", "--now", "--v"):
        # `.+?` rather than `[^)]+?`: the divisor is itself a var() call, so it
        # contains the closing paren a naive character class would stop at.
        rule = re.search(
            rf"calc\(var\({re.escape(prop)}\)\s*/\s*(.+?)\s*\*\s*100%", page)
        assert rule, f"no chart rule found for {prop}"
        assert "var(--scale" in rule.group(1), (
            f"{prop} is divided by {rule.group(1).strip()!r} rather than "
            "var(--scale). render.py sets --scale from the data for a reason."
        )
