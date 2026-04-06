from fastapi import APIRouter, Depends, HTTPException
from app.core.database import db
from app.core.dependencies import get_current_user
from bson import ObjectId
from datetime import datetime

router = APIRouter()

@router.get("/search")
async def search_user_by_email(email: str):
    user = db.users.find_one({"email": email.lower().strip()})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "id": str(user["_id"]),
        "name": user.get("name", ""),
        "email": user.get("email", ""),
        "profile_image": user.get("profile_image", "")
    }


@router.get("/{user_id}/host-reviews")
async def get_host_reviews_for_guest(user_id: str):
    try:
        try:
            user_oid = ObjectId(user_id)
        except:
            user_oid = None
        
        id_variants = [user_id]
        if user_oid:
            id_variants.append(user_oid)
        
        # Find reviews where this user was the GUEST
        # (reviews written by hosts about guests)
        reviews = list(db.reviews.find({
            "$or": [
                {"guest_id": {"$in": id_variants}},
                {"reviewer_type": "host", "reviewed_user_id": {"$in": id_variants}},
                {"userId": {"$in": id_variants}, "reviewer_type": "host"} # Alternate schema
            ]
        }).sort("createdAt", -1).limit(10))
        
        result = []
        for r in reviews:
            # Get host info
            host_id = r.get("host_id") or r.get("reviewer_id")
            host = None
            if host_id:
                try:
                    host = db.users.find_one({"_id": ObjectId(host_id)})
                except:
                    host = db.users.find_one({"_id": host_id})
            
            # Get property info
            prop_id = r.get("propertyId") or r.get("property_id") or r.get("listing_id")
            prop = None
            if prop_id:
                try:
                    prop = db.homes.find_one({"_id": ObjectId(prop_id)})
                except:
                    prop = db.homes.find_one({"_id": prop_id})
            
            result.append({
                "id": str(r["_id"]),
                "host_name": host.get("name", "Host") if host else "Host",
                "property_name": prop.get("title", "Property") if prop else "Property",
                "rating": r.get("rating", 5),
                "comment": r.get("comment") or r.get("text", ""),
                "created_at": str(r.get("createdAt") or r.get("created_at") or ""),
            })
        
        # Get trust score
        user = db.users.find_one({"_id": user_oid} if user_oid else {"_id": user_id})
        trust_score = user.get("trust_score", 0) if user else 0
        
        return {
            "reviews": result,
            "total": len(result),
            "trust_score": trust_score,
        }
    except Exception as e:
        import traceback
        print(f"Error in host-reviews: {str(e)}")
        print(traceback.format_exc())
        return {"reviews": [], "total": 0, "trust_score": 0}
