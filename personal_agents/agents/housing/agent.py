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
{notes_section}
You keep track of housing listings for the user with your tools:
- add_listing — when the user mentions a place, record it. Capture whatever details they give (address, price, link) plus anything that bears on the criteria (is it a self-contained basement? distance to McMaster? which neighbourhood?).
- update_listing — when something changes, update the listing's status. Statuses, roughly in order: new -> contacted -> viewed -> applying, or rejected at any point.
- list_listings / get_listing — to review the current list and reason about it.
- remember_preference — when the user states a new standing preference or constraint (a budget cap, "must allow pets", "no carpet", ...), save it so you apply it from then on.

How to work:
- When the user rejects a listing, always record why. If they didn't give a reason, ask for it before marking it rejected. Never suggest or recommend a rejected listing again.
- When the user asks what's still in play, or to compare options, weigh every listing against all of the criteria — self-contained basement, walkability/commute to McMaster, neighbourhood, and price — not price alone. Leave rejected listings out.
- Prefer your tools over memory of the chat; if something hasn't been recorded, say so. Always include a listing's id when you refer to it, so the user can act on it.
- Be concise and concrete, and honest about gaps — if a listing is missing the information needed to judge a criterion, point that out."""


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
        if not include_rejected:  # rejected listings are out of play by default
            return [l for l in listings if l.get("status") != "rejected"]
        return listings


class HousingAgent(BaseAgent):
    name = "housing"
    description = "Tracks the basement-apartment search in Westdale / near McMaster."

    def setup(self) -> None:
        self.profile = JsonStore(self.data_dir / "profile.json")
        self.listings = HousingStore(self.data_dir / "listings.json")
        if self.profile.load(None) is None:  # seed standing criteria on first run
            self.profile.save({"criteria": DEFAULT_CRITERIA, "notes": []})

    # ---- prompt / standing memory ------------------------------------------
    def _profile(self) -> dict:
        return self.profile.load({"criteria": DEFAULT_CRITERIA, "notes": []})

    def system_prompt(self) -> str:
        p = self._profile()
        notes = p.get("notes") or []
        notes_section = ""
        if notes:
            joined = "\n".join(f"- {n}" for n in notes)
            notes_section = (
                f"\nAdditional standing preferences the user has told you:\n{joined}\n"
            )
        return SYSTEM_TEMPLATE.format(
            criteria=p.get("criteria", DEFAULT_CRITERIA),
            notes_section=notes_section,
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
                        "rejection_reason": {"type": "string", "description": "Why it was rejected. Required when status is 'rejected' so it is never suggested again."},
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
                description="Save a new standing preference or constraint to apply to the whole search from now on.",
                input_schema={
                    "type": "object",
                    "properties": {"note": {"type": "string", "description": "The preference to remember."}},
                    "required": ["note"],
                },
                handler=self._remember_preference,
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
