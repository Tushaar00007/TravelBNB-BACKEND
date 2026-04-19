import json
import cloudinary.uploader
from fastapi import APIRouter, Depends, HTTPException, Form, File, UploadFile
from typing import List, Optional
from app.core.database import db
from app.core.dependencies import get_current_user
from datetime import datetime
from bson import ObjectId

router = APIRouter()

# ✅ Create Home (Protected - Multipart/FormData)
@router.post("/", status_code=201)
async def create_home(
    title: str = Form(...),
    description: str = Form(""),
    property_type: str = Form("House"),
    price_per_night: float = Form(0.0),
    is_free: bool = Form(True),
    city: str = Form(...),
    state: str = Form(...),
    country: str = Form("INDIA"),
    pincode: str = Form(""),
    address: str = Form(""),
    lat: float = Form(None),
    lng: float = Form(None),
    max_guests: int = Form(1),
    bedrooms: int = Form(1),
    beds: int = Form(1),
    bathrooms: int = Form(1),
    amenities: str = Form("[]"),
    safety_features: str = Form("[]"),
    image_urls: str = Form("[]"),
    images: List[UploadFile] = File([]),
    user_id: str = Depends(get_current_user)
):
    """Create a new home listing with image uploads."""
    
    image_urls_final = []
    try:
        image_urls_final = json.loads(image_urls)
    except:
        image_urls_final = []

    for image in images:
        try:
            if not image.content_type.startswith("image/"):
                continue
            result = cloudinary.uploader.upload(
                image.file,
                folder="travelbnb/homes",
                resource_type="auto"
            )
            image_urls_final.append(result.get("secure_url"))
        except Exception as e:
            print(f"Error uploading image to Cloudinary: {str(e)}")

    # 2. Parse JSON fields
    try:
        amenities_list = json.loads(amenities)
        safety_list = json.loads(safety_features)
    except json.JSONDecodeError:
        amenities_list, safety_list = [], []

    # 3. Construct the Home object
    new_home = {
        "host_id": ObjectId(user_id),
        "title": title,
        "description": description,
        "property_type": property_type,
        "price_per_night": float(price_per_night),
        "is_free": str(is_free).lower() == "true",
        "currency": "INR",
        "location": {
            "address_line": address,
            "city": city.upper(),
            "state": state.upper(),
            "country": country.upper(),
            "pincode": pincode,
            "lat": lat,
            "lng": lng
        },
        "city": city.upper(), # Redundant for easier searching
        "state": state.upper(),
        "max_guests": int(max_guests),
        "bedrooms": int(bedrooms),
        "beds": int(beds),
        "bathrooms": int(bathrooms),
        "amenities": amenities_list,
        "safety_features": safety_list,
        "images": image_urls_final,
        "is_active": True,
        "status": "pending",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    result = db.homes.insert_one(new_home)

    # 🚀 Promote user to host — but never downgrade elevated admin roles
    _current_user = db.users.find_one({"_id": ObjectId(user_id)}, {"role": 1})
    if _current_user:
        _current_role = _current_user.get("role", "guest")
        _protected_roles = {"super_admin", "admin", "sub_admin"}

        # Normalise: if role is a list, check each element for a protected role
        _is_protected = (
            _current_role in _protected_roles
            if isinstance(_current_role, str)
            else any(r in _protected_roles for r in _current_role)
        )

        if _is_protected:
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
        "message": "Home created successfully", 
        "id": str(result.inserted_id),
        "images": image_urls_final
    }


# ✅ Get Homes For Current Host
@router.get("/host/me")
def get_host_homes(user_id: str = Depends(get_current_user)):
    """Fetch all homes belonging to the authenticated host."""
    uid = ObjectId(user_id)
    query = {"$or": [{"host_id": uid}, {"host_id": user_id}]}
    
    homes = list(db.homes.find(query).sort("created_at", -1))
    print(f"DEBUG: Found {len(homes)} homes for host_id: {user_id}")
    
    for home in homes:
        _serialize_home(home)

    return homes


def _serialize_home(home: dict) -> dict:
    if not home: return home
    home["_id"] = str(home["_id"])
    home["id"] = str(home["_id"])
    home["host_id"] = str(home["host_id"])
    
    # Standardise images
    images = home.get("images", [])
    full_images = []
    for img in images:
        if isinstance(img, str):
            if img.startswith("http"):
                full_images.append(img)
            else:
                # Assuming local uploads if not http
                full_images.append(f"http://localhost:8000/uploads/{img}")
        elif isinstance(img, dict):
            url = img.get("url") or img.get("secure_url", "")
            if url: full_images.append(url)
            
    home["images"] = full_images
    home["image"] = full_images[0] if full_images else ""
    
    if "approved_by" in home:
        home["approved_by"] = [str(aid) for aid in home["approved_by"]]
    return home

# ✅ Get All Homes (Public) — supports filters + sort + city/state search
@router.get("/")
def get_homes(
    minPrice: float = 0,
    maxPrice: float = 1_000_000,
    propertyType: str = None,
    amenities: str = None,
    sort: str = None,
    location: str = None,
    city: str = None,
    state: str = None,
    guests: int = None,
):
    print(f"🔍 Search homes: city={city}, state={state}, location={location}, guests={guests}, price={minPrice}-{maxPrice}")
    try:
        db.command("ping")
        
        query = {
            "price_per_night": {"$gte": minPrice, "$lte": maxPrice},
            "status": "approved",
            "is_active": True,
        }

        # Explicit city/state params (from city-based search) — case-insensitive exact match
        if city:
            query["city"] = {"$regex": f"^{city}$", "$options": "i"}
        elif location:
            # Fallback: generic text search on city field (partial match, for the search bar location field)
            query["city"] = {"$regex": location, "$options": "i"}

        if state:
            query["state"] = {"$regex": f"^{state}$", "$options": "i"}

        if guests:
            query["max_guests"] = {"$gte": int(guests)}

        if propertyType:
            types = [t.strip() for t in propertyType.split(",") if t.strip()]
            if types:
                query["property_type"] = {"$in": types}

        if amenities:
            selected = [a.strip() for a in amenities.split(",") if a.strip()]
            if selected:
                query["amenities"] = {"$all": selected}

        sort_field = "created_at"
        sort_dir = -1
        if sort == "price_asc":
            sort_field, sort_dir = "price_per_night", 1
        elif sort == "price_desc":
            sort_field, sort_dir = "price_per_night", -1

        print(f"📋 MongoDB filter: {query}")

        homes_cursor = db.homes.find(query).sort(sort_field, sort_dir)
        homes = list(homes_cursor)
        
        result = []
        for home in homes:
            _serialize_home(home)
            # Add host verification status
            host = db.users.find_one({"_id": ObjectId(home["host_id"])}, {"is_verified": 1, "trust_score": 1})
            if host:
                home["host_verified"] = host.get("is_verified", False)
                home["host_trust_score"] = host.get("trust_score", 0)
            result.append(home)

        print(f"✅ Results found: {len(result)} homes")
        return result
    except Exception as e:
        print(f"❌ Error in get_homes: {str(e)}")
        return {"error": str(e)}

# 🛠️ Temporary Debug Route
@router.get("/debug/all-homes")
def debug_homes():
    try:
        homes = list(db.homes.find())
        for h in homes:
            h["_id"] = str(h["_id"])
            h["host_id"] = str(h.get("host_id", ""))
        return homes
    except Exception as e:
        return {"error": str(e)}


# ✅ Get Single Home
@router.get("/{home_id}")
def get_home(home_id: str):
    if not ObjectId.is_valid(home_id):
        raise HTTPException(status_code=400, detail="Invalid property ID format")

    home = db.homes.find_one({"_id": ObjectId(home_id)})

    if not home:
        raise HTTPException(status_code=404, detail="Home not found")

    # Populate host details
    host = db.users.find_one({"_id": home["host_id"]}, {"name": 1, "profile_image": 1, "profile_picture": 1, "is_verified": 1, "trust_score": 1})
    if host:
        home["host_details"] = {
            "name": host.get("name", "Unknown"),
            "profile_image": host.get("profile_image") or host.get("profile_picture", ""),
            "is_verified": host.get("is_verified", False),
            "trust_score": host.get("trust_score", 0)
        }

    return _serialize_home(home)

# ✅ Update Single Home
@router.put("/{home_id}")
def update_home(home_id: str, updated_data: dict, user_id: str = Depends(get_current_user)):
    if not ObjectId.is_valid(home_id):
        raise HTTPException(status_code=400, detail="Invalid property ID format")
    
    # Verify home exists and belongs to host
    home = db.homes.find_one({"_id": ObjectId(home_id)})
    if not home:
        raise HTTPException(status_code=404, detail="Home not found")
    
    if str(home["host_id"]) != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this property")

    # Update fields
    update_payload = {
        "title": updated_data.get("title", home.get("title")),
        "description": updated_data.get("description", home.get("description")),
        "price_per_night": updated_data.get("price_per_night", home.get("price_per_night")),
        "max_guests": updated_data.get("max_guests", home.get("max_guests")),
        "bedrooms": updated_data.get("bedrooms", home.get("bedrooms")),
        "beds": updated_data.get("beds", home.get("beds")),
        "bathrooms": updated_data.get("bathrooms", home.get("bathrooms")),
        "amenities": updated_data.get("amenities", home.get("amenities")),
        "rent_type": updated_data.get("rent_type", home.get("rent_type", "nightly")),
        "images": updated_data.get("images", home.get("images")),
        "caretaker_info": updated_data.get("caretaker_info", home.get("caretaker_info")),
        "updated_at": datetime.utcnow()
    }

    db.homes.update_one(
        {"_id": ObjectId(home_id)},
        {"$set": update_payload}
    )

    return {"message": "Home updated successfully"}


# ✅ Delete Home (Protected)
@router.delete("/{home_id}")
def delete_home(home_id: str, user_id: str = Depends(get_current_user)):
    if not ObjectId.is_valid(home_id):
        raise HTTPException(status_code=400, detail="Invalid property ID format")

    # Verify home exists and belongs to host
    home = db.homes.find_one({"_id": ObjectId(home_id)})
    if not home:
        raise HTTPException(status_code=404, detail="Home not found")

    if str(home["host_id"]) != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this property")

    # Delete the home
    db.homes.delete_one({"_id": ObjectId(home_id)})

    # Also clean up related bookings and reviews
    db.bookings.delete_many({"propertyId": home_id})
    db.reviews.delete_many({"propertyId": home_id})

    return {"message": "Home deleted successfully"}

# ✅ Patch Home (Partial Update)
@router.patch("/{listing_id}")
async def update_listing(
    listing_id: str,
    data: dict,
    current_user: str = Depends(get_current_user)
):
    try:
        from bson import ObjectId
        
        # Security: Remove sensitive fields from data
        data.pop("_id", None)
        data.pop("id", None)
        data.pop("host_id", None)
        
        data["updated_at"] = datetime.utcnow()
        
        # Try properties first (some data might be in this collection)
        result = db.properties.update_one(
            {"_id": ObjectId(listing_id)},
            {"$set": data}
        )
        
        if result.matched_count == 0:
            # Try homes collection
            db.homes.update_one(
                {"_id": ObjectId(listing_id)},
                {"$set": data}
            )
        
        return {"message": "Listing updated successfully"}
    except Exception as e:
        print(f"Error updating listing: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
