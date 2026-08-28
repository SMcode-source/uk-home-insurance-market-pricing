"""Postcode parsing and geographic risk features.

Turns a UK postcode into the risk drivers the models actually use — flood band,
crime, deprivation, area property value — so the model generalises to postcodes
you have never quoted. A postcode categorical cannot do that, which is the whole
reason this module exists.

Two layers:

**Parsing** works offline, needs no downloads, and is fully tested. Postcode
validation, and derivation of area / district / outcode / sector. Sector
(``BS1 4``) is the granularity most UK insurance rating areas use, and it is the
right join key for property value.

**Enrichment** joins reference datasets. Each source is a small class with a
common interface, so adding one is ~20 lines and the enricher does not change.

The cardinal rule
-----------------
**A missing geo feature is NaN with an explicit flag, never a default.**
Silently substituting "flood band 0" for an unresolved postcode would poison the
model invisibly — it looks like a confident low-risk prediction rather than an
absence of data. Every source reports its resolution rate, and
``GeoEnricher.coverage()`` will tell you before you train.

Data sources
------------
=================  ============================================================
flood              Environment Agency "Flood risk: postcode search tool data"
                   — keyed by postcode, no GIS required. This is the one that
                   makes the module practical.
                   environment.data.gov.uk/dataset/53cba123-71f8-417a-8441-4c7ba111e8e1
area value         HM Land Registry Price Paid Data, aggregated to sector.
                   landregistry.data.gov.uk/app/ppd/ppd_data
                   (their Standard Reports tool aggregates to postcode sector
                   directly, which saves processing the full file)
deprivation        English Indices of Deprivation 2019, LSOA or the postcode
                   lookup tool. imd-by-postcode.opendatacommunities.org
crime              police.uk street-level CSVs, LSOA-coded. data.police.uk/data
postcode -> LSOA   ONS Postcode Directory, Open Geography Portal. Needed only
                   to bridge LSOA-keyed sources such as crime.
subsidence         BGS GeoSure. **Licensed — not free.** Interface only.
=================  ============================================================

England and Wales only for several of these. Scotland and Northern Ireland need
different sources (SIMD, NIMDM, SEPA flood maps); ``GeoEnricher`` will report
those postcodes as unresolved rather than guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# postcode parsing
# ---------------------------------------------------------------------------

# Standard UK postcode grammar. The inward code never uses C, I, K, M, O or V,
# and the second outward letter excludes I, J and Z -- rejecting those catches a
# large share of transcription errors that a looser pattern would let through.
_POSTCODE_RE = re.compile(
    r"^(?P<outcode>"
    r"(?P<area>[A-PR-UWYZ][A-HK-Y]?)"
    r"(?P<district>[0-9][0-9]?|[0-9][A-HJKPS-UW])"
    r")"
    r"(?P<incode>(?P<sector_digit>[0-9])(?P<unit>[ABD-HJLNP-UW-Z]{2}))$"
)

_GIR = "GIR 0AA"  # historic Girobank postcode; valid but matches no pattern


@dataclass(frozen=True)
class PostcodeParts:
    """Decomposition of a UK postcode.

    ``BS1 4DJ`` -> area ``BS``, district ``1``, outcode ``BS1``,
    sector ``BS1 4``, unit ``DJ``.
    """

    raw: str
    normalised: str | None
    area: str | None
    district: str | None
    outcode: str | None
    sector: str | None
    incode: str | None
    unit: str | None
    valid: bool

    @property
    def is_scotland_or_ni(self) -> bool:
        """Rough flag: several English sources will not cover these.

        Not authoritative — postcode areas straddle borders — but good enough to
        warn that coverage will be poor before you discover it in the metrics.
        """
        if not self.area:
            return False
        return self.area in _SCOTLAND_AREAS or self.area == "BT"


# Postcode areas wholly or mostly in Scotland, plus BT for Northern Ireland.
_SCOTLAND_AREAS = {
    "AB", "DD", "DG", "EH", "FK", "G", "HS", "IV", "KA", "KW", "KY",
    "ML", "PA", "PH", "TD", "ZE",
}


def normalise_postcode(value) -> str | None:
    """Upper-case, strip separators, insert the single canonical space.

    Accepts ``bs14dj``, ``BS1  4DJ``, ``BS1-4DJ`` and returns ``BS1 4DJ``.
    Returns None for anything that is not a real postcode.

    Validating here rather than only in ``parse_postcode`` is deliberate. A
    length check alone turns ``"rubbish"`` into ``"RUBB ISH"`` -- a string that
    looks like a postcode, joins to nothing, and appears in the data as an
    unlucky address rather than as junk input. Callers get None or a postcode,
    never a plausible-looking mangling.
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    s = re.sub(r"[^A-Z0-9]", "", str(value).upper())
    if not s:
        return None
    if s == "GIR0AA":
        return _GIR
    if not _POSTCODE_RE.match(s):
        return None
    return f"{s[:-3]} {s[-3:]}"


def parse_postcode(value) -> PostcodeParts:
    """Parse into components. Never raises — check ``.valid``."""
    raw = "" if value is None else str(value)
    norm = normalise_postcode(value)
    if norm is None:
        return PostcodeParts(raw, None, None, None, None, None, None, None, False)

    if norm == _GIR:
        return PostcodeParts(raw, _GIR, "GIR", "", "GIR", "GIR 0", "0AA", "AA", True)

    # normalise_postcode already applied the pattern, so this always matches.
    m = _POSTCODE_RE.match(norm.replace(" ", ""))
    outcode = m.group("outcode")
    return PostcodeParts(
        raw=raw,
        normalised=norm,
        area=m.group("area"),
        district=m.group("district"),
        outcode=outcode,
        sector=f"{outcode} {m.group('sector_digit')}",
        incode=m.group("incode"),
        unit=m.group("unit"),
        valid=True,
    )


def add_postcode_parts(df: pd.DataFrame, postcode_col: str = "postcode") -> pd.DataFrame:
    """Add postcode, outcode, sector, area and validity columns.

    Overwrites ``postcode`` with the normalised form so every downstream join
    uses one spelling. Invalid postcodes keep their original text in
    ``postcode_raw`` for correction.
    """
    out = df.copy()
    parts = [parse_postcode(v) for v in out[postcode_col]]
    out["postcode_raw"] = out[postcode_col]
    out[postcode_col] = [p.normalised for p in parts]
    out["outcode"] = [p.outcode for p in parts]
    out["sector"] = [p.sector for p in parts]
    out["area"] = [p.area for p in parts]
    out["postcode_valid"] = [p.valid for p in parts]
    return out


# ---------------------------------------------------------------------------
# source framework
# ---------------------------------------------------------------------------


def _pick_column(df: pd.DataFrame, candidates, what: str) -> str:
    """Find a column by any of several published names.

    Government CSV headers get renamed between releases. Matching on a list and
    failing with the columns actually present beats a KeyError that makes the
    caller go and open the file themselves.
    """
    lowered = {c.lower().strip(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lowered:
            return lowered[cand.lower()]
    raise KeyError(
        f"could not find the {what} column. Tried {list(candidates)}; "
        f"file has {list(df.columns)[:25]}"
    )


class GeoSource:
    """One reference dataset.

    Subclasses set ``name``, ``provides`` (the columns they add) and ``key``
    (the join granularity: postcode, sector, outcode or lsoa), then implement
    ``load``.
    """

    name = "unnamed"
    provides: tuple = ()
    key = "postcode"

    def __init__(self, path=None, **options):
        self.path = Path(path) if path else None
        self.options = options
        self._table = None

    def available(self) -> bool:
        return self.path is not None and self.path.exists()

    def load(self) -> pd.DataFrame:
        """Return a frame indexed by ``self.key`` with exactly ``provides``."""
        raise NotImplementedError

    def table(self) -> pd.DataFrame:
        if self._table is None:
            self._table = self.load()
        return self._table


# ---------------------------------------------------------------------------
# concrete sources
# ---------------------------------------------------------------------------


class EnvironmentAgencyFlood(GeoSource):
    """Flood risk band per postcode, from the EA postcode search tool dataset.

    The published file counts property receptors in each flood likelihood
    category per postcode. We derive:

      ``flood_band``      0-3 from the highest category with any properties
      ``flood_high_share`` share of properties in High or Medium

    Using the *highest occupied* category rather than the modal one is
    deliberate: insurers underwrite the tail, and a postcode with 90% Very Low
    and 10% High is not a low-risk postcode to an underwriter.
    """

    name = "ea_flood"
    provides = ("flood_band", "flood_high_share")
    key = "postcode"

    # Published category labels, lowest risk first.
    _CATEGORIES = ("very low", "low", "medium", "high")

    @classmethod
    def _match_category_columns(cls, columns) -> dict:
        """Map band index -> column name.

        Substring matching alone is wrong here: "low" is contained in "verylow",
        so a naive scan hands the Very Low column to band 1 and silently shifts
        every flood band down one. Match exactly first, then fall back to
        substrings longest-category-first, never reusing a claimed column.
        """
        norm = {c: re.sub(r"[^a-z]", "", str(c).lower()) for c in columns}
        cat_cols: dict = {}
        claimed: set = set()

        for i, cat in enumerate(cls._CATEGORIES):
            key = cat.replace(" ", "")
            exact = [c for c in columns if norm[c] == key]
            if exact:
                cat_cols[i] = exact[0]
                claimed.add(exact[0])

        order = sorted(
            (i for i in range(len(cls._CATEGORIES)) if i not in cat_cols),
            key=lambda i: -len(cls._CATEGORIES[i]),
        )
        for i in order:
            key = cls._CATEGORIES[i].replace(" ", "")
            hits = [c for c in columns if c not in claimed and key in norm[c]]
            if hits:
                cat_cols[i] = hits[0]
                claimed.add(hits[0])
        return cat_cols

    def load(self) -> pd.DataFrame:
        df = pd.read_csv(self.path, dtype=str, low_memory=False)
        pc_col = _pick_column(df, ["postcode", "post_code", "pcd"], "postcode")

        cat_cols = self._match_category_columns(df.columns)
        if not cat_cols:
            raise KeyError(
                "no flood likelihood category columns found. Expected columns "
                f"naming {self._CATEGORIES}; file has {list(df.columns)[:25]}"
            )

        counts = pd.DataFrame(
            {i: pd.to_numeric(df[c], errors="coerce").fillna(0.0)
             for i, c in cat_cols.items()}
        )
        total = counts.sum(axis=1)

        # Highest band that has any properties at all.
        occupied = counts.gt(0)
        band = pd.Series(np.nan, index=df.index, dtype=float)
        for i in sorted(cat_cols):
            band = band.mask(occupied[i], float(i))

        high_cols = [i for i in cat_cols if i >= 2]
        high_share = (
            counts[high_cols].sum(axis=1).div(total.replace(0, np.nan))
            if high_cols else pd.Series(np.nan, index=df.index)
        )

        out = pd.DataFrame(
            {
                "postcode": [normalise_postcode(v) for v in df[pc_col]],
                "flood_band": band,
                "flood_high_share": high_share.fillna(0.0),
            }
        )
        out = out.dropna(subset=["postcode"])
        # Postcodes absent from the file have no receptors -> treat as band 0,
        # but only for postcodes the file's coverage area includes. That
        # judgement belongs to the caller, so we do not fill here.
        return out.groupby("postcode", as_index=False).agg(
            flood_band=("flood_band", "max"),
            flood_high_share=("flood_high_share", "max"),
        )


class LandRegistryValue(GeoSource):
    """Median sale price per postcode sector, from Price Paid Data.

    Sector rather than outcode because outcodes are far too coarse in cities —
    a single outcode can span a 4x price range, and property value is a strong
    driver of buildings sum insured and therefore premium.

    Median rather than mean: PPD includes occasional very large commercial-ish
    transactions that drag a mean badly.

    Accepts either the raw PPD file (no header, documented column order) or a
    Standard Reports export (has a header).
    """

    name = "lr_value"
    provides = ("area_avg_value",)
    key = "sector"

    # Raw PPD column order, per the HM Land Registry FAQ.
    _RAW_COLUMNS = [
        "transaction_id", "price", "date_of_transfer", "postcode", "property_type",
        "old_new", "duration", "paon", "saon", "street", "locality", "town_city",
        "district", "county", "ppd_category_type", "record_status",
    ]

    def load(self) -> pd.DataFrame:
        head = pd.read_csv(self.path, nrows=5, header=None, dtype=str)
        looks_raw = head.shape[1] >= 15 and not str(head.iloc[0, 1]).isalpha()

        if looks_raw:
            df = pd.read_csv(
                self.path, header=None, names=self._RAW_COLUMNS, dtype=str,
                usecols=[1, 2, 3], low_memory=False,
            )
            price_col, pc_col, date_col = "price", "postcode", "date_of_transfer"
        else:
            df = pd.read_csv(self.path, dtype=str, low_memory=False)
            price_col = _pick_column(df, ["price", "price_paid", "amount"], "price")
            pc_col = _pick_column(df, ["postcode", "post_code"], "postcode")
            date_col = next(
                (c for c in df.columns if "date" in c.lower()), None
            )

        df["_price"] = pd.to_numeric(df[price_col], errors="coerce")
        df = df[df["_price"].between(10_000, 20_000_000)]  # drop obvious junk

        since = self.options.get("since_year")
        if since and date_col:
            years = pd.to_datetime(df[date_col], errors="coerce").dt.year
            df = df[years >= int(since)]

        df["sector"] = [
            parse_postcode(v).sector for v in df[pc_col]
        ]
        df = df.dropna(subset=["sector"])

        min_sales = int(self.options.get("min_sales", 5))
        g = df.groupby("sector")["_price"]
        out = g.median().to_frame("area_avg_value")
        out["_n"] = g.size()
        # A sector median from two sales is noise dressed as a feature.
        out = out[out["_n"] >= min_sales].drop(columns="_n")
        return out.reset_index()


class ImdDeprivation(GeoSource):
    """Index of Multiple Deprivation decile.

    Accepts the postcode-level export from imd-by-postcode.opendatacommunities.org
    (keyed by postcode) or an LSOA-level file (set ``key='lsoa'``, needs ONSPD).
    """

    name = "imd"
    provides = ("imd_decile",)
    key = "postcode"

    def load(self) -> pd.DataFrame:
        df = pd.read_csv(self.path, dtype=str, low_memory=False)
        if self.key == "lsoa":
            key_col = _pick_column(
                df, ["lsoa code (2011)", "lsoa11cd", "lsoa_code", "lsoa"], "LSOA"
            )
            keys = df[key_col].str.strip()
        else:
            key_col = _pick_column(df, ["postcode", "post_code", "pcd"], "postcode")
            keys = [normalise_postcode(v) for v in df[key_col]]

        dec_col = _pick_column(
            df,
            ["index of multiple deprivation decile",
             "imd decile", "imd_decile", "index of multiple deprivation (imd) decile"],
            "IMD decile",
        )
        out = pd.DataFrame(
            {self.key: keys, "imd_decile": pd.to_numeric(df[dec_col], errors="coerce")}
        ).dropna(subset=[self.key])
        return out.groupby(self.key, as_index=False)["imd_decile"].median()


class PoliceCrime(GeoSource):
    """Crime count per LSOA from police.uk street-level data.

    Needs ONSPD to bridge postcode -> LSOA. Give it a directory of the monthly
    ``*-street.csv`` files and it will concatenate them.

    Emits a normalised 0-1 index rather than a raw count, because raw counts are
    dominated by LSOA population and by how many months you happened to
    download.
    """

    name = "police_crime"
    provides = ("crime_index",)
    key = "lsoa"

    def load(self) -> pd.DataFrame:
        path = self.path
        files = (
            sorted(path.rglob("*street.csv")) if path.is_dir() else [path]
        )
        if not files:
            raise FileNotFoundError(f"no *street.csv files under {path}")

        frames = []
        for f in files:
            d = pd.read_csv(f, dtype=str, low_memory=False)
            try:
                col = _pick_column(d, ["lsoa code", "lsoa_code", "lsoa11cd"], "LSOA")
            except KeyError:
                continue
            frames.append(d[[col]].rename(columns={col: "lsoa"}))
        if not frames:
            raise KeyError("no LSOA column found in any street.csv file")

        allc = pd.concat(frames, ignore_index=True).dropna()
        counts = allc.groupby("lsoa").size().to_frame("_n")
        n_months = max(len(files), 1)
        counts["_per_month"] = counts["_n"] / n_months

        # Rank-normalise to 0-1. Robust to the number of months downloaded and
        # to the long right tail of city-centre LSOAs.
        counts["crime_index"] = counts["_per_month"].rank(pct=True)
        return counts.reset_index()[["lsoa", "crime_index"]]


class OnspdLookup(GeoSource):
    """Postcode -> LSOA bridge, from the ONS Postcode Directory.

    Only needed for LSOA-keyed sources. The full ONSPD is large; passing
    ``usecols`` keeps memory sane.
    """

    name = "onspd"
    provides = ("lsoa",)
    key = "postcode"

    def load(self) -> pd.DataFrame:
        df = pd.read_csv(self.path, dtype=str, low_memory=False)
        pc_col = _pick_column(df, ["pcds", "pcd", "postcode"], "postcode")
        lsoa_col = _pick_column(
            df, ["lsoa11", "lsoa21", "lsoa11cd", "lsoa"], "LSOA"
        )
        out = pd.DataFrame(
            {
                "postcode": [normalise_postcode(v) for v in df[pc_col]],
                "lsoa": df[lsoa_col].str.strip(),
            }
        ).dropna(subset=["postcode"])
        return out.drop_duplicates("postcode")


class BgsSubsidence(GeoSource):
    """Subsidence susceptibility from BGS GeoSure.

    **Licensed data — not free.** No loader is shipped because the file format
    depends on your licence terms. Supply a CSV of ``postcode,subsidence_band``
    (0-3) and this will join it; that is the shape the models expect.
    """

    name = "bgs_subsidence"
    provides = ("subsidence_band",)
    key = "postcode"

    def load(self) -> pd.DataFrame:
        df = pd.read_csv(self.path, dtype=str, low_memory=False)
        pc_col = _pick_column(df, ["postcode", "post_code"], "postcode")
        band_col = _pick_column(
            df, ["subsidence_band", "band", "susceptibility"], "subsidence band"
        )
        out = pd.DataFrame(
            {
                "postcode": [normalise_postcode(v) for v in df[pc_col]],
                "subsidence_band": pd.to_numeric(df[band_col], errors="coerce"),
            }
        ).dropna(subset=["postcode"])
        return out.groupby("postcode", as_index=False)["subsidence_band"].max()


# ---------------------------------------------------------------------------
# enrichment
# ---------------------------------------------------------------------------


class GeoEnricher:
    """Join every configured source onto a risk table.

    Sources are applied in order. Missing sources are skipped with a note rather
    than silently producing absent columns, and every provided column keeps a
    ``<col>_resolved`` companion so you can see exactly what was matched.
    """

    def __init__(self, sources=None):
        self.sources = list(sources or [])
        self.notes: list = []

    def add(self, source: GeoSource) -> "GeoEnricher":
        self.sources.append(source)
        return self

    def enrich(self, risks: pd.DataFrame, postcode_col: str = "postcode") -> pd.DataFrame:
        out = add_postcode_parts(risks, postcode_col=postcode_col)
        self.notes = []

        n_invalid = int((~out["postcode_valid"]).sum())
        if n_invalid:
            self.notes.append(
                f"{n_invalid} of {len(out)} postcodes failed validation and will "
                "not join to any source"
            )

        # ONSPD is a bridge, not a feature: attach LSOA first so that LSOA-keyed
        # sources have a key to join on. Order in `self.sources` must not matter.
        needs_lsoa = any(s.key == "lsoa" for s in self.sources)
        if needs_lsoa and "lsoa" not in out.columns:
            bridge = next((s for s in self.sources if isinstance(s, OnspdLookup)), None)
            if bridge is not None and bridge.available():
                before = len(out)
                out = out.merge(bridge.table(), on="postcode", how="left")
                assert len(out) == before, "ONSPD join changed row count"
                rate = float(out["lsoa"].notna().mean() * 100)
                self.notes.append(f"onspd: LSOA resolved for {rate:.1f}%")
            else:
                where = bridge.path if bridge is not None else "<not configured>"
                self.notes.append(
                    f"onspd: no bridge at {where} -- LSOA-keyed sources "
                    "(crime) cannot join"
                )

        for src in self.sources:
            if isinstance(src, OnspdLookup):
                continue  # already applied as a bridge above
            if not src.available():
                self.notes.append(f"{src.name}: no file at {src.path} -- skipped")
                continue
            try:
                table = src.table()
            except Exception as exc:
                self.notes.append(f"{src.name}: failed to load -- {exc}")
                continue

            if src.key not in out.columns:
                self.notes.append(
                    f"{src.name}: needs key {src.key!r} which is not on the risk "
                    "table -- skipped"
                )
                continue

            before = len(out)
            out = out.merge(table, on=src.key, how="left")
            assert len(out) == before, f"{src.name} join changed row count"

            for col in src.provides:
                if col in out.columns:
                    out[f"{col}_resolved"] = out[col].notna()
                    rate = float(out[f"{col}_resolved"].mean() * 100)
                    self.notes.append(f"{src.name}: {col} resolved for {rate:.1f}%")

        return out

    def coverage(self, enriched: pd.DataFrame) -> pd.DataFrame:
        """Resolution rate per geo column. Check this before training.

        A feature resolved for 60% of rows is not a feature — it is a
        missingness indicator wearing a feature's name, and tree models will
        happily split on it.
        """
        rows = []
        for src in self.sources:
            for col in src.provides:
                flag = f"{col}_resolved"
                if flag in enriched.columns:
                    rows.append(
                        {
                            "source": src.name,
                            "column": col,
                            "resolved_pct": round(
                                float(enriched[flag].mean() * 100), 1
                            ),
                            "missing": int((~enriched[flag]).sum()),
                        }
                    )
        return pd.DataFrame(rows)


REQUIRED_GEO_COLUMNS = ("flood_band", "crime_index", "subsidence_band", "area_avg_value")


def check_ready_for_modelling(enriched: pd.DataFrame, min_resolved: float = 95.0):
    """Raise unless every model-required geo column is sufficiently resolved.

    Call this between enrichment and training. The failure mode it prevents is
    the quiet one: a model trained where a third of flood bands are NaN will fit
    and score, and the number it reports will be wrong in a way nothing in the
    metrics reveals.
    """
    problems = []
    for col in REQUIRED_GEO_COLUMNS:
        if col not in enriched.columns:
            problems.append(f"{col}: column absent")
            continue
        pct = float(enriched[col].notna().mean() * 100)
        if pct < min_resolved:
            problems.append(f"{col}: only {pct:.1f}% resolved")
    if problems:
        raise ValueError(
            "geo features not ready for modelling:\n  " + "\n  ".join(problems)
        )
    return True


# ---------------------------------------------------------------------------
# standard layout
# ---------------------------------------------------------------------------

# filename -> (what it is, where to get it, licence note)
SOURCE_MANIFEST = {
    "ea_flood.csv": (
        "EA flood risk, postcode search tool data",
        "https://environment.data.gov.uk/dataset/"
        "53cba123-71f8-417a-8441-4c7ba111e8e1",
        "Open Government Licence",
    ),
    "price_paid.csv": (
        "HM Land Registry Price Paid Data",
        "https://landregistry.data.gov.uk/app/ppd/ppd_data",
        "OGL -- attribution required, contains HM Land Registry data (c) Crown "
        "copyright",
    ),
    "imd.csv": (
        "Index of Multiple Deprivation 2019, by postcode",
        "https://imd-by-postcode.opendatacommunities.org/",
        "Open Government Licence",
    ),
    "police/": (
        "police.uk street-level crime, monthly *-street.csv files",
        "https://data.police.uk/data/",
        "Open Government Licence",
    ),
    "onspd.csv": (
        "ONS Postcode Directory (postcode -> LSOA bridge)",
        "https://geoportal.statistics.gov.uk/",
        "OGL -- contains OS data (c) Crown copyright and database right",
    ),
    "subsidence.csv": (
        "BGS GeoSure subsidence, as postcode,subsidence_band",
        "https://www.bgs.ac.uk/datasets/geosure/",
        "LICENSED -- not free, supply your own extract",
    ),
}


def default_sources(data_dir="data/geo") -> list:
    """The standard file layout, wired up.

    Everything is optional: a source with no file is skipped with a note rather
    than failing, so you can start with flood alone and add the rest as you
    obtain them. Land Registry is limited to recent years by default, because a
    sector median computed over sales back to 1995 is a history lesson, not a
    current property value.
    """
    d = Path(data_dir)
    return [
        OnspdLookup(d / "onspd.csv"),
        EnvironmentAgencyFlood(d / "ea_flood.csv"),
        LandRegistryValue(d / "price_paid.csv", since_year=2023, min_sales=5),
        ImdDeprivation(d / "imd.csv"),
        PoliceCrime(d / "police"),
        BgsSubsidence(d / "subsidence.csv"),
    ]


def missing_files(data_dir="data/geo") -> pd.DataFrame:
    """What still needs downloading, with the URL for each.

    Call this before a collection run rather than discovering the gap in a
    coverage report after training.
    """
    d = Path(data_dir)
    rows = []
    for name, (what, url, licence) in SOURCE_MANIFEST.items():
        target = d / name.rstrip("/")
        present = target.exists() and (
            any(target.rglob("*street.csv")) if name.endswith("/") else True
        )
        if not present:
            rows.append(
                {"file": name, "what": what, "url": url, "licence": licence}
            )
    return pd.DataFrame(rows)
