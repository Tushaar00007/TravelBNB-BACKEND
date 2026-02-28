from fastapi import APIRouter, Depends, HTTPException
from app.database import db
from app.dependencies import get_current_user
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
        "price_per_night": home["price_per_night"],
        "currency": "INR",
        "city": home["city"],
        "state": home["state"],
        "country": "India",
        "max_guests": home["max_guests"],
        "bedrooms": home["bedrooms"],
        "bathrooms": home["bathrooms"],
        "amenities": home.get("amenities", []),
        "images": home.get("images", []),
        "is_active": True,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    result = db.homes.insert_one(new_home)

    return {"message": "Home created", "home_id": str(result.inserted_id)}


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