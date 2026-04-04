from fastapi import APIRouter, Depends, HTTPException, Query, Form, File, UploadFile
from app.core.database import db
from app.core.dependencies import get_current_user, get_current_user_optional
from app.models.crashpad import CrashpadCreate, Location
from datetime import datetime
from bson import ObjectId
from typing import Optional, List
import uuid
import json
import re
import cloudinary.uploader

router = APIRouter()

# ─── Helpers ──────────────────────────────────────────────────────────────────

def serialize_crashpad(doc: dict) -> dict:
    """Convert MongoDB document to JSON-serialisable dict."""
    doc["id"] = str(doc.pop("_id"))
    doc["host_id"] = str(doc["host_id"])
    return doc


def get_crashpad_or_404(crashpad_id: str) -> dict:
    try:
        oid = ObjectId(crashpad_id)
    except Exception:
        # Try searching by the custom crashpad_id if ObjectId fails
        crashpad = db.crashpads_listings.find_one({"crashpad_id": crashpad_id})
        if crashpad:
            return crashpad
        raise HTTPException(status_code=400, detail="Invalid crashpad ID")

    crashpad = db.crashpads_listings.find_one({"_id": oid})
    if not crashpad:
        raise HTTPException(status_code=404, detail="Crashpad not found")
    return crashpad


# ─── ANALYTICS ──────────────────────────────────────────────────────────────

@router.post("/{id}/view")
async def track_view(id: str, user_id: Optional[str] = Depends(get_current_user_optional)):
    """Log a crashpad view."""
    try:
        db.views.insert_one({
            "crashpad_id": ObjectId(id),
            "user_id": ObjectId(user_id) if user_id else None,
            "timestamp": datetime.utcnow()
        })
        return {"message": "View tracked"}
    except Exception as e:
        return {"error": str(e)}


@router.get("/{id}/stats")
async def get_crashpad_stats(id: str, current_user_id: str = Depends(get_current_user)):
    """Fetch real-time analytics for a specific crashpad."""
    crashpad = get_crashpad_or_404(id)
    
    # Ownership Check
    if str(crashpad["host_id"]) != current_user_id:
        raise HTTPException(status_code=403, detail="Unauthorized to view these stats")

    oid = ObjectId(id)

    # 1. Total Views
    total_views = db.views.count_documents({"crashpad_id": oid})

    # 2. Total Bookings (Confirmed)
    # Note: Using propertyId for cross-collection consistency
    bookings = list(db.bookings.find({"propertyId": oid, "bookingStatus": "confirmed"}))
    total_bookings = len(bookings)

    # 3. Total Earnings
    total_earnings = sum(b.get("totalPrice", 0) for b in bookings)

    # 4. Average Rating
    reviews = list(db.reviews.find({"crashpad_id": oid}))
    avg_rating = sum(r["rating"] for r in reviews) / len(reviews) if reviews else 0

    return {
        "stats": {
            "total_views": total_views,
            "total_bookings": total_bookings,
            "total_earnings": round(total_earnings, 2),
            "avg_rating": round(avg_rating, 1)
        }
    }


@router.get("/{id}/views-graph")
async def get_views_graph(id: str, current_user_id: str = Depends(get_current_user)):
    """Get time-series view data for the last 30 days."""
    crashpad = get_crashpad_or_404(id)
    if str(crashpad["host_id"]) != current_user_id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    oid = ObjectId(id)
    
    # Aggregation for daily counts (last 30 days)
    pipeline = [
        {"$match": {"crashpad_id": oid}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}},
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}},
        {"$limit": 30}
    ]
    
    results = list(db.views.aggregate(pipeline))
    
    # Format for Recharts: [{date: "...", views: ...}]
    return [{"date": r["_id"], "views": r["count"]} for r in results]


# ─── CRUD ROUTES ──────────────────────────────────────────────────────────────

@router.get("/")
def get_all_crashpads(
    city: Optional[str] = Query(None, description="Filter by city"),
):
    """Return all approved crashpads with optional city filter."""
    query: dict = {"status": "approved"}

    if city:
        query["location.city"] = {"$regex": f"^{city}", "$options": "i"}

    crashpads = list(db.crashpads_listings.find(query).sort("created_at", -1))
    return [serialize_crashpad(c) for c in crashpads]


@router.get("/search")
def search_crashpads(
    city: Optional[str] = Query(None),
    state: Optional[str] = Query(None)
):
    """Search crashpads ONLY based on city and state stored in the DB."""
    query: dict = {"status": "approved"}
    
    if city:
        query["location.city"] = {"$regex": f"^{city}", "$options": "i"}
    
    if state:
        query["location.state"] = {"$regex": f"^{state}", "$options": "i"}
        
    results = list(db.crashpads_listings.find(query).sort("created_at", -1))
    return [serialize_crashpad(r) for r in results]


@router.get("/locations")
def get_distinct_locations():
    """Return all unique city/state pairs currently in the database."""
    pipeline = [
        {"$match": {"status": "approved"}},
        {"$group": {
            "_id": {
                "city": "$location.city",
                "state": "$location.state"
            }
        }},
        {"$project": {
            "_id": 0,
            "city": "$_id.city",
            "state": "$_id.state"
        }},
        {"$sort": {"city": 1}}
    ]
    
    locations = list(db.crashpads_listings.aggregate(pipeline))
    return locations


@router.post("/", status_code=201)
async def create_crashpad(
    title: str = Form(...),
    description: str = Form(""),
    stay_type: str = Form(...),
    city: str = Form(...),
    state: str = Form(...),
    country: str = Form("INDIA"),
    pincode: str = Form(...),
    lat: float = Form(...),
    lng: float = Form(...),
    address: str = Form(...),
    flat: Optional[str] = Form(None),
    landmark: Optional[str] = Form(None),
    district: Optional[str] = Form(None),
    max_guests: int = Form(1),
    max_nights: int = Form(3),
    is_free: bool = Form(True),
    price_per_night: float = Form(0.0),
    host_bio: str = Form(""),
    interests: str = Form("[]"),
    languages: str = Form("[]"),
    house_rules: str = Form("[]"),
    preferences: str = Form("[]"),
    images: List[UploadFile] = File([]),
    user_id: str = Depends(get_current_user)
):
    """Create a new crashpad listing with image uploads."""
    
    if not re.match(r'^[A-Za-z\s]+$', title):
        raise HTTPException(status_code=400, detail="Title must contain only letters")
    
    if len(description) < 20:
        raise HTTPException(status_code=400, detail="Description must be at least 20 characters")
    
    if len(host_bio) > 200:
        raise HTTPException(status_code=400, detail="Host bio cannot exceed 200 characters")

    image_urls = []
    for image in images:
        try:
            if not image.content_type.startswith("image/"):
                continue
            result = cloudinary.uploader.upload(
                image.file,
                folder="travelbnb/crashpads",
                resource_type="auto"
            )
            image_urls.append(result.get("secure_url"))
        except Exception as e:
            print(f"Error uploading image to Cloudinary: {str(e)}")

    short_id = f"CP-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.utcnow()
    
    try:
        interests_list = json.loads(interests)
        languages_list = json.loads(languages)
        house_rules_list = json.loads(house_rules)
        preferences_list = json.loads(preferences)
    except json.JSONDecodeError:
        interests_list, languages_list, house_rules_list, preferences_list = [], [], [], []

    new_crashpad = {
        "crashpad_id": short_id,
        "host_id": ObjectId(user_id),
        "title": title,
        "description": description,
        "stay_type": stay_type,
        "location": {
            "address_line": address,
            "flat_suite": flat,
            "landmark": landmark,
            "district": (district or "").upper(),
            "city": city.upper(),
            "state": state.upper(),
            "country": country.upper(),
            "pincode": pincode,
            "lat": lat,
            "lng": lng
        },
        "host_bio": host_bio,
        "interests": interests_list,
        "languages": languages_list,
        "max_guests": max_guests,
        "max_nights": max_nights,
        "house_rules": house_rules_list,
        "preferences": preferences_list,
        "is_free": is_free,
        "price_per_night": price_per_night,
        "images": image_urls,
        "is_active": True,
        "status": "pending",
        "created_at": now,
        "updated_at": now
    }

    result = db.crashpads_listings.insert_one(new_crashpad)
    return {
        "message": "Crashpad created successfully",
        "id": str(result.inserted_id),
        "crashpad_id": short_id,
        "images": image_urls
    }


@router.get("/{crashpad_id}")
def get_crashpad(crashpad_id: str):
    """Return a single crashpad by ID with host details."""
    crashpad = get_crashpad_or_404(crashpad_id)
    host = db.users.find_one(
        {"_id": crashpad["host_id"]}, 
        {"name": 1, "profile_image": 1, "profile_picture": 1, "is_verified": 1, "trust_score": 1}
    )
    if host:
        crashpad["host_details"] = {
            "name": host.get("name", "Unknown"),
            "profile_image": host.get("profile_image") or host.get("profile_picture", ""),
            "is_verified": host.get("is_verified", False),
            "trust_score": host.get("trust_score", 0)
        }
    return serialize_crashpad(crashpad)


@router.get("/me")
def get_my_crashpads(user_id: str = Depends(get_current_user)):
    """Return all crashpads belonging to the authenticated user."""
    query = {"host_id": ObjectId(user_id)}
    crashpads = list(db.crashpads_listings.find(query).sort("created_at", -1))
    return [serialize_crashpad(c) for c in crashpads]


@router.get("/is-host/{user_id}")
async def check_is_host(user_id: str):
    """Verify if a user has any crashpad listings."""
    try:
        uid = ObjectId(user_id)
        crashpad = db.crashpads_listings.find_one({"host_id": uid})
        return {"isHost": True if crashpad else False}
    except Exception:
        return {"isHost": False}


@router.delete("/{id}")
def delete_crashpad(id: str, user_id: str = Depends(get_current_user)):
    """Delete a crashpad listing."""
    try:
        oid = ObjectId(id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ID format")

    crashpad = db.crashpads_listings.find_one({"_id": oid})
    if not crashpad:
        raise HTTPException(status_code=404, detail="Crashpad not found")

    if str(crashpad["host_id"]) != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    db.crashpads_listings.delete_one({"_id": oid})
    return {"message": "Crashpad deleted successfully"}


@router.get("/host-requests")
def get_host_requests(user_id: str = Depends(get_current_user)):
    """Return all stay requests for crashpads owned by the host."""
    pads = list(db.crashpads_listings.find({"host_id": ObjectId(user_id)}, {"_id": 1}))
    pad_ids = [p["_id"] for p in pads]
    reqs = list(db.requests.find({"crashpad_id": {"$in": pad_ids}}))
    for r in reqs:
        r["_id"] = str(r["_id"])
        r["crashpad_id"] = str(r["crashpad_id"])
        r["guest_id"] = str(r["guest_id"])
    return reqs
