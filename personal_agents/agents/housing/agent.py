from __future__ import annotations

import json
from datetime import datetime

from ...core.agent import BaseAgent, Tool
from ...core.storage import JsonStore


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# Seeded into the agent's profile on first run, then editable as memory.
DEFAULT_CRITERIA = (
    "The user is moving to Hamilton, Ontario in September 2026 to begin a PhD at "
    "McMaster University, and is searching for a place to live.\n\n"
    "Hard requirements (a listing must meet these to be a real candidate):\n"
    "- A self-contained basement apartment: its own private entrance, its own "
    "kitchen, and its own bathroom (not a shared room or shared facilities).\n"
    "- Walkable to McMaster campus, or a short commute.\n\n"
    "Strong preferences:\n"
    "- In or near the Westdale neighbourhood (the area beside McMaster).\n"
    "- Good value — but fit to the requirements above matters more than price alone."
)

SYSTEM_TEMPLATE = """You are the user's personal housing-search assistant — one specialized agent in a larger personal-assistant system. You focus only on their housing search, and you remember everything relevant to it so the user never has to repeat themselves.

What you already know about this search:
<criteria>
{criteria}
</criteria>
{feedback_section}{notes_section}
**Current listings in the database:**
{listings_snapshot}

You keep track of housing listings with your tools:
- search_web — search the internet for listings. When the user asks you to find places, call this with queries like "basement apartment Westdale Hamilton Kijiji" or "self-contained basement rent near McMaster". Run multiple searches (different sites, different queries) to get broad coverage. After each search, call add_listing for every promising result.
- add_listing — record a new place. Capture address, price, url, self-contained/basement status, distance to McMaster, and neighbourhood.
- update_listing — update status (new → contacted → viewed → applying → rejected) or add notes.
- list_listings / get_listing — review or compare listings.
- remember_preference — save a new standing constraint or preference ("must allow pets", "no carpet", budget cap, etc.).
- record_feedback — save what the user likes or dislikes about specific features or locations. Use sentiment: "like", "dislike", or "dealbreaker". Call this any time the user expresses an opinion, even in passing.

How to work:
- At the start of every session, briefly orient the user: how many listings are tracked, which are still in play, and whether anything needs follow-up.
- When the user rejects a listing, always record why. If they didn't give a reason, ask for it. Never suggest rejected listings again.
- When the user expresses any opinion about a feature or area ("I hate shared laundry", "I like having a backyard", "busy roads are a dealbreaker"), immediately call record_feedback — don't just acknowledge it.
- When comparing options, weigh every listing against all criteria — self-contained basement, walkability to McMaster, neighbourhood, price, and all stored feedback. Leave rejected listings out.
- Be concise and concrete. Always include a listing's id. If information is missing to judge a criterion, say so."""


class HousingStore:
    """Persistence + rules for housing listings (independent of the LLM)."""

    STATUSES = ("new", "contacted", "viewed", "applying", "rejected")
    FIELDS = (
        "address", "price", "url", "bedrooms", "self_contained",
        "basement", "distance_to_mcmaster", "neighbourhood", "notes",
    )

    def __init__(self, path):
        self._store = JsonStore(path)

    def _load(self) -> dict:
        return self._store.load({"listings": []})

    def _next_id(self, listings) -> str:
        ids = [int(l["id"]) for l in listings if str(l.get("id", "")).isdigit()]
        return str((max(ids) + 1) if ids else 1)

    def add(self, data: dict) -> dict:
        d = self._load()
        listing = {f: data[f] for f in self.FIELDS if data.get(f) is not None}
        if not listing.get("address"):
            raise ValueError("a listing needs at least an address")
        now = _now()
        listing.update({
            "id": self._next_id(d["listings"]),
            "status": "new",
            "rejection_reason": None,
            "created_at": now,
            "updated_at": now,
            "history": [{"at": now, "event": "added"}],
        })
        d["listings"].append(listing)
        self._store.save(d)
        return listing

    def get(self, listing_id) -> dict | None:
        for l in self._load()["listings"]:
            if str(l["id"]) == str(listing_id):
                return l
        return None

    def update(self, listing_id, changes: dict) -> dict:
        d = self._load()
        listing = next((l for l in d["listings"] if str(l["id"]) == str(listing_id)), None)
        if listing is None:
            raise ValueError(f"no listing with id {listing_id}")

        new_status = changes.get("status")
        if new_status is not None and new_status not in self.STATUSES:
            raise ValueError(
                f"invalid status {new_status!r}; valid: {', '.join(self.STATUSES)}"
            )

        # Enforce the rule at the data layer too, not just in the prompt:
        # a rejection must capture *why*, so the listing is never re-suggested.
        reason = changes.get("rejection_reason") or listing.get("rejection_reason")
        if new_status == "rejected" and not reason:
            raise ValueError(
                "cannot reject a listing without a rejection_reason — ask the user "
                "why they're rejecting it, then call update_listing again with the reason"
            )

        events: list[str] = []
        if changes.get("notes"):
            existing = listing.get("notes") or ""
            listing["notes"] = (
                (existing + "\n" + changes["notes"]).strip() if existing else changes["notes"]
            )
            events.append("note added")
        for f in ("address", "price", "url", "bedrooms", "self_contained",
                  "basement", "distance_to_mcmaster", "neighbourhood"):
            if changes.get(f) is not None:
                listing[f] = changes[f]
                events.append(f"{f} updated")
        if new_status is not None:
            listing["status"] = new_status
            events.append(f"status -> {new_status}")
        if reason is not None:
            listing["rejection_reason"] = reason

        now = _now()
        listing["updated_at"] = now
        listing.setdefault("history", []).append(
            {"at": now, "event": "; ".join(events) or "updated"}
        )
        self._store.save(d)
        return listing

    def list(self, include_rejected: bool = False, status: str | None = None) -> list[dict]:
        listings = self._load()["listings"]
        if status:
            return [l for l in listings if l.get("status") == status]
        if not include_rejected:
            return [l for l in listings if l.get("status") != "rejected"]
        return listings


class HousingAgent(BaseAgent):
    name = "housing"
    description = "Tracks the basement-apartment search in Westdale / near McMaster."

    def setup(self) -> None:
        self.profile = JsonStore(self.data_dir / "profile.json")
        self.listings = HousingStore(self.data_dir / "listings.json")
        if self.profile.load(None) is None:
            self.profile.save({"criteria": DEFAULT_CRITERIA, "notes": [], "feedback": []})

    # ---- prompt / standing memory ------------------------------------------
    def _profile(self) -> dict:
        return self.profile.load({"criteria": DEFAULT_CRITERIA, "notes": [], "feedback": []})

    def system_prompt(self) -> str:
        p = self._profile()

        # Standing preferences
        notes = p.get("notes") or []
        notes_section = ""
        if notes:
            joined = "\n".join(f"- {n}" for n in notes)
            notes_section = f"\nStanding preferences:\n{joined}\n"

        # Stored feedback (likes / dislikes / dealbreakers)
        feedback = p.get("feedback") or []
        feedback_section = ""
        if feedback:
            lines = []
            for f in feedback:
                label = f["sentiment"].upper()
                topic = f["topic"]
                note = f.get("note", "")
                lines.append(f"  [{label}] {topic}" + (f" — {note}" if note else ""))
            feedback_section = "\nStored feedback on features/locations:\n" + "\n".join(lines) + "\n"

        # Compact listings snapshot so the agent knows state without a tool call
        active = self.listings.list(include_rejected=False)
        all_listings = self.listings.list(include_rejected=True)
        rejected_count = sum(1 for l in all_listings if l.get("status") == "rejected")

        if active:
            lines = []
            for l in active:
                price = f"${l['price']}/mo" if l.get("price") else "price unknown"
                lines.append(f"  #{l['id']} {l['address']} — {l['status']}, {price}")
            listings_snapshot = "\n".join(lines)
            if rejected_count:
                listings_snapshot += f"\n  ({rejected_count} rejected — not shown)"
        elif rejected_count:
            listings_snapshot = f"None active. {rejected_count} rejected."
        else:
            listings_snapshot = "None recorded yet."

        return SYSTEM_TEMPLATE.format(
            criteria=p.get("criteria", DEFAULT_CRITERIA),
            feedback_section=feedback_section,
            notes_section=notes_section,
            listings_snapshot=listings_snapshot,
        )

    # ---- tools --------------------------------------------------------------
    def tools(self) -> list[Tool]:
        statuses = list(HousingStore.STATUSES)
        return [
            Tool(
                name="add_listing",
                description="Record a new housing listing the user told you about.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "address": {"type": "string", "description": "Street address or location."},
                        "price": {"type": "number", "description": "Monthly rent in CAD, if known."},
                        "url": {"type": "string", "description": "Link to the listing, if any."},
                        "bedrooms": {"type": "number", "description": "Number of bedrooms, if known."},
                        "self_contained": {"type": "boolean", "description": "True if it has its own private entrance, kitchen, and bathroom."},
                        "basement": {"type": "boolean", "description": "True if it is a basement apartment."},
                        "distance_to_mcmaster": {"type": "string", "description": "Commute or walk to McMaster, e.g. '10 min walk'."},
                        "neighbourhood": {"type": "string", "description": "Neighbourhood, e.g. 'Westdale'."},
                        "notes": {"type": "string", "description": "Any other relevant details."},
                    },
                    "required": ["address"],
                },
                handler=self._add_listing,
            ),
            Tool(
                name="update_listing",
                description=(
                    "Update a listing as things change (status, price, notes, etc.). "
                    "Provide rejection_reason whenever status is 'rejected'."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "The id of the listing to update."},
                        "status": {"type": "string", "enum": statuses, "description": "New status."},
                        "rejection_reason": {"type": "string", "description": "Why it was rejected. Required when status is 'rejected'."},
                        "price": {"type": "number"},
                        "url": {"type": "string"},
                        "bedrooms": {"type": "number"},
                        "self_contained": {"type": "boolean"},
                        "basement": {"type": "boolean"},
                        "distance_to_mcmaster": {"type": "string"},
                        "neighbourhood": {"type": "string"},
                        "notes": {"type": "string", "description": "A note to append to the listing."},
                    },
                    "required": ["id"],
                },
                handler=self._update_listing,
            ),
            Tool(
                name="list_listings",
                description=(
                    "List tracked listings to review or compare. Rejected listings are "
                    "excluded unless include_rejected is true."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "include_rejected": {"type": "boolean", "description": "Include rejected listings (default false)."},
                        "status": {"type": "string", "enum": statuses, "description": "Only listings with this status."},
                    },
                },
                handler=self._list_listings,
            ),
            Tool(
                name="get_listing",
                description="Get the full details of a single listing by id.",
                input_schema={
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
                handler=self._get_listing,
            ),
            Tool(
                name="remember_preference",
                description="Save a new standing preference or hard constraint that applies to the whole search.",
                input_schema={
                    "type": "object",
                    "properties": {"note": {"type": "string", "description": "The preference to remember."}},
                    "required": ["note"],
                },
                handler=self._remember_preference,
            ),
            Tool(
                name="search_web",
                description=(
                    "Search the web for housing listings or neighbourhood info. "
                    "Try queries like 'basement apartment Westdale Hamilton Kijiji' or "
                    "'self-contained basement for rent near McMaster Hamilton'. "
                    "Call add_listing for every promising result you find."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search query."},
                        "max_results": {"type": "integer", "description": "Results to fetch (default 6, max 10)."},
                    },
                    "required": ["query"],
                },
                handler=self._search_web,
            ),
            Tool(
                name="record_feedback",
                description=(
                    "Record what the user likes, dislikes, or considers a dealbreaker about "
                    "specific housing features, amenities, or locations. Call this any time "
                    "the user expresses an opinion — even casually — so it persists across sessions."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "sentiment": {
                            "type": "string",
                            "enum": ["like", "dislike", "dealbreaker"],
                            "description": "How the user feels about this.",
                        },
                        "topic": {
                            "type": "string",
                            "description": "What the feedback is about, e.g. 'shared laundry', 'busy street', 'backyard'.",
                        },
                        "note": {
                            "type": "string",
                            "description": "Optional extra detail or context.",
                        },
                    },
                    "required": ["sentiment", "topic"],
                },
                handler=self._record_feedback,
            ),
        ]

    # ---- handlers -----------------------------------------------------------
    def _add_listing(self, inp: dict) -> str:
        listing = self.listings.add(inp)
        return f"Recorded listing #{listing['id']}:\n" + json.dumps(listing, indent=2, ensure_ascii=False)

    def _update_listing(self, inp: dict) -> str:
        listing_id = inp.get("id")
        if not listing_id:
            return "Error: 'id' is required."
        changes = {k: v for k, v in inp.items() if k != "id"}
        listing = self.listings.update(listing_id, changes)
        return f"Updated listing #{listing['id']}:\n" + json.dumps(listing, indent=2, ensure_ascii=False)

    def _list_listings(self, inp: dict) -> str:
        items = self.listings.list(
            include_rejected=bool(inp.get("include_rejected", False)),
            status=inp.get("status"),
        )
        if not items:
            return "No listings recorded yet (matching that filter)."
        return f"{len(items)} listing(s):\n" + json.dumps(items, indent=2, ensure_ascii=False)

    def _get_listing(self, inp: dict) -> str:
        listing = self.listings.get(inp.get("id"))
        if listing is None:
            return f"No listing with id {inp.get('id')!r}."
        return json.dumps(listing, indent=2, ensure_ascii=False)

    def _remember_preference(self, inp: dict) -> str:
        note = (inp.get("note") or "").strip()
        if not note:
            return "Error: nothing to remember."
        p = self._profile()
        p.setdefault("notes", []).append(note)
        self.profile.save(p)
        return f"Saved preference: {note}"

    def _search_web(self, inp: dict) -> str:
        from ddgs import DDGS
        query = (inp.get("query") or "").strip()
        if not query:
            return "Error: query is required."
        max_results = min(int(inp.get("max_results") or 6), 10)
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
        except Exception as e:
            return f"Search error: {e}"
        if not results:
            return "No results found."
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.get('title', '')}\n   {r.get('href', '')}\n   {r.get('body', '')}")
        return "\n\n".join(lines)

    def _record_feedback(self, inp: dict) -> str:
        sentiment = (inp.get("sentiment") or "dislike").strip()
        topic = (inp.get("topic") or "").strip()
        if not topic:
            return "Error: 'topic' is required."
        entry = {
            "sentiment": sentiment,
            "topic": topic,
            "note": (inp.get("note") or "").strip(),
            "recorded_at": _now(),
        }
        p = self._profile()
        p.setdefault("feedback", []).append(entry)
        self.profile.save(p)
        return f"Noted [{sentiment.upper()}]: {topic}"
