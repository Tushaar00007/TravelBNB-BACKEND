from fastapi import APIRouter, Depends, HTTPException
from app.core.database import db
from app.core.dependencies import get_current_user
from datetime import datetime
from bson import ObjectId

router = APIRouter()

# ✅ Create Home (Protected)
@router.post("/")
def create_home(home: dict, user_id: str = Depends(get_current_user)):

    new_home = {
        "host_id": ObjectId(user_id),
        "title": home["title"],
        "description": home["description"],
        "property_type": home.get("property_type", "Apartment"),
        "price_per_night": home["price_per_night"],
        "currency": "INR",
        "city": home["city"],
        "state": home["state"],
        "country": "India",
        "location": home.get("location", {"lat": 20.5937, "lng": 78.9629}),
        "max_guests": home["max_guests"],
        "bedrooms": home["bedrooms"],
        "beds": home.get("beds", 1),
        "bathrooms": home["bathrooms"],
        "amenities": home.get("amenities", []),
        "images": home.get("images", []),
        "caretaker_info": home.get("caretaker_info", ""),
        "is_active": True,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    result = db.homes.insert_one(new_home)

    # 🚀 Upgrade the user's role to include "host"
    user_data = db.users.find_one({"_id": ObjectId(user_id)})
    if user_data:
        current_role = user_data.get("role", "guest")
        if isinstance(current_role, str):
            # If it's a string like "guest", convert to an array of both
            if "host" not in current_role:
                db.users.update_one(
                    {"_id": ObjectId(user_id)},
                    {"$set": {"role": ["guest", "host"]}}
                )
        elif isinstance(current_role, list):
            # If it's already an array, add "host" to it safely
            db.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$addToSet": {"role": "host"}}
            )

    return {"message": "Home created", "home_id": str(result.inserted_id)}


# ✅ Get Homes For Current Host
@router.get("/host/me")
def get_host_homes(user_id: str = Depends(get_current_user)):
    homes = list(db.homes.find({"host_id": ObjectId(user_id)}))
    
    for home in homes:
        home["_id"] = str(home["_id"])
        home["host_id"] = str(home["host_id"])

    return homes


# ✅ Get All Homes (Public)
@router.get("/")
def get_homes():
    homes = list(db.homes.find())

    for home in homes:
        home["_id"] = str(home["_id"])
        home["host_id"] = str(home["host_id"])

    return homes


# ✅ Get Single Home
@router.get("/{home_id}")
def get_home(home_id: str):

    home = db.homes.find_one({"_id": ObjectId(home_id)})

    if not home:
        raise HTTPException(status_code=404, detail="Home not found")

    home["_id"] = str(home["_id"])
    home["host_id"] = str(home["host_id"])

    return home

# ✅ Update Single Home
@router.put("/{home_id}")
def update_home(home_id: str, updated_data: dict, user_id: str = Depends(get_current_user)):
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
