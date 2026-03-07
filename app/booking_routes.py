from fastapi import APIRouter, Depends, HTTPException
from app.database import db
from app.dependencies import get_current_user
from datetime import datetime
from bson import ObjectId

router = APIRouter()


# ✅ CREATE BOOKING (POST /api/bookings)
@router.post("/")
def create_booking(data: dict, user_id: str = Depends(get_current_user)):

    # Support both "home_id" and "propertyId" from frontend payloads
    prop_id = data.get("propertyId") or data.get("home_id")
    
    home = db.homes.find_one({"_id": ObjectId(prop_id)})

    if not home:
        raise HTTPException(status_code=404, detail="Home not found")

    check_in = datetime.fromisoformat(data.get("checkIn", data.get("check_in")))
    check_out = datetime.fromisoformat(data.get("checkOut", data.get("check_out")))

    if check_in >= check_out:
        raise HTTPException(status_code=400, detail="Invalid dates")

    # 🔥 Prevent Double Booking
    existing_booking = db.bookings.find_one({
        "propertyId": ObjectId(prop_id),
        "bookingStatus": "confirmed",
        "$or": [
            {
                "checkIn": {"$lt": check_out},
                "checkOut": {"$gt": check_in}
            }
        ]
    })

    if existing_booking:
        raise HTTPException(
            status_code=400,
            detail="Home already booked for these dates"
        )

    nights = (check_out - check_in).days
    total_price = nights * home["price_per_night"]

    booking = {
        "userId": ObjectId(user_id),
        "propertyId": ObjectId(prop_id),
        "checkIn": check_in,
        "checkOut": check_out,
        "guests": int(data.get("guests", 1)),
        "totalPrice": float(total_price),
        "bookingStatus": "confirmed",
        "paymentStatus": "pending",
        "createdAt": datetime.utcnow()
    }

    result = db.bookings.insert_one(booking)

    return {
        "message": "Booking confirmed",
        "booking_id": str(result.inserted_id),
        "total_price": total_price
    }


# ✅ GET HOST ANALYTICS (GET /api/bookings/host/analytics)
@router.get("/host/analytics")
def get_host_analytics(user_id: str = Depends(get_current_user)):
    host_properties = list(db.homes.find({"host_id": ObjectId(user_id)}, {"_id": 1}))
    if not host_properties:
        return {"total_revenue": 0, "total_bookings": 0, "upcoming_bookings": 0, "total_guests": 0}

    property_ids = [p["_id"] for p in host_properties]
    
    # Get all confirmed bookings
    bookings = list(db.bookings.find({
        "propertyId": {"$in": property_ids},
        "bookingStatus": "confirmed"
    }))

    total_revenue = sum(b.get("totalPrice", 0) for b in bookings)
    total_bookings = len(bookings)
    total_guests = sum(b.get("guests", 1) for b in bookings)

    now = datetime.utcnow()
    upcoming_bookings = len([b for b in bookings if b["checkIn"] > now])

    return {
        "total_revenue": total_revenue,
        "total_bookings": total_bookings,
        "upcoming_bookings": upcoming_bookings,
        "total_guests": total_guests
    }

# ✅ GET HOST BOOKINGS (GET /api/bookings/host/me)
@router.get("/host/me")
def get_host_bookings(user_id: str = Depends(get_current_user)):
    # 1. Find all properties owned by this host
    host_properties = list(db.homes.find({"host_id": ObjectId(user_id)}, {"_id": 1, "title": 1, "images": 1}))
    
    if not host_properties:
        return []

    property_map = {str(p["_id"]): p for p in host_properties}
    property_ids = [p["_id"] for p in host_properties]

    # 2. Fetch bookings for these properties
    bookings = list(db.bookings.find({"propertyId": {"$in": property_ids}}).sort("checkIn", -1))

    # 3. Format response
    formatted_bookings = []
    for booking in bookings:
        prop = property_map.get(str(booking["propertyId"]))
        formatted_bookings.append({
            "_id": str(booking["_id"]),
            "property_title": prop["title"] if prop else "Unknown Property",
            "property_image": prop.get("images", [None])[0] if prop else None,
            "propertyId": str(booking["propertyId"]),
            "checkIn": booking["checkIn"].isoformat() if isinstance(booking.get("checkIn"), datetime) else booking.get("checkIn"),
            "checkOut": booking["checkOut"].isoformat() if isinstance(booking.get("checkOut"), datetime) else booking.get("checkOut"),
            "guests": booking.get("guests", 1),
            "totalPrice": booking.get("totalPrice", 0),
            "bookingStatus": booking.get("bookingStatus", "confirmed"),
            "createdAt": booking.get("createdAt").isoformat() if isinstance(booking.get("createdAt"), datetime) else booking.get("createdAt")
        })

    return formatted_bookings


# ✅ GET MY BOOKINGS (GET /api/bookings/user/)
@router.get("/user/")
def get_my_bookings(user_id: str = Depends(get_current_user)):

    bookings = list(db.bookings.find({"userId": ObjectId(user_id)}))

    for booking in bookings:
        booking["_id"] = str(booking["_id"])
        booking["userId"] = str(booking["userId"])
        booking["propertyId"] = str(booking["propertyId"])

    return bookings


# ✅ CANCEL BOOKING (DELETE /api/bookings/)
@router.delete("/")
def cancel_booking(booking_id: str, user_id: str = Depends(get_current_user)):

    booking = db.bookings.find_one({"_id": ObjectId(booking_id)})

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Only owner can cancel
    if str(booking["userId"]) != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if booking["bookingStatus"] == "cancelled":
        raise HTTPException(
            status_code=400,
            detail="Booking already cancelled"
        )

    db.bookings.update_one(
        {"_id": ObjectId(booking_id)},
        {
            "$set": {
                "bookingStatus": "cancelled"
            }
        }
    )

    return {"message": "Booking cancelled successfully"}