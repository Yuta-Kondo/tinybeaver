"""Generate recommendations.md from the housing agent's listings.json.

Usage:
    python scripts/report.py                    # uses default ~/.personal_agents
    python scripts/report.py --data-dir ./data  # custom data dir
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path


def _load(data_dir: Path) -> tuple[dict, list[dict]]:
    profile_path = data_dir / "housing" / "profile.json"
    listings_path = data_dir / "housing" / "listings.json"

    profile: dict = {}
    if profile_path.exists():
        with open(profile_path) as f:
            profile = json.load(f)

    listings: list[dict] = []
    if listings_path.exists():
        with open(listings_path) as f:
            listings = json.load(f).get("listings", [])

    return profile, listings


def _stars(listing: dict) -> str:
    score = 0
    if listing.get("self_contained"):
        score += 2
    if listing.get("basement"):
        score += 1
    nb = (listing.get("neighbourhood") or "").lower()
    if "westdale" in nb:
        score += 2
    dist = listing.get("distance_to_mcmaster") or ""
    if dist and any(c.isdigit() for c in dist):
        mins = int("".join(c for c in dist if c.isdigit())[:2])
        if mins <= 10:
            score += 2
        elif mins <= 20:
            score += 1
    if listing.get("price"):
        if listing["price"] <= 1400:
            score += 1
    return "★" * min(score, 5) + "☆" * (5 - min(score, 5))


def _fmt_listing(l: dict, idx: int) -> str:
    lines = [f"### #{l['id']} — {l.get('address', 'Unknown address')}"]
    lines.append("")

    stars = _stars(l)
    status = l.get("status", "new").upper()
    price = f"${l['price']:,.0f}/mo" if l.get("price") else "Price unknown"
    lines.append(f"**{stars}** &nbsp; `{status}` &nbsp; {price}")
    lines.append("")

    details = []
    if l.get("neighbourhood"):
        details.append(f"📍 {l['neighbourhood']}")
    if l.get("distance_to_mcmaster"):
        details.append(f"🚶 {l['distance_to_mcmaster']} to McMaster")
    if l.get("bedrooms"):
        details.append(f"🛏 {int(l['bedrooms'])} bed")
    if l.get("self_contained") is True:
        details.append("✅ Self-contained")
    elif l.get("self_contained") is False:
        details.append("❌ Not self-contained")
    else:
        details.append("❓ Self-contained: unknown")
    if l.get("basement") is True:
        details.append("✅ Basement")
    elif l.get("basement") is False:
        details.append("❌ Not basement")

    if details:
        lines.append(" &nbsp;·&nbsp; ".join(details))
        lines.append("")

    if l.get("url"):
        lines.append(f"🔗 [{l['url']}]({l['url']})")
        lines.append("")

    if l.get("notes"):
        lines.append(f"> {l['notes']}")
        lines.append("")

    return "\n".join(lines)


def generate(data_dir: Path, output: Path) -> None:
    profile, listings = _load(data_dir)

    active = [l for l in listings if l.get("status") != "rejected"]
    rejected = [l for l in listings if l.get("status") == "rejected"]

    # Sort active: self-contained + basement first, then by price
    def sort_key(l):
        sc = 0 if l.get("self_contained") else 1
        price = l.get("price") or 9999
        return (sc, price)

    active.sort(key=sort_key)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Housing Recommendations",
        f"",
        f"_Generated {now} · {len(active)} active, {len(rejected)} rejected_",
        f"",
    ]

    feedback = profile.get("feedback") or []
    if feedback:
        lines += ["## Stored preferences", ""]
        for f in feedback:
            icon = {"like": "✅", "dislike": "⚠️", "dealbreaker": "🚫"}.get(f["sentiment"], "•")
            note = f" — {f['note']}" if f.get("note") else ""
            lines.append(f"- {icon} **{f['sentiment'].upper()}**: {f['topic']}{note}")
        lines += ["", "---", ""]

    if active:
        lines += ["## Active listings", ""]
        for i, l in enumerate(active):
            lines.append(_fmt_listing(l, i))
            lines.append("---")
            lines.append("")
    else:
        lines += ["## Active listings", "", "_None recorded yet._", ""]

    if rejected:
        lines += ["## Rejected", ""]
        for l in rejected:
            reason = l.get("rejection_reason") or "no reason given"
            lines.append(f"- ~~#{l['id']} {l.get('address', '')}~~ — {reason}")
        lines.append("")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Written → {output}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--output", default="recommendations.md")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).expanduser() if args.data_dir else Path.home() / ".personal_agents"
    generate(data_dir, Path(args.output))


if __name__ == "__main__":
    main()
