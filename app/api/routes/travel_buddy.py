from fastapi import APIRouter, Depends, HTTPException, Query
from app.core.database import db
from app.core.dependencies import get_current_user
from datetime import datetime
from bson import ObjectId
from typing import Optional

router = APIRouter()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def serialize_buddy(doc: dict) -> dict:
    """Convert MongoDB document to JSON-serialisable dict."""
    doc["id"] = str(doc.pop("_id"))
    doc["user_id"] = str(doc["user_id"])
    return doc


def get_buddy_or_404(buddy_id: str) -> dict:
    try:
        oid = ObjectId(buddy_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid travel buddy ID")

    buddy = db.travel_buddies.find_one({"_id": oid})
    if not buddy:
        raise HTTPException(status_code=404, detail="Travel buddy listing not found")
    return buddy


# ─── GET /travel-buddies/ ─────────────────────────────────────────────────────

@router.get("/")
def get_all_travel_buddies():
    """Return all travel buddy listings, most recent first."""
    buddies = list(db.travel_buddies.find().sort("created_at", -1))
    return [serialize_buddy(b) for b in buddies]


# ─── GET /travel-buddies/search ───────────────────────────────────────────────

@router.get("/search")
def search_travel_buddies(
    destination: str = Query(..., description="Destination city to search for"),
    start_date: str = Query(..., description="Your trip start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="Your trip end date (YYYY-MM-DD)"),
):
    """
    Find travel buddies going to the same destination with overlapping dates.

    Overlap condition:
      buddy.start_date <= your end_date  AND  buddy.end_date >= your start_date
    """
    # Basic date format validation
    try:
        datetime.strptime(start_date, "%Y-%m-%d")
        datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be in YYYY-MM-DD format")

    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be on or before end_date")

    query = {
        "destination": {"$regex": f"^{destination}$", "$options": "i"},
        "start_date": {"$lte": end_date},
        "end_date":   {"$gte": start_date},
    }

    buddies = list(db.travel_buddies.find(query).sort("created_at", -1))
    return {
        "count": len(buddies),
        "results": [serialize_buddy(b) for b in buddies],
    }


# ─── POST /travel-buddies/ ────────────────────────────────────────────────────

@router.post("/", status_code=201)
def create_travel_buddy(data: dict, user_id: str = Depends(get_current_user)):
    """Create a new travel buddy listing."""
    required = ["destination", "start_date", "end_date"]
    missing = [f for f in required if f not in data]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required fields: {', '.join(missing)}"
        )

    # Validate dates
    try:
        datetime.strptime(data["start_date"], "%Y-%m-%d")
        datetime.strptime(data["end_date"], "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be in YYYY-MM-DD format")

    if data["start_date"] > data["end_date"]:
        raise HTTPException(status_code=400, detail="start_date must be on or before end_date")

    new_buddy = {
        "user_id": ObjectId(user_id),
        "destination": data["destination"],
        "city": data.get("city", data["destination"]),
        "start_date": data["start_date"],
        "end_date": data["end_date"],
        "budget": float(data["budget"]) if "budget" in data else None,
        "interests": data.get("interests", []),
        "description": data.get("description", ""),
        "created_at": datetime.utcnow(),
    }

    result = db.travel_buddies.insert_one(new_buddy)

    return {
        "message": "Travel buddy listing created",
        "buddy_id": str(result.inserted_id),
        "destination": new_buddy["destination"],
        "start_date": new_buddy["start_date"],
        "end_date": new_buddy["end_date"],
    }


# ─── DELETE /travel-buddies/{id} ──────────────────────────────────────────────

@router.delete("/{buddy_id}")
def delete_travel_buddy(
    buddy_id: str,
    user_id: str = Depends(get_current_user),
):
    """Delete a travel buddy listing. Only the owner can do this."""
    buddy = get_buddy_or_404(buddy_id)

    if str(buddy["user_id"]) != user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own listings")

    db.travel_buddies.delete_one({"_id": ObjectId(buddy_id)})

    return {"message": "Travel buddy listing deleted"}


# ─── POST /travel-buddies/{id}/connect ───────────────────────────────────────

@router.post("/{buddy_id}/connect")
def connect_with_travel_buddy(
    buddy_id: str,
    user_id: str = Depends(get_current_user),
):
    """
    Connect with a travel buddy.

    Uses the existing messages collection to indicate chat availability.
    Returns the buddy's user_id so the frontend can open the Messages page.
    """
    buddy = get_buddy_or_404(buddy_id)

    buddy_user_id = str(buddy["user_id"])

    # Prevent connecting with yourself
    if buddy_user_id == user_id:
        raise HTTPException(status_code=400, detail="You cannot connect with your own listing")

    # Check if a conversation thread already exists between these two users
    existing = db.messages.find_one({
        "$or": [
            {"sender_id": ObjectId(user_id), "receiver_id": ObjectId(buddy_user_id)},
            {"sender_id": ObjectId(buddy_user_id), "receiver_id": ObjectId(user_id)},
        ]
    })

    # Optionally seed an intro message if no prior conversation exists
    if not existing:
        buddy_destination = buddy.get("destination", "your destination")
        intro_message = {
            "sender_id": ObjectId(user_id),
            "receiver_id": ObjectId(buddy_user_id),
            "content": (
                f"Hey! I saw your travel buddy listing for {buddy_destination} "
                f"({buddy.get('start_date')} – {buddy.get('end_date')}). "
                "Want to travel together? 🌍"
            ),
            "message_type": "travel_buddy_connect",
            "reference_id": ObjectId(buddy_id),
            "is_read": False,
            "created_at": datetime.utcnow(),
        }
        db.messages.insert_one(intro_message)

    return {
        "message": "Connection established! You can now chat.",
        "buddy_user_id": buddy_user_id,
        "chat_available": True,
        "destination": buddy.get("destination"),
        "travel_dates": {
            "start_date": buddy.get("start_date"),
            "end_date": buddy.get("end_date"),
        },
    }
