from fastapi import APIRouter, Depends, HTTPException
from app.core.database import db
from app.core.dependencies import get_current_user
from datetime import datetime
from bson import ObjectId
from app.models.schemas import BookingRequestSchema, PaymentConfirmation

router = APIRouter()


# ✅ CREATE BOOKING (POST /api/bookings)
@router.post("/")
def create_booking(data: dict, user_id: str = Depends(get_current_user)):
    print(f"!!! POST /bookings/ RECEIVED DATA: {data} FROM USER: {user_id} !!!")

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

    # 💰 Record Transaction
    transaction = {
        "user_id": ObjectId(user_id),
        "amount": float(total_price),
        "type": "booking",
        "status": "success",
        "booking_id": result.inserted_id,
        "created_at": datetime.utcnow()
    }
    db.transactions.insert_one(transaction)

    return {
        "message": "Booking confirmed",
        "booking_id": str(result.inserted_id),
        "total_price": total_price
    }


# ✅ REQUEST BOOKING (POST /api/bookings/request)
@router.post("/request")
async def create_booking_request(request: BookingRequestSchema, db=Depends(lambda: db)):
    try:
        new_booking = {
            "propertyId": ObjectId(request.property_id),
            "hostId": ObjectId(request.host_id),
            "userId": ObjectId(request.guest_id) if request.guest_id else None,
            "checkIn": datetime.fromisoformat(request.check_in),
            "checkOut": datetime.fromisoformat(request.check_out),
            "guests": request.guests,
            "totalPrice": request.total_price,
            "bookingStatus": request.status if request.status else "pending",
            "paymentStatus": "pending",
            "createdAt": datetime.utcnow(),
        }
        
        result = db.bookings.insert_one(new_booking)
        booking_id = str(result.inserted_id)
        
        print(f"Booking request created: {booking_id}")
        
        return {
            "booking_request_id": booking_id,
            "status": "pending",
            "message": "Booking request created successfully"
        }
        
    except Exception as e:
        import traceback
        print(f"Error creating booking: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{booking_id}")
async def get_booking_by_id(booking_id: str, current_user: str = Depends(get_current_user)):
    """
    Fetch details for a specific booking/request by ID.
    Used by checkout page as 'Source of Truth'.
    """
    try:
        booking = db.bookings.find_one({"_id": ObjectId(booking_id)})
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
        
        # Format for frontend
        res = {
            "booking_request_id": str(booking["_id"]),
            "property_id": str(booking.get("propertyId", "")),
            "host_id": str(booking.get("hostId", "")),
            "user_id": str(booking.get("userId", "")),
            "check_in": booking["checkIn"].isoformat() if isinstance(booking.get("checkIn"), datetime) else booking.get("checkIn"),
            "check_out": booking["checkOut"].isoformat() if isinstance(booking.get("checkOut"), datetime) else booking.get("checkOut"),
            "guests": booking.get("guests", 1),
            "total_price": booking.get("totalPrice", 0),
            "booking_status": booking.get("bookingStatus", "pending")
        }

        # Optionally attach property info
        prop = db.homes.find_one({"_id": booking["propertyId"]})
        if prop:
            res["property_name"] = prop.get("title")
            res["property_image"] = prop.get("images", [None])[0]

        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ✅ APPROVE BOOKING (PATCH /api/bookings/{id}/approve)
@router.patch("/{booking_id}/approve")
def approve_booking(booking_id: str, user_id: str = Depends(get_current_user)):
    result = db.bookings.update_one(
        {"_id": ObjectId(booking_id)},
        {"$set": {"bookingStatus": "approved", "approved_at": datetime.utcnow()}}
    )

    # 🔄 Synchronize status in all related messages
    db.messages.update_many(
        {"booking_request_id": booking_id},
        {"$set": {"booking_status": "approved"}}
    )
    return {
        "booking_request_id": booking_id, 
        "booking_status": "approved", 
        "status": "approved",
        "message": "Booking approved"
    }


# ✅ DECLINE BOOKING (PATCH /api/bookings/{id}/decline)
@router.patch("/{booking_id}/decline")
def decline_booking(booking_id: str, user_id: str = Depends(get_current_user)):
    result = db.bookings.update_one(
        {"_id": ObjectId(booking_id)},
        {"$set": {"bookingStatus": "rejected", "rejected_at": datetime.utcnow()}}
    )

    # 🔄 Synchronize status in all related messages
    db.messages.update_many(
        {"booking_request_id": booking_id},
        {"$set": {"booking_status": "rejected"}}
    )
    return {
        "booking_request_id": booking_id, 
        "booking_status": "rejected", 
        "status": "rejected",
        "message": "Booking declined"
    }


# ✅ REJECT BOOKING (Alias for /decline)
@router.patch("/{booking_id}/reject")
def reject_booking(booking_id: str, user_id: str = Depends(get_current_user)):
    return decline_booking(booking_id, user_id)


    return {"booking_request_id": booking_id, "status": "confirmed"}


@router.post("/confirm-payment")
async def confirm_payment(
    payment: PaymentConfirmation,
    current_user: str = Depends(get_current_user)
):
    """
    Final confirmation of a booking after guest processes payment.
    """
    booking_id = payment.booking_request_id
    amount = payment.amount
    payment_method = payment.payment_method
    transaction_id = payment.transaction_id

    # Find the booking request
    booking = db.bookings.find_one({"_id": ObjectId(booking_id)})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking request not found")

    # Update booking status
    db.bookings.update_one(
        {"_id": ObjectId(booking_id)},
        {"$set": {
            "bookingStatus": "confirmed",
            "paymentStatus": "success",
            "paymentMethod": payment_method,
            "amountPaid": float(amount),
            "transactionId": transaction_id,
            "confirmedAt": datetime.utcnow()
        }}
    )

    # 🔄 Synchronize status in all related messages
    db.messages.update_many(
        {"booking_request_id": booking_id},
        {"$set": {"booking_status": "confirmed"}}
    )

    # Record Transaction
    transaction = {
        "user_id": ObjectId(current_user),
        "amount": float(amount),
        "type": "booking_payment",
        "status": "success",
        "booking_id": ObjectId(booking_id),
        "transaction_id": transaction_id,
        "created_at": datetime.utcnow()
    }
    db.transactions.insert_one(transaction)

    # 🚀 AUTO CREATE TRIP
    try:
        # Check if trip already exists
        if not db.trips.find_one({"booking_id": ObjectId(booking_id)}):
            # Fetch property title for naming
            prop = db.homes.find_one({"_id": ObjectId(booking.get("propertyId"))}, {"title": 1})
            prop_title = prop.get("title", "Stay") if prop else "Stay"
            
            trip_doc = {
                "title": f"Trip to {prop_title}",
                "booking_id": ObjectId(booking_id),
                "property_id": ObjectId(booking.get("propertyId")),
                "userId": ObjectId(current_user), # Explicit userId for queries
                "owner_id": ObjectId(current_user),
                "members": [ObjectId(current_user)],
                "start_date": booking.get("checkIn"),
                "end_date": booking.get("checkOut"),
                "created_at": datetime.utcnow(),
            }
            db.trips.insert_one(trip_doc)
            print(f"!!! SUCCESS: Trip '{trip_doc['title']}' automatically created for booking {booking_id} !!!")
        else:
            print(f"!!! INFO: Trip for booking {booking_id} already exists, skipping creation. !!!")
    except Exception as trip_err:
        print(f"!!! ERROR: Failed to auto-create trip: {trip_err} !!!")
        import traceback
        print(traceback.format_exc())

    return {
        "success": True, 
        "booking_id": booking_id,
        "message": "Payment confirmed and trip created",
        "transaction_id": transaction_id
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
    uid = ObjectId(user_id)
    host_query = {"$or": [{"host_id": uid}, {"host_id": user_id}, {"hostId": uid}, {"hostId": user_id}]}

    # Collect properties across all listing types
    property_map = {}
    for coll_name in ["homes", "crashpads_listings", "travel_buddies", "buddy_requests"]:
        coll = getattr(db, coll_name, None)
        if coll is None:
            continue
        for p in coll.find(host_query, {"_id": 1, "title": 1, "images": 1, "city": 1}):
            property_map[str(p["_id"])] = {
                "title": p.get("title", "Untitled"),
                "image": (p.get("images") or [None])[0],
                "city": p.get("city", ""),
            }

    if not property_map:
        return []

    property_ids = [ObjectId(pid) for pid in property_map.keys()]
    
    # 1. Fetch from 'bookings' collection
    bookings_raw = list(db.bookings.find({
        "$or": [
            {"propertyId": {"$in": property_ids}},
            {"hostId": uid},
            {"hostId": user_id},
        ]
    }))

    # 2. Fetch from 'requests' collection (used by Crashpads and other request-based flows)
    requests_raw = list(db.requests.find({
        "$or": [
            {"crashpad_id": {"$in": property_ids}},
            {"host_id": uid},
            {"host_id": user_id},
        ]
    }))

    all_raw = []
    # Normalize bookings
    for b in bookings_raw:
        b["_source"] = "bookings"
        all_raw.append(b)
    
    # Normalize requests
    for r in requests_raw:
        r["_source"] = "requests"
        # Map fields to match booking schema
        r["propertyId"] = r.get("crashpad_id")
        r["userId"] = r.get("guest_id")
        r["checkIn"] = r.get("check_in")
        r["checkOut"] = r.get("check_out")
        r["bookingStatus"] = r.get("status", "pending")
        r["totalPrice"] = r.get("total_price", 0)
        all_raw.append(r)

    # Sort all by check-in date
    all_raw.sort(key=lambda x: x.get("checkIn") or x.get("check_in") or datetime.min, reverse=True)

    formatted = []
    for b in all_raw:
        prop = property_map.get(str(b.get("propertyId", "")), {})

        # Resolve guest name
        guest_name = "Guest"
        guest_id = b.get("userId") or b.get("user_id") or b.get("guestId") or b.get("guest_id")
        if guest_id:
            try:
                guest = db.users.find_one(
                    {"_id": ObjectId(guest_id) if not isinstance(guest_id, ObjectId) else guest_id},
                    {"name": 1, "firstName": 1, "email": 1}
                )
                if guest:
                    guest_name = guest.get("name") or guest.get("firstName") or guest.get("email", "Guest").split("@")[0]
            except Exception:
                pass

        check_in = b.get("checkIn") or b.get("check_in")
        check_out = b.get("checkOut") or b.get("check_out")
        created_at = b.get("createdAt") or b.get("created_at")

        formatted.append({
            "_id": str(b["_id"]),
            "id": str(b["_id"]),
            "property_title": prop.get("title", "Unknown Property"),
            "property_image": prop.get("image"),
            "propertyId": str(b.get("propertyId", "")),
            "property_id": str(b.get("propertyId", "")),
            "checkIn": check_in.isoformat() if isinstance(check_in, datetime) else check_in,
            "checkOut": check_out.isoformat() if isinstance(check_out, datetime) else check_out,
            "check_in": check_in.isoformat() if isinstance(check_in, datetime) else check_in,
            "check_out": check_out.isoformat() if isinstance(check_out, datetime) else check_out,
            "guests": b.get("guests", 1),
            "totalPrice": b.get("totalPrice") or b.get("total_price", 0),
            "total_price": b.get("totalPrice") or b.get("total_price", 0),
            "bookingStatus": b.get("bookingStatus") or b.get("status", "pending"),
            "status": b.get("bookingStatus") or b.get("status", "pending"),
            "guest_name": guest_name,
            "guestName": guest_name,
            "createdAt": created_at.isoformat() if isinstance(created_at, datetime) else created_at,
            "created_at": created_at.isoformat() if isinstance(created_at, datetime) else created_at,
        })

    return formatted


# ✅ GET MY BOOKINGS (GET /api/bookings/user/)
@router.get("/user/")
def get_my_bookings(user_id: str = Depends(get_current_user)):
    """Get all bookings for the current user enriched with property info"""
    try:
        print(f"=== FETCHING BOOKINGS FOR USER: {user_id} ===")
        # Fetch all bookings for this user
        bookings_cursor = db.bookings.find({"userId": ObjectId(user_id)}).sort("checkIn", -1)
        bookings = list(bookings_cursor)
        print(f"Found {len(bookings)} bookings in database")

        # Enrich each booking with property info
        for booking in bookings:
            try:
                # 🚀 STRINGIFY ALL OBJECTIDS FIRST (to prevent JSON serialization errors)
                for key, value in booking.items():
                    if isinstance(value, ObjectId):
                        booking[key] = str(value)

                # Fetch property details (Homes collection)
                if booking.get("propertyId"):
                    property_data = db.homes.find_one({"_id": ObjectId(booking["propertyId"])})
                    if property_data:
                        booking["homeDetails"] = {
                            "title": property_data.get("title", "Unknown Title"),
                            "images": property_data.get("images", []),
                            "city": property_data.get("city", "Unknown City"),
                            "address": property_data.get("address", "")
                        }
                    else:
                        booking["homeDetails"] = None
                else:
                    booking["homeDetails"] = None

                # Format dates for JSON
                for date_key in ["checkIn", "checkOut", "createdAt"]:
                    if date_key in booking and isinstance(booking[date_key], datetime):
                        booking[date_key] = booking[date_key].isoformat()

            except Exception as inner_e:
                print(f"!!! Error enriching booking {booking.get('_id')}: {inner_e} !!!")
                booking["homeDetails"] = None

        return {"bookings": bookings, "error": None}
    except Exception as e:
        print(f"!!! TOP-LEVEL Error in get_my_bookings: {e} !!!")
        import traceback
        print(traceback.format_exc())
        return {"bookings": [], "error": str(e)}


# ✅ GET UNIFIED BOOKINGS (GET /api/bookings/user/all)
@router.get("/user/all")
def get_my_bookings_unified(user_id: str = Depends(get_current_user)):
    """
    Return ALL bookings for the current user across all listing types:
    - Home bookings (bookings collection)
    - Crashpad stay requests (requests collection)
    - Travel buddy applications (buddy_applications collection)
    Each item is normalized into a common shape with a 'kind' field for the frontend.
    """
    uid = ObjectId(user_id)
    unified = []

    # 1. HOME BOOKINGS
    try:
        home_bookings = list(db.bookings.find({"userId": uid}).sort("checkIn", -1))
        for b in home_bookings:
            prop = None
            if b.get("propertyId"):
                try:
                    prop = db.homes.find_one({"_id": b["propertyId"]})
                except Exception:
                    pass

            check_in = b.get("checkIn")
            check_out = b.get("checkOut")
            created_at = b.get("createdAt")

            unified.append({
                "_id": str(b["_id"]),
                "id": str(b["_id"]),
                "kind": "home",
                "title": prop.get("title", "Home Booking") if prop else "Home Booking",
                "image": (prop.get("images") or [None])[0] if prop else None,
                "city": prop.get("city", "") if prop else "",
                "address": prop.get("address", "") if prop else "",
                "checkIn": check_in.isoformat() if isinstance(check_in, datetime) else check_in,
                "checkOut": check_out.isoformat() if isinstance(check_out, datetime) else check_out,
                "guests": b.get("guests", 1),
                "totalPrice": b.get("totalPrice", 0),
                "bookingStatus": b.get("bookingStatus", "pending"),
                "createdAt": created_at.isoformat() if isinstance(created_at, datetime) else created_at,
                "homeDetails": {
                    "title": prop.get("title", "Unknown") if prop else "Unknown",
                    "images": prop.get("images", []) if prop else [],
                    "city": prop.get("city", "") if prop else "",
                    "address": prop.get("address", "") if prop else "",
                },
            })
    except Exception as e:
        print(f"Error fetching home bookings: {e}")

    # 2. CRASHPAD REQUESTS
    try:
        crash_reqs = list(db.requests.find({"guest_id": uid}).sort("created_at", -1))
        for r in crash_reqs:
            pad = None
            if r.get("crashpad_id"):
                try:
                    pad = db.crashpads_listings.find_one({"_id": r["crashpad_id"]})
                except Exception:
                    pass

            created_at = r.get("created_at")

            # Normalize crashpad status to match home bookingStatus values
            status_map = {"pending": "pending", "approved": "approved", "rejected": "rejected", "confirmed": "confirmed", "cancelled": "cancelled"}
            normalized_status = status_map.get(r.get("status", "pending"), "pending")

            unified.append({
                "_id": str(r["_id"]),
                "id": str(r["_id"]),
                "kind": "crashpad",
                "title": pad.get("title", "Crashpad Request") if pad else "Crashpad Request",
                "image": (pad.get("images") or [None])[0] if pad else None,
                "city": (pad.get("location", {}) or {}).get("city", "") if pad else "",
                "address": (pad.get("location", {}) or {}).get("address_line", "") if pad else "",
                "checkIn": r.get("check_in", ""),
                "checkOut": r.get("check_out", ""),
                "guests": r.get("guests", 1),
                "totalPrice": r.get("total_price", 0),
                "bookingStatus": normalized_status,
                "message": r.get("message", ""),
                "createdAt": created_at.isoformat() if isinstance(created_at, datetime) else created_at,
                "homeDetails": {
                    "title": pad.get("title", "Crashpad") if pad else "Crashpad",
                    "images": pad.get("images", []) if pad else [],
                    "city": (pad.get("location", {}) or {}).get("city", "") if pad else "",
                    "address": (pad.get("location", {}) or {}).get("address_line", "") if pad else "",
                },
            })
    except Exception as e:
        print(f"Error fetching crashpad requests: {e}")

    # 3. TRAVEL BUDDY APPLICATIONS
    try:
        buddy_apps = list(db.buddy_applications.find({"user_id": uid}).sort("created_at", -1))
        for app in buddy_apps:
            trip = None
            if app.get("request_id"):
                try:
                    trip_id = app["request_id"] if isinstance(app["request_id"], ObjectId) else ObjectId(app["request_id"])
                    trip = db.buddy_requests.find_one({"_id": trip_id})
                except Exception:
                    pass

            created_at = app.get("created_at")

            status_map = {"pending": "pending", "accepted": "confirmed", "rejected": "rejected", "cancelled": "cancelled"}
            normalized_status = status_map.get(app.get("status", "pending"), "pending")

            unified.append({
                "_id": str(app["_id"]),
                "id": str(app["_id"]),
                "kind": "buddy",
                "title": f"Trip to {trip.get('destination', 'Unknown')}" if trip else "Travel Buddy Application",
                "image": (trip.get("images") or [None])[0] if trip else None,
                "city": trip.get("destination", "") if trip else "",
                "address": trip.get("destination", "") if trip else "",
                "checkIn": trip.get("start_date", "") if trip else "",
                "checkOut": trip.get("end_date", "") if trip else "",
                "guests": 1,
                "totalPrice": trip.get("budget", 0) if trip else 0,
                "bookingStatus": normalized_status,
                "createdAt": created_at.isoformat() if isinstance(created_at, datetime) else created_at,
                "homeDetails": {
                    "title": f"Trip to {trip.get('destination', 'Unknown')}" if trip else "Travel Buddy",
                    "images": trip.get("images", []) if trip else [],
                    "city": trip.get("destination", "") if trip else "",
                    "address": trip.get("description", "") if trip else "",
                },
            })
    except Exception as e:
        print(f"Error fetching buddy applications: {e}")

    # Sort all by check-in date (closest first)
    unified.sort(key=lambda x: x.get("checkIn") or "", reverse=False)

    return {"bookings": unified, "error": None}


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
