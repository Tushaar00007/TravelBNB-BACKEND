from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from app.core.database import db
from app.core.dependencies import get_current_user
from datetime import datetime
from bson import ObjectId
from typing import Optional, List
import json
import cloudinary.uploader

router = APIRouter()


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _serialize_buddy(doc: dict):
    if not doc:
        return None
    doc["id"] = str(doc.pop("_id"))
    doc["user_id"] = str(doc["user_id"])

    # Enrichment: Add owner details
    owner = db.users.find_one(
        {"_id": ObjectId(doc["user_id"])},
        {"name": 1, "profile_image": 1, "profile_picture": 1, "is_verified": 1}
    )
    if owner:
        doc["name"] = owner.get("name", "Unknown")
        doc["avatar"] = owner.get("profile_image") or owner.get("profile_picture", "")
        doc["user_verified"] = owner.get("is_verified", False)

    # Compute spots_left from accepted applications
    try:
        group_size = int(doc.get("group_size", 1)) if doc.get("group_size") else 1
    except (ValueError, TypeError):
        group_size = 1

    try:
        accepted_count = db.buddy_applications.count_documents({
            "request_id": ObjectId(doc["id"]),
            "status": "accepted"
        })
    except Exception:
        accepted_count = 0

    doc["accepted_count"] = accepted_count
    doc["total_spots"] = group_size
    doc["spots_left"] = max(0, group_size - accepted_count)
    doc["is_full"] = doc["spots_left"] == 0

    return doc


def get_buddy_or_404(buddy_id: str) -> dict:
    try:
        oid = ObjectId(buddy_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid travel buddy ID")

    buddy = db.buddy_requests.find_one({"_id": oid})
    if not buddy:
        raise HTTPException(status_code=404, detail="Travel buddy listing not found")
    return buddy


# ─── GET /travel-buddies/ ─────────────────────────────────────────────────────

@router.get("/")
def get_all_travel_buddies(
    destination: Optional[str] = Query(None),
    travel_style: Optional[str] = Query(None),
    gender_preference: Optional[str] = Query(None)
):
    """Return all travel buddy listings with optional filtering."""
    query = {
        "status": "active",
        "$or": [
            {"is_active": True},
            {"is_active": {"$exists": False}}
        ]
    }

    if destination:
        query["destination"] = {"$regex": destination, "$options": "i"}
    if travel_style:
        query["travel_style"] = {"$regex": f"^{travel_style}$", "$options": "i"}
    if gender_preference:
        query["gender_preference"] = {"$regex": f"^{gender_preference}$", "$options": "i"}

    buddies = list(db.buddy_requests.find(query).sort("created_at", -1))
    return [_serialize_buddy(b) for b in buddies]


# ─── GET /travel-buddies/host/applications ───────────────────────────────

@router.get("/host/applications")
def get_host_buddy_applications(user_id: str = Depends(get_current_user)):
    """Return all join applications for trips owned by the current host, enriched with applicant info."""
    uid = ObjectId(user_id)

    # Find all trips owned by this host
    trips = list(db.buddy_requests.find(
        {"$or": [{"user_id": uid}, {"user_id": user_id}]},
        {"_id": 1, "destination": 1, "start_date": 1, "end_date": 1, "images": 1}
    ))
    if not trips:
        return []

    trip_map = {str(t["_id"]): t for t in trips}
    trip_ids = [t["_id"] for t in trips]

    # Find all applications for these trips
    apps = list(db.buddy_applications.find({"request_id": {"$in": trip_ids}}).sort("created_at", -1))

    enriched = []
    for app in apps:
        # Resolve applicant name
        guest_name = "Traveler"
        applicant_id = app.get("user_id")
        if applicant_id:
            try:
                u = db.users.find_one(
                    {"_id": applicant_id if isinstance(applicant_id, ObjectId) else ObjectId(applicant_id)},
                    {"name": 1, "email": 1}
                )
                if u:
                    guest_name = u.get("name") or (u.get("email", "Traveler").split("@")[0])
            except Exception:
                pass

        trip = trip_map.get(str(app.get("request_id")), {})
        created_at = app.get("created_at")

        enriched.append({
            "_id": str(app["_id"]),
            "id": str(app["_id"]),
            "application_id": str(app["_id"]),
            "trip_id": str(app.get("request_id", "")),
            "property_id": str(app.get("request_id", "")),
            "property_title": f"Trip to {trip.get('destination', 'Unknown')}",
            "property_image": (trip.get("images") or [None])[0],
            "host_id": user_id,
            "guest_id": str(app.get("user_id", "")),
            "guest_name": guest_name,
            "phone": app.get("phone", ""),
            "message": f"Wants to join your trip to {trip.get('destination', '')}. Contact: +91 {app.get('phone', 'N/A')}",
            "check_in": trip.get("start_date", ""),
            "check_out": trip.get("end_date", ""),
            "guests": 1,
            "total_price": 0,
            "status": app.get("status", "pending"),
            "created_at": created_at.isoformat() if isinstance(created_at, datetime) else created_at,
            "kind": "buddy_request",
        })

    return enriched


@router.patch("/applications/{application_id}/approve")
def approve_buddy_application(application_id: str, user_id: str = Depends(get_current_user)):
    """Approve a travel buddy join application."""
    try:
        oid = ObjectId(application_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid application ID")

    app = db.buddy_applications.find_one({"_id": oid})
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    # Verify the trip is owned by this host
    trip = db.buddy_requests.find_one({"_id": app.get("request_id")})
    if not trip or str(trip.get("user_id")) != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    db.buddy_applications.update_one(
        {"_id": oid},
        {"$set": {"status": "accepted", "approved_at": datetime.utcnow()}}
    )
    return {"application_id": application_id, "status": "accepted", "message": "Application approved"}


@router.patch("/applications/{application_id}/decline")
def decline_buddy_application(application_id: str, user_id: str = Depends(get_current_user)):
    """Decline a travel buddy join application."""
    try:
        oid = ObjectId(application_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid application ID")

    app = db.buddy_applications.find_one({"_id": oid})
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    trip = db.buddy_requests.find_one({"_id": app.get("request_id")})
    if not trip or str(trip.get("user_id")) != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    db.buddy_applications.update_one(
        {"_id": oid},
        {"$set": {"status": "rejected", "rejected_at": datetime.utcnow()}}
    )
    return {"application_id": application_id, "status": "rejected", "message": "Application declined"}


# ─── GET /travel-buddies/{id} ────────────────────────────────────────────────

@router.get("/{buddy_id}")
def get_travel_buddy(buddy_id: str):
    """Return a single travel buddy listing by ID."""
    buddy = get_buddy_or_404(buddy_id)
    return _serialize_buddy(buddy)


# ─── GET /travel-buddies/search ───────────────────────────────────────────────

@router.get("/search")
def search_travel_buddies(
    destination: str = Query(..., description="Destination city to search for"),
    start_date: str = Query(..., description="Your trip start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="Your trip end date (YYYY-MM-DD)"),
):
    """
    Find travel buddies going to the same destination with overlapping dates.
    """
    try:
        datetime.strptime(start_date, "%Y-%m-%d")
        datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be in YYYY-MM-DD format")

    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be on or before end_date")

    query = {
        "status": "active",
        "$or": [
            {"is_active": True},
            {"is_active": {"$exists": False}}
        ],
        "destination": {"$regex": f"^{destination}$", "$options": "i"},
        "start_date": {"$lte": end_date},
        "end_date":   {"$gte": start_date},
    }

    buddies = list(db.buddy_requests.find(query).sort("created_at", -1))
    return {
        "count": len(buddies),
        "results": [_serialize_buddy(b) for b in buddies],
    }


# ─── POST /travel-buddies/ ────────────────────────────────────────────────────

@router.post("/", status_code=201)
async def create_travel_buddy(
    destination: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    city: str = Form(None),
    budget: str = Form(None),
    description: str = Form(None),
    travel_style: str = Form(None),
    group_size: str = Form(None),
    gender_preference: str = Form(None),
    age_range: str = Form(None),
    languages: str = Form("[]"),
    interests: str = Form("[]"),
    images: List[UploadFile] = File(default=[]),
    user_id: str = Depends(get_current_user)
):
    """Create a new travel buddy listing with image uploads."""
    
    # 1. Image Uploads
    image_urls = []
    for image in images:
        try:
            if not image.content_type.startswith("image/"):
                continue
            result = cloudinary.uploader.upload(
                image.file,
                folder="travelbnb/travel_buddies",
                resource_type="auto"
            )
            image_urls.append(result.get("secure_url"))
        except Exception as e:
            print(f"Error uploading image to Cloudinary: {str(e)}")

    # 2. Parse JSON fields
    try:
        languages_list = json.loads(languages)
        interests_list = json.loads(interests)
    except json.JSONDecodeError:
        languages_list, interests_list = [], []

    # 3. Create document
    new_buddy = {
        "user_id": ObjectId(user_id),
        "destination": destination,
        "city": city or destination,
        "start_date": start_date,
        "end_date": end_date,
        "budget": float(budget) if budget else None,
        "description": description or "",
        "travel_style": travel_style or "",
        "group_size": group_size or "1",
        "gender_preference": gender_preference or "any",
        "age_range": age_range or "",
        "languages": languages_list,
        "interests": interests_list,
        "images": image_urls,
        "status": "active",
        "created_at": datetime.utcnow(),
    }

    result = db.buddy_requests.insert_one(new_buddy)

    # Promote user to host — but never downgrade elevated admin roles
    _current_user = db.users.find_one({"_id": ObjectId(user_id)}, {"role": 1})
    _current_role = _current_user.get("role", "guest") if _current_user else "guest"
    _protected_roles = {"super_admin", "admin", "sub_admin"}

    if _current_role in _protected_roles:
        # Only flag as host — never touch the admin role
        db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"is_host": True}}
        )
    else:
        # Safe to promote guest → host
        db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"is_host": True, "role": "host"}}
        )

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

    db.buddy_requests.delete_one({"_id": ObjectId(buddy_id)})

    return {"message": "Travel buddy listing deleted"}


# ─── POST /travel-buddies/{id}/connect ───────────────────────────────────────

@router.post("/{buddy_id}/connect")
def connect_with_travel_buddy(
    buddy_id: str,
    user_id: str = Depends(get_current_user),
):
    """
    Connect with a travel buddy.
    """
    buddy = get_buddy_or_404(buddy_id)
    buddy_user_id = str(buddy["user_id"])

    if buddy_user_id == user_id:
        raise HTTPException(status_code=400, detail="You cannot connect with your own listing")

    existing = db.messages.find_one({
        "$or": [
            {"sender_id": ObjectId(user_id), "receiver_id": ObjectId(buddy_user_id)},
            {"sender_id": ObjectId(buddy_user_id), "receiver_id": ObjectId(user_id)},
        ]
    })

    if not existing:
        buddy_destination = buddy.get("destination", "your destination")
        intro_message = {
            "sender_id": ObjectId(user_id),
            "receiver_id": ObjectId(buddy_user_id),
            "message": (
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


@router.post("/{buddy_id}/request")
def request_to_join_trip(
    buddy_id: str,
    payload: dict,
    user_id: str = Depends(get_current_user),
):
    """
    Submit a request to join an existing travel buddy trip.
    Creates a buddy_application record and sends an intro message to the trip owner.
    """
    buddy = get_buddy_or_404(buddy_id)
    trip_owner_id = str(buddy["user_id"])

    if trip_owner_id == user_id:
        raise HTTPException(status_code=400, detail="You cannot request to join your own trip")

    phone = (payload or {}).get("phone", "").strip()
    if not phone or len(phone) != 10 or not phone.isdigit():
        raise HTTPException(status_code=400, detail="Valid 10-digit phone number required")

    # Prevent duplicate applications
    existing = db.buddy_applications.find_one({
        "request_id": ObjectId(buddy_id),
        "user_id": ObjectId(user_id),
    })
    if existing:
        raise HTTPException(status_code=400, detail="You have already requested to join this trip")

    # Create application record
    application = {
        "request_id": ObjectId(buddy_id),
        "user_id": ObjectId(user_id),
        "phone": phone,
        "status": "pending",
        "created_at": datetime.utcnow(),
    }
    result = db.buddy_applications.insert_one(application)

    # Send intro message to the trip owner so it appears in their inbox
    try:
        applicant = db.users.find_one({"_id": ObjectId(user_id)}, {"name": 1})
        applicant_name = applicant.get("name", "A traveler") if applicant else "A traveler"
        destination = buddy.get("destination", "your trip")

        intro_message = {
            "sender_id": ObjectId(user_id),
            "recipient_id": ObjectId(trip_owner_id),
            "receiver_id": ObjectId(trip_owner_id),
            "message": f"Hi! I'd like to join your trip to {destination}. My contact: +91 {phone}",
            "message_type": "travel_buddy_request",
            "reference_id": ObjectId(buddy_id),
            "property_id": str(buddy_id),
            "property_name": f"Trip to {destination}",
            "is_read": False,
            "created_at": datetime.utcnow(),
        }
        db.messages.insert_one(intro_message)
    except Exception as e:
        print(f"Warning: Failed to send intro message: {e}")

    return {
        "message": "Join request sent successfully",
        "application_id": str(result.inserted_id),
        "status": "pending",
    }
