from fastapi import APIRouter, HTTPException
from app.core.database import db
from app.utils.trip_helpers import to_oid, log_activity
from bson import ObjectId
from datetime import datetime, timezone

router = APIRouter()


# ─── helpers ────────────────────────────────────────────────────────────────

def serialize_trip(t: dict) -> dict:
    return {
        "_id": str(t["_id"]),
        "booking_id": str(t.get("booking_id", "")),
        "property_id": str(t.get("property_id", "")),
        "owner_id": str(t.get("owner_id", "")),
        "members": [str(m) for m in t.get("members", [])],
        "start_date": t["start_date"].isoformat() if isinstance(t.get("start_date"), datetime) else str(t.get("start_date", "")),
        "end_date": t["end_date"].isoformat() if isinstance(t.get("end_date"), datetime) else str(t.get("end_date", "")),
        "created_at": t["created_at"].isoformat() if isinstance(t.get("created_at"), datetime) else str(t.get("created_at", "")),
    }


def enrich_trip(trip: dict) -> dict:
    """Add property info + member names to a serialized trip dict."""
    prop = db.homes.find_one({"_id": ObjectId(trip["property_id"])}, {"title": 1, "images": 1, "location": 1, "price_per_night": 1})
    if prop:
        trip["property"] = {
            "title": prop.get("title", ""),
            "image": (prop.get("images") or [""])[0],
            "location": prop.get("location", ""),
            "price_per_night": prop.get("price_per_night", 0),
        }

    member_docs = list(db.users.find(
        {"_id": {"$in": [ObjectId(m) for m in trip["members"]]}},
        {"name": 1, "profile_image": 1, "email": 1}
    ))
    trip["member_details"] = [
        {"_id": str(m["_id"]), "name": m.get("name", ""), "profile_image": m.get("profile_image", ""), "email": m.get("email", "")}
        for m in member_docs
    ]
    return trip


# ─── Feature 2: create trip from booking ────────────────────────────────────

@router.post("/create")
def create_trip(payload: dict):
    """POST /api/trips/create  — call after booking confirmed."""
    booking_id_str = payload.get("booking_id", "")
    booking_id = to_oid(booking_id_str, "booking_id")

    booking = db.bookings.find_one({"_id": booking_id})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Idempotency: don't create duplicate trip for same booking
    existing = db.trips.find_one({"booking_id": booking_id})
    if existing:
        return {"success": True, "trip": serialize_trip(existing), "message": "Trip already exists"}

    owner_id = booking.get("user_id") or booking.get("userId")
    if not owner_id:
        raise HTTPException(status_code=400, detail="Booking has no user_id")

    owner_oid = ObjectId(str(owner_id))
    prop_oid = ObjectId(str(booking.get("home_id") or booking.get("homeId") or booking.get("property_id")))

    # Parse dates
    def parse_date(val):
        if isinstance(val, datetime):
            return val
        try:
            return datetime.fromisoformat(str(val))
        except Exception:
            return datetime.now(timezone.utc)

    start = parse_date(booking.get("check_in") or booking.get("checkIn"))
    end = parse_date(booking.get("check_out") or booking.get("checkOut"))

    trip_doc = {
        "booking_id": booking_id,
        "property_id": prop_oid,
        "owner_id": owner_oid,
        "members": [owner_oid],
        "start_date": start,
        "end_date": end,
        "created_at": datetime.now(timezone.utc),
    }

    result = db.trips.insert_one(trip_doc)
    trip_doc["_id"] = result.inserted_id

    log_activity(result.inserted_id, owner_oid, "Trip created")
    return {"success": True, "trip": serialize_trip(trip_doc)}


# ─── Feature 3: members ──────────────────────────────────────────────────────

@router.post("/{trip_id}/add-member")
def add_member(trip_id: str, payload: dict):
    trip_oid = to_oid(trip_id, "trip_id")
    user_id_str = payload.get("user_id", "")
    user_oid = to_oid(user_id_str, "user_id")

    trip = db.trips.find_one({"_id": trip_oid})
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    user = db.users.find_one({"_id": user_oid})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db.trips.update_one({"_id": trip_oid}, {"$addToSet": {"members": user_oid}})
    log_activity(trip_oid, user_oid, f"{user.get('name', 'Someone')} joined the trip")
    return {"success": True, "message": "Member added"}


@router.delete("/{trip_id}/remove-member")
def remove_member(trip_id: str, payload: dict):
    trip_oid = to_oid(trip_id, "trip_id")
    user_oid = to_oid(payload.get("user_id", ""), "user_id")

    trip = db.trips.find_one({"_id": trip_oid})
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.get("owner_id") == user_oid:
        raise HTTPException(status_code=400, detail="Cannot remove owner from trip")

    db.trips.update_one({"_id": trip_oid}, {"$pull": {"members": user_oid}})
    log_activity(trip_oid, user_oid, "Member left the trip")
    return {"success": True, "message": "Member removed"}


# ─── Feature 4: group chat ───────────────────────────────────────────────────

@router.post("/{trip_id}/messages")
def send_trip_message(trip_id: str, payload: dict):
    trip_oid = to_oid(trip_id, "trip_id")
    sender_str = payload.get("sender_id", "")
    message = payload.get("message", "").strip()

    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    sender_oid = to_oid(sender_str, "sender_id")
    trip = db.trips.find_one({"_id": trip_oid})
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    doc = {
        "trip_id": trip_oid,
        "sender_id": sender_oid,
        "message": message,
        "created_at": datetime.now(timezone.utc),
    }
    result = db.messages.insert_one(doc)
    doc["_id"] = result.inserted_id

    return {
        "success": True,
        "message": {
            "_id": str(doc["_id"]),
            "trip_id": trip_id,
            "sender_id": sender_str,
            "message": message,
            "created_at": doc["created_at"].isoformat(),
        }
    }


@router.get("/{trip_id}/messages")
def get_trip_messages(trip_id: str):
    trip_oid = to_oid(trip_id, "trip_id")
    msgs = list(db.messages.find({"trip_id": trip_oid}).sort("created_at", 1))

    result = []
    for m in msgs:
        sender = db.users.find_one({"_id": m.get("sender_id")}, {"name": 1, "profile_image": 1}) or {}
        result.append({
            "_id": str(m["_id"]),
            "trip_id": trip_id,
            "sender_id": str(m.get("sender_id", "")),
            "sender_name": sender.get("name", ""),
            "sender_pic": sender.get("profile_image", ""),
            "message": m.get("message", ""),
            "created_at": m["created_at"].isoformat() if isinstance(m.get("created_at"), datetime) else "",
        })

    return {"messages": result}


# ─── Feature 6: activities ───────────────────────────────────────────────────

@router.get("/{trip_id}/activities")
def get_activities(trip_id: str):
    trip_oid = to_oid(trip_id, "trip_id")
    acts = list(db.trip_activities.find({"trip_id": trip_oid}).sort("created_at", 1))
    return {
        "activities": [
            {
                "_id": str(a["_id"]),
                "action": a.get("action", ""),
                "created_at": a["created_at"].isoformat() if isinstance(a.get("created_at"), datetime) else "",
            }
            for a in acts
        ]
    }


# ─── Feature 7: user trips ───────────────────────────────────────────────────

@router.get("/user/{user_id}")
def get_user_trips(user_id: str):
    user_oid = to_oid(user_id, "user_id")
    now = datetime.now(timezone.utc)

    trips = list(db.trips.find({"members": user_oid}))
    upcoming, past = [], []

    for t in trips:
        serialized = enrich_trip(serialize_trip(t))
        start = t.get("start_date")
        end = t.get("end_date")

        if isinstance(start, datetime) and start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if isinstance(end, datetime) and end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        if isinstance(end, datetime) and end < now:
            past.append(serialized)
        else:
            upcoming.append(serialized)

    return {"upcoming_trips": upcoming, "past_trips": past}


# ─── Feature 8: trip details ─────────────────────────────────────────────────

@router.get("/{trip_id}")
def get_trip(trip_id: str):
    trip_oid = to_oid(trip_id, "trip_id")
    trip = db.trips.find_one({"_id": trip_oid})
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    serialized = enrich_trip(serialize_trip(trip))

    # Expenses summary
    expenses = list(db.expenses.find({"trip_id": trip_oid}))
    total_spent = sum(e.get("amount", 0) for e in expenses)
    serialized["expenses_summary"] = {
        "total": total_spent,
        "count": len(expenses),
    }

    return {"trip": serialized}
