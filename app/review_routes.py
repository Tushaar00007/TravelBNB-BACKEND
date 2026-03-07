from fastapi import APIRouter, Depends, HTTPException
from app.database import db
from app.dependencies import get_current_user
from datetime import datetime
from bson import ObjectId

router = APIRouter()

# 1️⃣ Create Review
@router.post("/")
def create_review(review: dict, user_id: str = Depends(get_current_user)):
    try:
        property_id = review.get("propertyId")
        rating = review.get("rating")
        comment = review.get("comment")

        if not property_id or not rating or not comment:
            raise HTTPException(status_code=400, detail="Missing required fields: propertyId, rating, comment")

        # Validate rating
        if not isinstance(rating, (int, float)) or not (1 <= rating <= 5):
            raise HTTPException(status_code=400, detail="Rating must be a number between 1 and 5")

        # Validate property exists
        try:
            property_obj_id = ObjectId(property_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid propertyId format")

        home = db.homes.find_one({"_id": property_obj_id})
        if not home:
            raise HTTPException(status_code=404, detail="Property not found")

        # Prevent duplicate reviews
        existing_review = db.reviews.find_one({
            "userId": ObjectId(user_id),
            "propertyId": property_obj_id
        })
        if existing_review:
            raise HTTPException(status_code=400, detail="You have already reviewed this property. Only one review per user per property is allowed.")

        # Save review
        new_review = {
            "userId": ObjectId(user_id),
            "propertyId": property_obj_id,
            "rating": float(rating),
            "comment": comment,
            "createdAt": datetime.utcnow()
        }

        result = db.reviews.insert_one(new_review)

        # Convert ObjectIds to strings for response
        new_review["_id"] = str(result.inserted_id)
        new_review["userId"] = str(new_review["userId"])
        new_review["propertyId"] = str(new_review["propertyId"])

        return {
            "success": True,
            "message": "Review created successfully",
            "review": new_review
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 2️⃣ Get Reviews for Property
@router.get("/{propertyId}")
def get_reviews(propertyId: str):
    try:
        try:
            property_obj_id = ObjectId(propertyId)
        except:
            raise HTTPException(status_code=400, detail="Invalid propertyId format")

        # Fetch all reviews for the property
        reviews_cursor = db.reviews.find({"propertyId": property_obj_id}).sort("createdAt", -1)
        reviews_list = list(reviews_cursor)

        if not reviews_list:
            return {
                "reviews": [],
                "averageRating": 0,
                "totalReviews": 0
            }

        # Calculate average and populate user details
        total_rating = 0
        populated_reviews = []

        for r in reviews_list:
            total_rating += r["rating"]
            
            # Fetch user details (name)
            user = db.users.find_one({"_id": r["userId"]}, {"name": 1, "profile_image": 1})
            user_info = None
            if user:
                user_info = {
                    "firstName": user.get("name", "Unknown"),
                    "lastName": "",
                    "profileImage": user.get("profile_image", "")
                }
            
            populated_reviews.append({
                "_id": str(r["_id"]),
                "userId": str(r["userId"]),
                "propertyId": str(r["propertyId"]),
                "rating": r["rating"],
                "comment": r["comment"],
                "createdAt": r["createdAt"],
                "user": user_info
            })

        avg_rating = round(total_rating / len(reviews_list), 1)

        return {
            "reviews": populated_reviews,
            "averageRating": avg_rating,
            "totalReviews": len(reviews_list)
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 3️⃣ Delete Review
@router.delete("/{reviewId}")
def delete_review(reviewId: str, user_id: str = Depends(get_current_user)):
    try:
        try:
            review_obj_id = ObjectId(reviewId)
        except:
            raise HTTPException(status_code=400, detail="Invalid reviewId format")

        # Find the review
        review = db.reviews.find_one({"_id": review_obj_id})
        
        if not review:
            raise HTTPException(status_code=404, detail="Review not found")

        # Check ownership (only the creator can delete it)
        if str(review["userId"]) != user_id:
            raise HTTPException(status_code=403, detail="You are not authorized to delete this review")

        # Delete it
        db.reviews.delete_one({"_id": review_obj_id})

        return {
            "success": True,
            "message": "Review deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ✅ Get Host Reviews (GET /api/reviews/host/me)
@router.get("/host/me")
def get_host_reviews(user_id: str = Depends(get_current_user)):
    try:
        host_properties = list(db.homes.find({"host_id": ObjectId(user_id)}, {"_id": 1, "title": 1, "images": 1}))
        if not host_properties:
            return []

        property_map = {str(p["_id"]): p for p in host_properties}
        property_ids = [p["_id"] for p in host_properties]

        reviews = list(db.reviews.find({"propertyId": {"$in": property_ids}}).sort("createdAt", -1))
        
        if not reviews:
            return []

        # Fetch user info for each review to display reviewer's name
        user_ids = list(set([r["userId"] for r in reviews]))
        users = list(db.users.find({"_id": {"$in": user_ids}}, {"_id": 1, "firstName": 1, "lastName": 1, "profile_picture": 1}))
        user_map = {str(u["_id"]): u for u in users}

        formatted_reviews = []
        for review in reviews:
            prop = property_map.get(str(review["propertyId"]))
            reviewer = user_map.get(str(review["userId"]))
            
            formatted_reviews.append({
                "_id": str(review["_id"]),
                "property_title": prop["title"] if prop else "Unknown Property",
                "rating": review.get("rating", 0),
                "comment": review.get("comment", ""),
                "createdAt": review.get("createdAt").isoformat() if isinstance(review.get("createdAt"), datetime) else review.get("createdAt"),
                "reviewer_name": f"{reviewer.get('firstName', '')} {reviewer.get('lastName', '')}".strip() if reviewer else "Guest",
                "reviewer_image": reviewer.get("profile_picture") if reviewer else None
            })

        return formatted_reviews
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
