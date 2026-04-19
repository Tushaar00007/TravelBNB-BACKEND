from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from app.core.database import db
from app.core.dependencies import get_current_user
from app.utils.trip_helpers import to_oid, log_activity
from bson import ObjectId
from datetime import datetime, timezone
import cloudinary
import cloudinary.uploader
import os

router = APIRouter()


# ─── helpers ────────────────────────────────────────────────────────────────

def serialize_trip(t: dict) -> dict:
    return {
        "_id": str(t["_id"]),
        "title": t.get("title", "My Trip"),
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
    prop = db.homes.find_one({"_id": ObjectId(trip["property_id"])}, {"title": 1, "images": 1, "location": 1, "price_per_night": 1, "city": 1})
    if prop:
        trip["property"] = {
            "title": prop.get("title", ""),
            "image": (prop.get("images") or [""])[0],
            "location": prop.get("location") or prop.get("city") or "Location TBD",
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
def create_trip(payload: dict, current_user: str = Depends(get_current_user)):
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

    owner_oid = ObjectId(current_user)
    prop_oid = ObjectId(str(booking.get("propertyId") or booking.get("home_id") or booking.get("property_id")))

    # Base dates on booking
    start = booking.get("checkIn") or booking.get("check_in")
    end = booking.get("checkOut") or booking.get("check_out")

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
def add_member(trip_id: str, payload: dict, current_user: str = Depends(get_current_user)):
    trip_oid = to_oid(trip_id, "trip_id")
    user_id_str = payload.get("user_id", "")
    user_oid = to_oid(user_id_str, "user_id")

    trip = db.trips.find_one({"_id": trip_oid})
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    
    # AUTH: Only members can invite others
    if ObjectId(current_user) not in trip.get("members", []):
        raise HTTPException(status_code=403, detail="Not authorized")

    user = db.users.find_one({"_id": user_oid})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db.trips.update_one({"_id": trip_oid}, {"$addToSet": {"members": user_oid}})
    log_activity(trip_oid, user_oid, f"{user.get('name', 'Someone')} joined the trip")
    return {"success": True, "message": "Member added"}


@router.delete("/{trip_id}/remove-member")
def remove_member(trip_id: str, payload: dict, current_user: str = Depends(get_current_user)):
    trip_oid = to_oid(trip_id, "trip_id")
    user_oid = to_oid(payload.get("user_id", ""), "user_id")

    trip = db.trips.find_one({"_id": trip_oid})
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    
    # AUTH: Only owner can remove someone, or person can remove self
    is_owner = trip.get("owner_id") == ObjectId(current_user)
    is_self = ObjectId(current_user) == user_oid
    if not (is_owner or is_self):
        raise HTTPException(status_code=403, detail="Not authorized")

    if trip.get("owner_id") == user_oid:
        raise HTTPException(status_code=400, detail="Cannot remove owner from trip")

    db.trips.update_one({"_id": trip_oid}, {"$pull": {"members": user_oid}})
    log_activity(trip_oid, user_oid, "Member left the trip")
    return {"success": True, "message": "Member removed"}


# ─── Feature 4: group chat ───────────────────────────────────────────────────

@router.post("/{trip_id}/messages")
def send_trip_message(trip_id: str, payload: dict, current_user: str = Depends(get_current_user)):
    trip_oid = to_oid(trip_id, "trip_id")
    message = payload.get("message", "").strip()
    msg_type = payload.get("type", "text")
    file_url = payload.get("file_url", "")
    reply_to = payload.get("reply_to")

    if not message and not file_url:
        raise HTTPException(status_code=400, detail="message or file_url is required")

    sender_oid = ObjectId(current_user)
    trip = db.trips.find_one({"_id": trip_oid})
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    
    # AUTH
    if sender_oid not in trip.get("members", []):
        raise HTTPException(status_code=403, detail="Not authorized")

    doc = {
        "trip_id": trip_oid,
        "sender_id": sender_oid,
        "message": message,
        "type": msg_type,
        "file_url": file_url,
        "reply_to": ObjectId(reply_to) if reply_to else None,
        "reactions": [],
        "created_at": datetime.now(timezone.utc),
    }
    result = db.messages.insert_one(doc)
    doc["_id"] = result.inserted_id

    return {
        "success": True,
        "message": {
            "_id": str(doc["_id"]),
            "trip_id": trip_id,
            "sender_id": current_user,
            "message": message,
            "type": msg_type,
            "file_url": file_url,
            "reply_to": reply_to,
            "reactions": [],
            "created_at": doc["created_at"].isoformat(),
        }
    }


@router.post("/{trip_id}/chat/upload")
async def upload_chat_file(trip_id: str, file: UploadFile = File(...), current_user: str = Depends(get_current_user)):
    trip_oid = to_oid(trip_id, "trip_id")
    trip = db.trips.find_one({"_id": trip_oid})
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    
    # AUTH
    if ObjectId(current_user) not in trip.get("members", []):
        raise HTTPException(status_code=403, detail="Not authorized")

    try:
        content = await file.read()
        
        # Determine resource type
        resource_type = "image" if file.content_type.startswith("image/") else "raw"
        
        upload_result = cloudinary.uploader.upload(
            content,
            folder=f"travelbnb/chats/{trip_id}",
            resource_type=resource_type,
            public_id=f"chat_{os.urandom(4).hex()}_{file.filename}",
        )
        
        return {
            "success": True,
            "file_url": upload_result["secure_url"],
            "type": "image" if resource_type == "image" else "file",
            "filename": file.filename
        }
    except Exception as e:
        print(f"!!! CHAT UPLOAD ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{trip_id}/chat/react")
def react_to_message(trip_id: str, payload: dict, current_user: str = Depends(get_current_user)):
    trip_oid = to_oid(trip_id, "trip_id")
    message_id = payload.get("message_id")
    emoji = payload.get("emoji")

    if not message_id or not emoji:
        raise HTTPException(status_code=400, detail="message_id and emoji are required")

    user_oid = ObjectId(current_user)
    msg_oid = ObjectId(message_id)

    # Check if user is member of trip
    trip = db.trips.find_one({"_id": trip_oid})
    if not trip or user_oid not in trip.get("members", []):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Update logic: remove existing reaction by this user, then add new one
    db.messages.update_one(
        {"_id": msg_oid},
        {"$pull": {"reactions": {"user_id": user_oid}}}
    )
    
    db.messages.update_one(
        {"_id": msg_oid},
        {"$push": {"reactions": {"user_id": user_oid, "emoji": emoji}}}
    )

    return {"success": True}


@router.get("/{trip_id}/messages")
def get_trip_messages(trip_id: str, current_user: str = Depends(get_current_user)):
    trip_oid = to_oid(trip_id, "trip_id")
    trip = db.trips.find_one({"_id": trip_oid})
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    
    # AUTH
    if ObjectId(current_user) not in trip.get("members", []):
        raise HTTPException(status_code=403, detail="Not authorized")

    msgs = list(db.messages.find({"trip_id": trip_oid}).sort("created_at", 1))

    result = []
    for m in msgs:
        sender = db.users.find_one({"_id": m.get("sender_id")}, {"name": 1, "profile_image": 1}) or {}
        
        # Populate reply message text
        reply_to_text = ""
        if m.get("reply_to"):
            parent_msg = db.messages.find_one({"_id": m["reply_to"]}, {"message": 1})
            if parent_msg:
                reply_to_text = parent_msg.get("message", "").strip() or "File attachment"

        result.append({
            "_id": str(m["_id"]),
            "trip_id": trip_id,
            "sender_id": str(m.get("sender_id", "")),
            "sender_name": sender.get("name", ""),
            "sender_pic": sender.get("profile_image", ""),
            "message": m.get("message", ""),
            "type": m.get("type", "text"),
            "file_url": m.get("file_url", ""),
            "reply_to": str(m["reply_to"]) if m.get("reply_to") else None,
            "reply_to_text": reply_to_text,
            "reactions": [
                {"user_id": str(r["user_id"]), "emoji": r["emoji"]} 
                for r in m.get("reactions", [])
            ],
            "created_at": m["created_at"].isoformat() if isinstance(m.get("created_at"), datetime) else "",
        })

    return {"messages": result}


# ─── Feature 7: user trips ───────────────────────────────────────────────────

@router.get("/my")
def get_my_trips(current_user: str = Depends(get_current_user)):
    """GET /api/trips/my — returns upcoming and past trips for the current user."""
    user_oid = ObjectId(current_user)
    now = datetime.now(timezone.utc)

    # 1. Fetch existing trip documents
    trip_query = {
        "$or": [
            {"owner_id": user_oid},
            {"members": user_oid},
            {"userId": user_oid}
        ]
    }
    existing_trips = list(db.trips.find(trip_query))
    # Keep track of booking IDs that already have trips
    trip_booking_ids = {str(t["booking_id"]) for t in existing_trips if t.get("booking_id")}

    # 2. Fetch confirmed + paid bookings for this user
    booking_query = {
        "userId": user_oid,
        "bookingStatus": "confirmed",
        "paymentStatus": "success"
    }
    bookings = list(db.bookings.find(booking_query))
    
    # 3. Handle confirmed + paid bookings (ensure they have trip documents)
    for b in bookings:
        booking_id = b["_id"]
        if str(booking_id) not in trip_booking_ids:
            # AUTO-CREATE TRIP DOCUMENT
            try:
                prop = db.homes.find_one({"_id": b["propertyId"]}, {"title": 1})
                prop_title = prop.get("title", "Stay") if prop else "Stay"
                
                trip_doc = {
                    "title": f"Trip to {prop_title}",
                    "booking_id": booking_id,
                    "property_id": b.get("propertyId"),
                    "userId": user_oid,
                    "owner_id": user_oid,
                    "members": [user_oid],
                    "start_date": b.get("checkIn"),
                    "end_date": b.get("checkOut"),
                    "created_at": datetime.now(timezone.utc),
                }
                # Use upsert to avoid race conditions
                result = db.trips.update_one(
                    {"booking_id": booking_id}, 
                    {"$setOnInsert": trip_doc}, 
                    upsert=True
                )
                if result.upserted_id:
                    print(f"!!! SUCCESS: Lazy-created trip for booking {booking_id} !!!")
            except Exception as e:
                print(f"!!! ERROR: Failed lazy trip creation: {e} !!!")

    # 4. Final query now that we've ensured all bookings should have trip docs
    # (Re-running query is simplest, or we can just append the new docs)
    all_trips_cursor = db.trips.find(trip_query).sort("start_date", 1)
    results = [enrich_trip(serialize_trip(t)) for t in all_trips_cursor]

    print(f"!!! DEBUG: Returning {len(results)} trips for user {current_user} !!!")

    upcoming, past = [], []
    for t in results:
        start = t.get("start_date")
        end = t.get("end_date")

        # Handle various date formats (string vs datetime)
        if isinstance(start, str):
            try: start = datetime.fromisoformat(start.replace("Z", "+00:00"))
            except: pass
        if isinstance(end, str):
            try: end = datetime.fromisoformat(end.replace("Z", "+00:00"))
            except: pass

        # Convert to aware UTC if naive
        if isinstance(start, datetime) and start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if isinstance(end, datetime) and end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        # Logic for grouping
        if isinstance(start, datetime) and start >= now:
            upcoming.append(t)
        elif isinstance(end, datetime) and end < now:
            past.append(t)
        else:
            # Ongoing or edge cases -> upcoming
            upcoming.append(t)

    # Sort
    upcoming.sort(key=lambda x: x.get("start_date", ""), reverse=False)
    past.sort(key=lambda x: x.get("start_date", ""), reverse=True)

    return {"upcoming_trips": upcoming, "past_trips": past}


@router.get("/user/{user_id}")
def get_user_trips(user_id: str, current_user: str = Depends(get_current_user)):
    """Legacy endpoint — redirects to /my logic for self."""
    if user_id != current_user:
        raise HTTPException(status_code=403, detail="Not authorized")
    return get_my_trips(current_user)


# ─── Feature 8: trip details ─────────────────────────────────────────────────

@router.get("/{trip_id}")
def get_trip(trip_id: str, current_user: str = Depends(get_current_user)):
    trip_oid = to_oid(trip_id, "trip_id")
    trip = db.trips.find_one({"_id": trip_oid})
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    
    # AUTH
    if ObjectId(current_user) not in trip.get("members", []):
        raise HTTPException(status_code=403, detail="Not authorized")

    serialized = enrich_trip(serialize_trip(trip))

    # Expenses summary
    expenses = list(db.expenses.find({"trip_id": trip_oid}))
    total_spent = sum(e.get("amount", 0) for e in expenses)
    serialized["expenses_summary"] = {
        "total": total_spent,
        "count": len(expenses),
    }

    return {"trip": serialized}
