from fastapi import APIRouter, Depends, HTTPException
from app.core.database import db
from app.core.dependencies import get_current_user
from bson import ObjectId
from typing import List, Dict

router = APIRouter()

def serialize_doc(doc):
    if not doc: return None
    doc["id"] = str(doc.pop("_id"))
    if "host_id" in doc:
        doc["host_id"] = str(doc["host_id"])
    if "user_id" in doc:
        doc["user_id"] = str(doc["user_id"])
    return doc

@router.get("/dashboard/me")
async def get_host_dashboard(user_id: str = Depends(get_current_user)):
    """Aggregate all listing types for the current host/user."""
    
    uid = ObjectId(user_id)
    
    # 1. Fetch Homes
    homes = list(db.homes.find({"host_id": uid}).sort("created_at", -1))
    
    # 2. Fetch Crashpads
    crashpads = list(db.crashpads_listings.find({"host_id": uid}).sort("created_at", -1))
    
    # 3. Fetch Travel Buddy listings
    travel_buddies = list(db.travel_buddies.find({"user_id": uid}).sort("created_at", -1))
    
    # Aggregated Results
    return {
        "homes": [serialize_doc(h) for h in homes],
        "crashpads": [serialize_doc(c) for c in crashpads],
        "travel_buddies": [serialize_doc(t) for t in travel_buddies],
        "is_host": len(homes) > 0 or len(crashpads) > 0 or len(travel_buddies) > 0,
        "counts": {
            "homes": len(homes),
            "crashpads": len(crashpads),
            "travel_buddies": len(travel_buddies)
        }
    }
