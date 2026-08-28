"""Manual collection sessions -- quotes you obtain yourself, as a real customer.

This is the POC collection path. You run the quote journeys by hand and record
what came back; the module gives you a session template, validates what you
enter, and lands it in the same canonical schema a vendor extract would use, so
nothing downstream cares which source it came from.

Identity policy, and why it is not just box-ticking
---------------------------------------------------
Vary the *contact* details freely. Keep the *rating* details real.

  Vary   email (use a per-channel alias), phone if you like. These never touch
         the rating engine -- they exist so four PCWs and a dozen insurers do not
         all land in one inbox, and so you can tell who sold your address on.

  Real   name, date of birth, address, claims history, property attributes.
         UK household pricing commonly involves identity and credit checks at
         point of quote. An identity that does not resolve gets default or
         penalty pricing, so a fabricated one does not return that insurer's real
         price for that risk -- it returns their price for an unresolvable
         applicant. That is the specific failure mode Defaqto cite for not using
         fake profiles, and it would invalidate the accuracy measurement this
         repo exists to produce.

The practical consequence, stated plainly: one real person quoting one real
property yields ONE risk profile. That is enough to validate the pipeline and to
benchmark cross-provider spread and top-5 accuracy for that risk. It is not
enough to train per-provider models across risk space -- that needs licensed
vendor data or consented panellists. See docs/DESIGN.md.
"""

from __future__ import annotations

import csv
import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path

# Columns the collector fills in during a session. Deliberately short: anything
# derivable is derived later, so hand-entry stays fast and error-free.
SESSION_COLUMNS = [
    "risk_id",
    "brand",
    "channel",
    "collected_on",
    "quoted",          # y / n  -- n means asked and declined/referred
    "premium",         # blank if quoted = n
    "compulsory_excess",
    "accidental_damage",
    "rank_on_page",    # PCW only; position in the results list
    "cashback",        # incentive OUTSIDE the premium -- never fold it in
    "incentive_note",
    "collector_note",
]


@dataclass
class ChannelAlias:
    """One alias address per place you quote, so inboxes stay separable.

    `label` is what you would recognise in a mailbox; `address` is the alias.
    Plus-addressing (you+ctm@gmail.com) works and is free, but some forms reject
    the '+'. A masking service or a dedicated free account avoids that.
    """

    channel: str
    address: str
    label: str = ""


@dataclass
class CollectionSession:
    """A single sitting of manual quote collection."""

    session_id: str
    collected_on: _dt.date
    identity_ref: str  # pointer to the real identity used; NOT the identity itself
    risk_ids: list = field(default_factory=list)
    channels: list = field(default_factory=list)
    brands: list = field(default_factory=list)
    aliases: list = field(default_factory=list)
    note: str = ""

    def alias_for(self, channel: str) -> str | None:
        for a in self.aliases:
            if a.channel == channel:
                return a.address
        return None

    def expected_rows(self) -> int:
        return len(self.risk_ids) * len(self.channels) * len(self.brands)

    def write_template(self, path) -> Path:
        """Emit a pre-filled CSV: one row per (risk, channel, brand) to fill in.

        Pre-filling the grid matters -- it means a provider you could not get a
        quote from leaves a visible empty row rather than vanishing. Absent rows
        and declines are different things, and only one of them is signal.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=SESSION_COLUMNS)
            w.writeheader()
            for risk_id in self.risk_ids:
                for channel in self.channels:
                    for brand in self.brands:
                        w.writerow(
                            {
                                "risk_id": risk_id,
                                "brand": brand,
                                "channel": channel,
                                "collected_on": self.collected_on.isoformat(),
                                "quoted": "",
                                "premium": "",
                                "compulsory_excess": "",
                                "accidental_damage": "",
                                "rank_on_page": "",
                                "cashback": "",
                                "incentive_note": "",
                                "collector_note": "",
                            }
                        )
        return path


def _parse_bool(value, field_name: str, row_no: int):
    v = (value or "").strip().lower()
    if v in ("y", "yes", "true", "1"):
        return True
    if v in ("n", "no", "false", "0"):
        return False
    if v == "":
        return None
    raise ValueError(f"row {row_no}: {field_name}={value!r} is not y/n")


def _parse_float(value, field_name: str, row_no: int):
    v = (value or "").strip().replace(",", "").lstrip("£")
    if v == "":
        return None
    try:
        return float(v)
    except ValueError as exc:
        raise ValueError(f"row {row_no}: {field_name}={value!r} is not a number") from exc


def read_session(path):
    """Read a filled-in session CSV into canonical quote dicts.

    Rows left entirely blank are skipped as not-yet-collected. Rows with
    quoted=n and no premium are kept -- those are declines, and they train the
    quotability model.
    """
    path = Path(path)
    out, problems = [], []

    with path.open(newline="", encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh), start=2):
            if not (row.get("quoted") or "").strip():
                continue  # not collected yet
            try:
                quoted = _parse_bool(row["quoted"], "quoted", i)
                premium = _parse_float(row.get("premium"), "premium", i)
                if quoted and premium is None:
                    raise ValueError(f"row {i}: quoted=y but no premium")
                if not quoted and premium is not None:
                    raise ValueError(f"row {i}: quoted=n must not carry a premium")

                rank = row.get("rank_on_page", "").strip()
                out.append(
                    dict(
                        risk_id=row["risk_id"].strip(),
                        brand=row["brand"].strip(),
                        channel=row["channel"].strip(),
                        collected_on=_dt.date.fromisoformat(row["collected_on"].strip()),
                        quoted=quoted,
                        premium=premium,
                        compulsory_excess=_parse_float(
                            row.get("compulsory_excess"), "compulsory_excess", i
                        ),
                        accidental_damage=_parse_bool(
                            row.get("accidental_damage"), "accidental_damage", i
                        ),
                        rank_on_page=int(rank) if rank else None,
                        cashback=_parse_float(row.get("cashback"), "cashback", i),
                        incentive_note=(row.get("incentive_note") or "").strip() or None,
                        collector_note=(row.get("collector_note") or "").strip() or None,
                        source="manual",
                    )
                )
            except (ValueError, KeyError) as exc:
                problems.append(str(exc))

    return out, problems


def coverage_report(rows, expected_brands, expected_channels):
    """What did we actually get? Run this before trusting a session.

    Reports per brand: quoted, declined, and missing. A brand that is *missing*
    rather than *declined* is a collection gap, not market signal, and treating
    the two alike is the fastest way to bias a top-5 list.
    """
    seen = {}
    for r in rows:
        key = r["brand"]
        rec = seen.setdefault(key, {"quoted": 0, "declined": 0, "channels": set()})
        rec["channels"].add(r["channel"])
        if r["quoted"]:
            rec["quoted"] += 1
        else:
            rec["declined"] += 1

    report = []
    for brand in expected_brands:
        rec = seen.get(brand)
        if rec is None:
            report.append(
                {"brand": brand, "quoted": 0, "declined": 0,
                 "missing_channels": list(expected_channels), "status": "MISSING"}
            )
            continue
        missing = [c for c in expected_channels if c not in rec["channels"]]
        report.append(
            {
                "brand": brand,
                "quoted": rec["quoted"],
                "declined": rec["declined"],
                "missing_channels": missing,
                "status": "partial" if missing else "complete",
            }
        )
    return report
