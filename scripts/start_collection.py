"""Open a manual collection session: write the grid you fill in by hand.

    python scripts/start_collection.py --risk MY-HOUSE --identity me
    python scripts/start_collection.py --risk MY-HOUSE --identity me --tier 1 2

Reads `config/providers.yml`, selects the brands reachable on each requested
channel, and writes a pre-filled (risk x channel x brand) CSV to `data/raw/`.

The grid is pre-filled on purpose. A provider you could not get a quote from
leaves a **visible empty row** instead of vanishing, which is the difference
between "declined" (market signal) and "missing" (collection gap). Treating
those alike is the fastest way to bias every number downstream.

WHAT MUST BE TRUE OF THE QUOTES YOU COLLECT

Per-channel email aliases are fine and sensible -- that is what `--identity`
plus the alias column is for, and it keeps each site's marketing separate.

Everything the insurer actually rates on must be genuine: name, date of birth,
address, claims and conviction history, and every property attribute. This is
not only about the terms you agreed to when you used the site. A fabricated
applicant returns a real price for a person who does not exist, so the number
you record is not a market price for your risk and the accuracy measurement
built on it means nothing. The dishonest version is also the useless version.

Store the identity itself outside this repository. `identity_ref` is a pointer,
never the identity.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mktpricing.collect.session import (  # noqa: E402
    ChannelAlias, CollectionSession, write_risk_template,
)


def load_brands(config: Path, channel_kinds, tiers):
    """Brands reachable on any requested channel kind, within the given tiers."""
    spec = yaml.safe_load(config.read_text(encoding="utf-8"))
    out, unreachable = [], []
    for b in spec.get("brands", []):
        if tiers and b.get("tier") not in tiers:
            continue
        if set(b.get("channels", [])) & set(channel_kinds):
            out.append(b)
        else:
            unreachable.append(b)
    return out, unreachable


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--risk", action="append", required=True,
                    help="risk id, e.g. MY-HOUSE. Repeat for more than one.")
    ap.add_argument("--identity", required=True,
                    help="pointer to the identity used, NOT the identity itself")
    ap.add_argument("--channels", nargs="*",
                    default=["pcw_ctm", "pcw_msm", "pcw_gocompare", "direct"],
                    help="collection channels for this sitting")
    ap.add_argument("--tier", nargs="*", type=int, default=[1],
                    help="provider tiers to include (1=weekly, 2=monthly, 3=ad hoc)")
    ap.add_argument("--alias-domain", default=None,
                    help="if your mail provider supports plus-addressing, e.g. "
                         "you@example.com -- one alias per channel is generated")
    ap.add_argument("--week", default=None,
                    help="session id; defaults to the ISO week, e.g. 2026-W35")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "providers.yml")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "raw")
    args = ap.parse_args()

    today = _dt.date.today()
    iso = today.isocalendar()
    session_id = args.week or f"{iso.year}-W{iso.week:02d}"

    kinds = {"direct" if c == "direct" else "pcw" for c in args.channels}
    brands, unreachable = load_brands(args.config, kinds, set(args.tier))
    if not brands:
        print(f"no brands in tier(s) {args.tier} reachable on {sorted(kinds)}")
        return 2

    aliases = []
    if args.alias_domain and "@" in args.alias_domain:
        local, domain = args.alias_domain.split("@", 1)
        aliases = [
            ChannelAlias(c, f"{local}+{c}@{domain}", c) for c in args.channels
        ]

    session = CollectionSession(
        session_id=session_id,
        collected_on=today,
        identity_ref=args.identity,
        risk_ids=list(args.risk),
        channels=list(args.channels),
        brands=[b["name"] for b in brands],
        aliases=aliases,
        note=f"tier(s) {sorted(args.tier)}",
    )

    path = session.write_template(args.out / f"{session_id}.csv")

    # The grid records what each brand said. What was *asked* -- the property,
    # cover and excess actually entered -- lives in the risk file, one entry
    # per risk_id. Without it the quotes are premiums with no risk attached.
    risk_file = args.out / "risks.yml"
    risk_file_written = False
    if not risk_file.exists():
        write_risk_template(risk_file, args.risk)
        risk_file_written = True

    print(f"session {session_id}   {today.isoformat()}")
    print(f"  identity_ref  {args.identity}  (the identity itself stays out of this repo)")
    print(f"  risks         {', '.join(args.risk)}")
    print(f"  channels      {', '.join(args.channels)}")
    print(f"  brands        {len(brands)} in tier(s) {sorted(args.tier)}")
    print(f"  rows to fill  {session.expected_rows()}")
    print(f"\n  template -> {path}")

    if aliases:
        print("\n  per-channel aliases:")
        for a in aliases:
            print(f"    {a.channel:16} {a.address}")
    else:
        print("\n  no --alias-domain given, so the alias column is blank. Fill it in")
        print("  by hand if you want each channel's marketing kept separate.")

    if unreachable:
        print("\n  NOT in this sitting -- unreachable on the requested channels:")
        for b in unreachable:
            ch = ", ".join(b.get("channels", [])) or "none recorded"
            print(f"    {b['name']:16} reachable via: {ch}")
        print("  This is the coverage gap. A PCW-only dataset cannot close it,")
        print("  and pretending the panel is the market biases the index.")

    if risk_file_written:
        print(f"\n  risk definitions -> {risk_file}  (new; describe the property there)")
    else:
        print(f"\n  risk definitions: {risk_file}  (exists; add any new risk_id to it)")

    print("\n  Fill in `quoted` and `premium` for every row. Leave a row blank")
    print("  only if you could not complete the journey -- a refusal to quote is")
    print("  quoted=false, which is signal, not a gap. Then ingest the grid:")
    print(f"\n    python scripts/ingest_session.py {path} --risks {risk_file} --geo data/geo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
