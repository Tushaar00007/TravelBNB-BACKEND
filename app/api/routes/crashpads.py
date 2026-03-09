from fastapi import APIRouter, Depends, HTTPException, Query
from app.core.database import db
from app.core.dependencies import get_current_user
from datetime import datetime
from bson import ObjectId
from typing import Optional, List

router = APIRouter()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def serialize_crashpad(doc: dict) -> dict:
    """Convert MongoDB document to JSON-serialisable dict."""
    doc["id"] = str(doc.pop("_id"))
    doc["host_id"] = str(doc["host_id"])
    doc["members"] = [str(m) for m in doc.get("members", [])]
    doc["available_spots"] = doc.get("max_guests", 0) - doc.get("current_guests", 0)
    return doc


def get_crashpad_or_404(crashpad_id: str) -> dict:
    try:
        oid = ObjectId(crashpad_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid crashpad ID")

    crashpad = db.crashpads.find_one({"_id": oid})
    if not crashpad:
        raise HTTPException(status_code=404, detail="Crashpad not found")
    return crashpad


# ─── GET /crashpads/ ──────────────────────────────────────────────────────────

@router.get("/")
def get_all_crashpads(
    city: Optional[str] = Query(None, description="Filter by city"),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
):
    """Return all crashpads with optional filters."""
    query: dict = {}

    if city:
        query["city"] = {"$regex": city, "$options": "i"}
    if min_price is not None:
        query.setdefault("price_per_night", {})["$gte"] = min_price
    if max_price is not None:
        query.setdefault("price_per_night", {})["$lte"] = max_price

    crashpads = list(db.crashpads.find(query).sort("created_at", -1))
    return [serialize_crashpad(c) for c in crashpads]


# ─── GET /crashpads/{crashpad_id} ─────────────────────────────────────────────

@router.get("/{crashpad_id}")
def get_crashpad(crashpad_id: str):
    """Return a single crashpad by ID."""
    crashpad = get_crashpad_or_404(crashpad_id)
    return serialize_crashpad(crashpad)


# ─── POST /crashpads/ ─────────────────────────────────────────────────────────

@router.post("/", status_code=201)
def create_crashpad(data: dict, user_id: str = Depends(get_current_user)):
    """Create a new crashpad listing."""
    # Required fields validation
    required = ["title", "city", "price_per_night", "max_guests"]
    missing = [f for f in required if f not in data]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required fields: {', '.join(missing)}"
        )

    new_crashpad = {
        "host_id": ObjectId(user_id),
        "title": data["title"],
        "description": data.get("description", ""),
        "city": data["city"],
        "location": data.get("location", {"lat": 0.0, "lng": 0.0}),
        "price_per_night": float(data["price_per_night"]),
        "max_guests": int(data["max_guests"]),
        "current_guests": 0,
        "amenities": data.get("amenities", []),
        "images": data.get("images", []),
        "members": [],
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    result = db.crashpads.insert_one(new_crashpad)

    return {
        "message": "Crashpad created successfully",
        "crashpad_id": str(result.inserted_id),
        "title": new_crashpad["title"],
        "city": new_crashpad["city"],
        "price_per_night": new_crashpad["price_per_night"],
        "available_spots": new_crashpad["max_guests"],
    }


# ─── PUT /crashpads/{crashpad_id} ─────────────────────────────────────────────

@router.put("/{crashpad_id}")
def update_crashpad(
    crashpad_id: str,
    data: dict,
    user_id: str = Depends(get_current_user),
):
    """Update a crashpad. Only the host can do this."""
    crashpad = get_crashpad_or_404(crashpad_id)

    if str(crashpad["host_id"]) != user_id:
        raise HTTPException(status_code=403, detail="Only the host can update this crashpad")

    updatable_fields = [
        "title", "description", "city", "location",
        "price_per_night", "max_guests", "amenities", "images",
    ]
    update_payload = {
        field: data[field] for field in updatable_fields if field in data
    }

    # Validate max_guests doesn't drop below current_guests
    new_max = update_payload.get("max_guests")
    if new_max is not None and int(new_max) < crashpad.get("current_guests", 0):
        raise HTTPException(
            status_code=400,
            detail="max_guests cannot be less than current number of guests"
        )

    update_payload["updated_at"] = datetime.utcnow()

    db.crashpads.update_one(
        {"_id": ObjectId(crashpad_id)},
        {"$set": update_payload}
    )

    return {"message": "Crashpad updated successfully"}


# ─── DELETE /crashpads/{crashpad_id} ──────────────────────────────────────────

@router.delete("/{crashpad_id}")
def delete_crashpad(
    crashpad_id: str,
    user_id: str = Depends(get_current_user),
):
    """Delete a crashpad. Only the host can do this."""
    crashpad = get_crashpad_or_404(crashpad_id)

    if str(crashpad["host_id"]) != user_id:
        raise HTTPException(status_code=403, detail="Only the host can delete this crashpad")

    db.crashpads.delete_one({"_id": ObjectId(crashpad_id)})

    return {"message": "Crashpad deleted successfully"}


# ─── POST /crashpads/{crashpad_id}/join ───────────────────────────────────────

@router.post("/{crashpad_id}/join")
def join_crashpad(
    crashpad_id: str,
    user_id: str = Depends(get_current_user),
):
    """Join a crashpad if spots are available."""
    crashpad = get_crashpad_or_404(crashpad_id)

    user_oid = ObjectId(user_id)
    members = crashpad.get("members", [])

    # Already a member?
    if user_oid in members:
        raise HTTPException(status_code=400, detail="You have already joined this crashpad")

    # Host trying to join their own crashpad?
    if str(crashpad["host_id"]) == user_id:
        raise HTTPException(status_code=400, detail="Hosts cannot join their own crashpad")

    # Check capacity
    current = crashpad.get("current_guests", 0)
    max_g = crashpad.get("max_guests", 0)
    if current >= max_g:
        raise HTTPException(status_code=400, detail="Crashpad is fully booked — no spots available")

    # Add member and increment guest count
    db.crashpads.update_one(
        {"_id": ObjectId(crashpad_id)},
        {
            "$addToSet": {"members": user_oid},
            "$inc": {"current_guests": 1},
        }
    )

    new_count = current + 1
    return {
        "message": "Successfully joined the crashpad",
        "crashpad_id": crashpad_id,
        "current_guests": new_count,
        "available_spots": max_g - new_count,
    }


# ─── POST /crashpads/{crashpad_id}/leave ──────────────────────────────────────

@router.post("/{crashpad_id}/leave")
def leave_crashpad(
    crashpad_id: str,
    user_id: str = Depends(get_current_user),
):
    """Leave a crashpad."""
    crashpad = get_crashpad_or_404(crashpad_id)

    user_oid = ObjectId(user_id)
    members = crashpad.get("members", [])

    # Not a member?
    if user_oid not in members:
        raise HTTPException(status_code=400, detail="You are not a member of this crashpad")

    current = crashpad.get("current_guests", 0)

    db.crashpads.update_one(
        {"_id": ObjectId(crashpad_id)},
        {
            "$pull": {"members": user_oid},
            "$inc": {"current_guests": -1},
        }
    )

    new_count = max(current - 1, 0)
    max_g = crashpad.get("max_guests", 0)
    return {
        "message": "Successfully left the crashpad",
        "crashpad_id": crashpad_id,
        "current_guests": new_count,
        "available_spots": max_g - new_count,
    }
