from fastapi import APIRouter, Depends, HTTPException, Query
from app.core.database import db
from app.core.dependencies import require_role
from app.utils.security import hash_password
from app.services.email_service import send_email
from app.utils.email_template import promotional_email_template
from datetime import datetime, timedelta
from bson import ObjectId
import time

router = APIRouter()

SUPER = ["super_admin"]
SUPER_SUB = ["super_admin", "sub_admin"]
SUPER_ADMIN = ["super_admin", "admin"]
ALL_ADMINS = ["super_admin", "sub_admin", "admin"]

# ─── helpers ──────────────────────────────────────────────────

# ─── Create Admin ─────────────────────────────────────────────
@router.post("/create")
def create_admin(data: dict, user=Depends(require_role(SUPER))):
    """Creates a new admin user. Restricted to super_admin."""
    name     = data.get("name")
    email    = data.get("email")
    password = data.get("password")
    role     = data.get("role")

    if not all([name, email, password, role]):
        raise HTTPException(status_code=400, detail="Missing required fields")

    if role not in ["admin", "sub_admin", "super_admin"]:
        raise HTTPException(status_code=400, detail="Invalid admin role")

    if db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already exists")

    new_admin = {
        "name":       name,
        "email":      email,
        "password":   hash_password(password),
        "role":       role,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "is_verified": True
    }

    result = db.users.insert_one(new_admin)
    _log(user, f"Created new {role}: {email}", entity=str(result.inserted_id))

    return {"message": f"{role.replace('_', ' ').capitalize()} created successfully"}


def _log(user: dict, action: str, entity: str = ""):
    db.admin_logs.insert_one({
        "admin_id":   user["id"],
        "admin_name": user.get("name", ""),
        "action":     action,
        "entity":     entity,
        "timestamp":  datetime.utcnow(),
    })

def _str_id(doc: dict) -> dict:
    if not doc: return doc
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    
    # Handle all common ID fields (snake_case and camelCase)
    id_fields = (
        "host_id", "user_id", "property_id", 
        "hostId", "userId", "propertyId", "home_id"
    )
    for k in id_fields:
        if k in doc and doc[k]:
            doc[k] = str(doc[k])
    
    # Handle nested dates if any (converting to ISO strings for safety)
    for k, v in doc.items():
        if isinstance(v, datetime):
            doc[k] = v.isoformat() + "Z"

    if "approved_by" in doc and isinstance(doc["approved_by"], list):
        doc["approved_by"] = [str(aid) for aid in doc["approved_by"]]

    return doc


# ─── Dashboard Stats ──────────────────────────────────────────
@router.get("/stats")
@router.get("/analytics")
def get_stats(user=Depends(require_role(SUPER))):
    total_users    = db.users.count_documents({})
    total_homes    = db.homes.count_documents({})
    total_bookings = db.bookings.count_documents({})

    # Revenue = sum of total_price across all bookings
    pipeline = [{"$group": {"_id": None, "revenue": {"$sum": "$total_price"}}}]
    rev_result = list(db.bookings.aggregate(pipeline))
    revenue = rev_result[0]["revenue"] if rev_result else 0

    # Monthly breakdown for charts (last 6 months — approximate via created_at)
    user_monthly = []
    booking_monthly = []
    revenue_monthly = []

    for month_offset in range(5, -1, -1):
        # Rough monthly buckets using string labels
        label_parts = []
        import calendar
        from datetime import timedelta
        now = datetime.utcnow()
        year = now.year
        month = now.month - month_offset
        while month <= 0:
            month += 12
            year -= 1
        month_label = f"{calendar.month_abbr[month]} {str(year)[2:]}"

        start = datetime(year, month, 1)
        end_month = month + 1 if month < 12 else 1
        end_year = year if month < 12 else year + 1
        end = datetime(end_year, end_month, 1)

        u_count = db.users.count_documents({"created_at": {"$gte": start, "$lt": end}})
        b_docs = list(db.bookings.find({"created_at": {"$gte": start, "$lt": end}}))
        b_count = len(b_docs)
        b_rev = sum(d.get("total_price", 0) for d in b_docs)

        user_monthly.append({"month": month_label, "users": u_count})
        booking_monthly.append({"month": month_label, "bookings": b_count})
        revenue_monthly.append({"month": month_label, "revenue": round(b_rev)})

    return {
        "total_users":    total_users,
        "total_homes":    total_homes,
        "total_bookings": total_bookings,
        "total_revenue":  round(revenue),
        "user_monthly":     user_monthly,
        "booking_monthly":  booking_monthly,
        "revenue_monthly":  revenue_monthly,
    }


# ─── Users ────────────────────────────────────────────────────
@router.get("/users")
def get_users(
    page:   int = Query(1, ge=1),
    limit:  int = Query(10, ge=1, le=100),
    search: str = Query(""),
    role:   str = Query(""),
    verified: str = Query(""), # "true" | "false" | ""
    user=Depends(require_role(SUPER)),
):
    query = {}
    if search:
        query["$or"] = [
            {"name":  {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
        ]
    if role:
        query["role"] = role
    
    if verified == "true":
        query["is_email_verified"] = True
    elif verified == "false":
        query["is_email_verified"] = False

    skip  = (page - 1) * limit
    total = db.users.count_documents(query)
    users = list(db.users.find(query, {"password": 0}).skip(skip).limit(limit))

    for u in users:
        u["_id"] = str(u["_id"])

    return {"total": total, "page": page, "limit": limit, "data": users}


@router.get("/users-compact")
def get_users_compact(
    city: str = Query(None),
    isActive: bool = Query(None),
    recentBookings: bool = Query(None),
    user=Depends(require_role(SUPER))
):
    """Returns a filtered list of users (names/emails only) for campaigns."""
    query = {}
    
    if city:
        # Check both address.city and location.city for compatibility
        query["$or"] = [
            {"address.city": {"$regex": city, "$options": "i"}},
            {"location.city": {"$regex": city, "$options": "i"}}
        ]
        
    if isActive:
        query["is_email_verified"] = True
        
    if recentBookings:
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        # Find user IDs who have a confirmed booking in last 30 days
        recent_user_ids = db.bookings.distinct("userId", {"createdAt": {"$gte": thirty_days_ago}})
        query["_id"] = {"$in": recent_user_ids}
        
    users = list(db.users.find(query, {"name": 1, "email": 1, "address.city": 1}))
    for u in users:
        u["_id"] = str(u["_id"])
    return users


@router.put("/users/{user_id}/role")
def update_user_role(user_id: str, payload: dict, user=Depends(require_role(SUPER))):
    new_role = payload.get("role")
    if new_role not in ["guest", "admin", "sub_admin", "super_admin", "host"]:
        raise HTTPException(status_code=400, detail="Invalid role")

    result = db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"role": new_role}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    _log(user, f"Changed role → {new_role}", entity=user_id)
    return {"message": f"Role updated to {new_role}"}


@router.delete("/users/{user_id}")
def delete_user(user_id: str, user=Depends(require_role(SUPER))):
    result = db.users.delete_one({"_id": ObjectId(user_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    return {"message": "User deleted"}


# ─── Admin Management ─────────────────────────────────────────
@router.get("/admins")
def list_admins(user=Depends(require_role(SUPER))):
    """List all users with administrative roles."""
    admins = list(db.users.find({
        "role": {"$in": ["admin", "sub_admin", "super_admin"]}
    }))
    
    return [{
        "_id": str(a["_id"]),
        "name": a.get("name", ""),
        "email": a.get("email", ""),
        "role": a.get("role", ""),
        "created_at": str(a.get("created_at", a.get("createdAt", "")))
    } for a in admins]


@router.delete("/admins/{admin_id}")
def delete_admin(admin_id: str, user=Depends(require_role(SUPER))):
    """Delete an administrative account with safety checks."""
    if not ObjectId.is_valid(admin_id):
        raise HTTPException(status_code=400, detail="Invalid admin ID format")
        
    target_oid = ObjectId(admin_id)
    
    # 1. Cannot delete yourself
    if str(user["id"]) == admin_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    
    # 2. Find the target
    target = db.users.find_one({"_id": target_oid})
    if not target:
        raise HTTPException(status_code=404, detail="Admin not found")
    
    # 3. Cannot delete other super admins
    if target.get("role") == "super_admin":
        raise HTTPException(status_code=400, detail="Cannot delete a super_admin account")
    
    result = db.users.delete_one({"_id": target_oid})
    _log(user, f"Deleted admin user: {target.get('email')}", entity=admin_id)
    
    return {"success": True, "deleted_count": result.deleted_count}


@router.put("/users/{user_id}/verify")
def verify_user(user_id: str, payload: dict, user=Depends(require_role(SUPER_ADMIN))):
    """
    Toggles the identity verification status of a user.
    Grants +40 trust points on first-time verification.
    """
    is_verified = payload.get("is_verified", True)
    
    db_user = db.users.find_one({"_id": ObjectId(user_id)})
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    # If verifying for the first time, boost trust score
    trust_boost = 0
    if is_verified and not db_user.get("is_verified"):
        trust_boost = 40

    db.users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "is_verified": is_verified,
                "trust_score": db_user.get("trust_score", 0) + trust_boost,
                "updated_at": datetime.utcnow()
            }
        }
    )

    status_str = "verified" if is_verified else "unverified"
    _log(user, f"Marked user as {status_str}", entity=user_id)
    
    return {
        "message": f"User is now {status_str}",
        "new_trust_score": db_user.get("trust_score", 0) + trust_boost
    }


# ─── Listings ─────────────────────────────────────────────────
@router.get("/listings")
def get_listings(
    page:   int = Query(1, ge=1),
    limit:  int = Query(10, ge=1, le=100),
    search: str = Query(""),
    status: str = Query(""),
    user=Depends(require_role(SUPER_SUB)),
):
    query = {}
    if status:
        query["status"] = status
    if search:
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"city":  {"$regex": search, "$options": "i"}},
        ]

    skip  = (page - 1) * limit
    total = db.homes.count_documents(query)
    homes = list(db.homes.find(query).skip(skip).limit(limit))

    return {"total": total, "page": page, "limit": limit, "data": [_str_id(h) for h in homes]}


@router.post("/listings/{id}/approve")
def approve_listing(id: str, user=Depends(require_role(ALL_ADMINS))):
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid property ID format")
    prop = db.homes.find_one({"_id": ObjectId(id)})
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    # Add admin to approved_by if not already there
    if user["id"] not in [str(aid) for aid in prop.get("approved_by", [])]:
        db.homes.update_one(
            {"_id": ObjectId(id)},
            {"$addToSet": {"approved_by": ObjectId(user["id"])}}
        )
    
    # Check if we have 1 approval
    updated_prop = db.homes.find_one({"_id": ObjectId(id)})
    if len(updated_prop.get("approved_by", [])) >= 1:
        db.homes.update_one(
            {"_id": ObjectId(id)},
            {"$set": {"status": "approved"}}
        )
        _log(user, f"Property approved (Final)", entity=id)
    else:
        _log(user, f"Recorded approval for property", entity=id)

    return {"message": "Approval recorded", "count": len(updated_prop.get("approved_by", []))}


@router.post("/listings/{id}/reject")
def reject_listing(id: str, user=Depends(require_role(ALL_ADMINS))):
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid property ID format")
    result = db.homes.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"status": "rejected", "approved_by": []}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Property not found")

    _log(user, "Rejected property", entity=id)
    return {"message": "Listing rejected"}


@router.post("/listings/{id}/flag")
def flag_listing(id: str, user=Depends(require_role(ALL_ADMINS))):
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid property ID format")
    result = db.homes.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"status": "flagged"}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Property not found")

    _log(user, "Flagged property", entity=id)
    return {"message": "Listing flagged"}


@router.delete("/listings/{id}")
def delete_listing(id: str, user=Depends(require_role(ALL_ADMINS))):
    """
    Permanently delete a home or property listing. Restricted to admin roles.
    """
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid property ID format")
    
    oid = ObjectId(id)
    deleted = False
    
    # 1. Try deleting from properties collection
    result = db.properties.delete_one({"_id": oid})
    if result.deleted_count > 0:
        deleted = True
        print(f"Deleted from properties: {id}")
    
    # 2. Try deleting from homes collection
    if not deleted:
        result = db.homes.delete_one({"_id": oid})
        if result.deleted_count > 0:
            deleted = True
            print(f"Deleted from homes: {id}")
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Listing not found")
    
    _log(user, "Deleted listing (Admin)", entity=id)
    return {"message": "Listing deleted successfully"}


# ─── Crashpads ────────────────────────────────────────────────
@router.get("/crashpads")
def get_crashpads(
    page:   int = Query(1, ge=1),
    limit:  int = Query(10, ge=1, le=100),
    status: str = Query(""),
    user=Depends(require_role(SUPER_SUB)),
):
    query = {}
    if status:
        query["status"] = status
    
    skip = (page - 1) * limit
    total = db.crashpads_listings.count_documents(query)
    pads = list(db.crashpads_listings.find(query).skip(skip).limit(limit))
    
    # Flatten city for frontend compatibility (nested in new collection)
    for p in pads:
        if "location" in p and "city" in p["location"]:
            p["city"] = p["location"]["city"]

    return {"total": total, "page": page, "limit": limit, "data": [_str_id(p) for p in pads]}


@router.post("/crashpads/{id}/approve")
def approve_crashpad(id: str, user=Depends(require_role(ALL_ADMINS))):
    db.crashpads_listings.update_one({"_id": ObjectId(id)}, {"$set": {"status": "approved"}})
    _log(user, "Approved crashpad", entity=id)
    return {"message": "Crashpad approved"}


@router.post("/crashpads/{id}/reject")
def reject_crashpad(id: str, user=Depends(require_role(ALL_ADMINS))):
    db.crashpads_listings.update_one({"_id": ObjectId(id)}, {"$set": {"status": "rejected"}})
    _log(user, "Rejected crashpad", entity=id)
    return {"message": "Crashpad rejected"}


@router.delete("/crashpads/{id}")
def delete_crashpad_admin(id: str, user=Depends(require_role(ALL_ADMINS))):
    """
    Permanently delete a crashpad listing. Restricted to admin roles.
    """
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid crashpad ID format")
    
    result = db.crashpads_listings.delete_one({"_id": ObjectId(id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Crashpad not found")
    
    _log(user, "Deleted crashpad (Admin)", entity=id)
    return {"message": "Crashpad deleted successfully"}


# ─── Travel Buddy ─────────────────────────────────────────────
@router.get("/travel-buddies")
def get_travel_buddies(
    page:   int = Query(1, ge=1),
    limit:  int = Query(10, ge=1, le=100),
    user=Depends(require_role(SUPER_SUB)),
):
    skip = (page - 1) * limit
    total = db.travel_buddies.count_documents({})
    buddies = list(db.travel_buddies.find({}).skip(skip).limit(limit))
    
    return {"total": total, "page": page, "limit": limit, "data": [_str_id(b) for b in buddies]}


@router.post("/travel-buddies/{id}/ban")
def ban_travel_buddy(id: str, user=Depends(require_role(SUPER_ADMIN))):
    # This might involve banning the user associated with the profile
    profile = db.travel_buddies.find_one({"_id": ObjectId(id)})
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    user_id = profile.get("user_id")
    db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"status": "banned"}})
    _log(user, "Banned travel buddy user", entity=str(user_id))
    return {"message": "User banned"}


@router.delete("/travel-buddy/{id}")
def delete_travel_buddy_admin(id: str, admin=Depends(require_role(ALL_ADMINS))):
    """
    Permanently delete a travel buddy listing. Restricted to admin roles.
    """
    try:
        if not ObjectId.is_valid(id):
            raise HTTPException(status_code=400, detail="Invalid profile ID format")
            
        result = db.travel_buddies.delete_one({"_id": ObjectId(id)})
        
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Travel buddy profile not found")
            
        _log(admin, "Permanently deleted travel buddy profile", entity=id)
        return {"message": "Deleted successfully"}
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── New Travel Buddy Moderation (Singular Route Pattern) ───
@router.patch("/travelbuddy/{id}/approve")
def approve_travel_buddy(id: str, admin=Depends(require_role(ALL_ADMINS))):
    try:
        if not ObjectId.is_valid(id):
            raise HTTPException(status_code=400, detail="Invalid profile ID format")
            
        result = db.travel_buddies.update_one(
            {"_id": ObjectId(id)},
            {"$set": {"status": "approved", "updated_at": datetime.utcnow()}}
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Travel buddy profile not found")
            
        _log(admin, "Approved travel buddy profile", entity=id)
        return {"message": "User approved"}
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/travelbuddy/{id}/reject")
def reject_travel_buddy(id: str, admin=Depends(require_role(ALL_ADMINS))):
    try:
        if not ObjectId.is_valid(id):
            raise HTTPException(status_code=400, detail="Invalid profile ID format")
            
        result = db.travel_buddies.update_one(
            {"_id": ObjectId(id)},
            {"$set": {"status": "rejected", "updated_at": datetime.utcnow()}}
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Travel buddy profile not found")
            
        _log(admin, "Rejected travel buddy profile", entity=id)
        return {"message": "User rejected"}
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/travelbuddy/{id}/ban")
def ban_travel_buddy_singular(id: str, admin=Depends(require_role(SUPER_ADMIN))):
    try:
        if not ObjectId.is_valid(id):
            raise HTTPException(status_code=400, detail="Invalid profile ID format")
            
        profile = db.travel_buddies.find_one({"_id": ObjectId(id)})
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
            
        user_id = profile.get("user_id")
        
        # 1. Update Profile Status
        db.travel_buddies.update_one(
            {"_id": ObjectId(id)},
            {"$set": {"status": "banned", "updated_at": datetime.utcnow()}}
        )
        
        # 2. Update User Account Status
        if user_id:
            db.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"status": "banned", "updated_at": datetime.utcnow()}}
            )
            
        _log(admin, "Banned travel buddy user and profile", entity=id)
        return {"message": "User banned"}
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Bookings ─────────────────────────────────────────────────
@router.get("/bookings")
def get_bookings(
    page:   int = Query(1, ge=1),
    limit:  int = Query(10, ge=1, le=100),
    status: str = Query(""),
    user=Depends(require_role(SUPER_ADMIN)),
):
    query = {}
    if status:
        query["status"] = status

    skip  = (page - 1) * limit
    total = db.bookings.count_documents(query)
    bookings = list(db.bookings.find(query).skip(skip).limit(limit))

    return {"total": total, "page": page, "limit": limit, "data": [_str_id(b) for b in bookings]}


# ─── Payments & Transactions ──────────────────────────────────
@router.get("/transactions")
def get_transactions(
    page:   int = Query(1, ge=1),
    limit:  int = Query(20, ge=1, le=100),
    user=Depends(require_role(SUPER_ADMIN)),
):
    skip = (page - 1) * limit
    total = db.transactions.count_documents({})
    txs = list(db.transactions.find({}).sort("created_at", -1).skip(skip).limit(limit))
    
    for tx in txs:
        tx["_id"] = str(tx["_id"])
        tx["user_id"] = str(tx["user_id"])
        if "booking_id" in tx:
            tx["booking_id"] = str(tx["booking_id"])
        tx["created_at"] = tx["created_at"].isoformat() + "Z"
        
        # Optionally enrich with user name
        u = db.users.find_one({"_id": ObjectId(tx["user_id"])}, {"name": 1})
        tx["user_name"] = u.get("name") if u else "Unknown"

    return {"total": total, "page": page, "limit": limit, "data": txs}


# ─── Support & Tickets ────────────────────────────────────────
@router.get("/tickets")
def get_tickets(status: str = Query("open"), user=Depends(require_role(ALL_ADMINS))):
    query = {"status": status} if status else {}
    tickets = list(db.tickets.find(query).sort("created_at", -1))
    
    for t in tickets:
        t["_id"] = str(t["_id"])
        t["user_id"] = str(t["user_id"])
        u = db.users.find_one({"_id": ObjectId(t["user_id"])}, {"name": 1, "email": 1})
        t["user_name"] = u.get("name") if u else "Deleted User"

    return tickets


@router.post("/tickets/respond")
def respond_ticket(payload: dict, user=Depends(require_role(ALL_ADMINS))):
    ticket_id = payload.get("id")
    response_text = payload.get("response")
    
    db.tickets.update_one(
        {"_id": ObjectId(ticket_id)},
        {"$set": {
            "status": "resolved",
            "response": response_text,
            "resolved_by": user["id"],
            "resolved_at": datetime.utcnow()
        }}
    )
    _log(user, "Responded to ticket", entity=ticket_id)
    return {"message": "Ticket resolved"}


# ─── Notifications ────────────────────────────────────────────
@router.post("/notify")
def send_notification(payload: dict, user=Depends(require_role(SUPER_ADMIN))):
    target = payload.get("target", "all") # all | host | user
    title = payload.get("title")
    message = payload.get("message")
    
    notif = {
        "title": title,
        "message": message,
        "target": target,
        "created_at": datetime.utcnow(),
        "sent_by": user["id"]
    }
    db.notifications.insert_one(notif)
    _log(user, f"Sent global notification: {title}")
    return {"message": "Notification sent successfully"}


# ─── Coupons ──────────────────────────────────────────────────
@router.get("/coupons")
def list_coupons(user=Depends(require_role(SUPER_SUB))):
    coupons = list(db.coupons.find())
    return [_str_id(c) for c in coupons]


@router.post("/coupons")
def create_coupon(payload: dict, user=Depends(require_role(SUPER_SUB))):
    code     = payload.get("code", "").upper().strip()
    discount = payload.get("discount")
    expires  = payload.get("expires_at")  # optional ISO string

    if not code or not discount:
        raise HTTPException(status_code=400, detail="code and discount are required")
    if db.coupons.find_one({"code": code}):
        raise HTTPException(status_code=409, detail="Coupon code already exists")

    doc = {
        "code":       code,
        "discount":   int(discount),
        "created_by": user["name"],
        "created_at": datetime.utcnow(),
        "expires_at": expires,
        "active":     True,
    }
    db.coupons.insert_one(doc)
    _log(user, f"Created coupon {code}", entity=code)
    return {"message": f"Coupon {code} created"}


@router.delete("/coupons/{code}")
def delete_coupon(code: str, user=Depends(require_role(SUPER_SUB))):
    result = db.coupons.delete_one({"code": code.upper()})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Coupon not found")

    _log(user, f"Deleted coupon {code.upper()}", entity=code.upper())
    return {"message": f"Coupon {code.upper()} deleted"}


# ─── Activity Logs ────────────────────────────────────────────
@router.get("/logs")
def get_logs(
    page:  int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user=Depends(require_role(SUPER)),
):
    skip  = (page - 1) * limit
    total = db.admin_logs.count_documents({})
    logs  = list(db.admin_logs.find().sort("timestamp", -1).skip(skip).limit(limit))

    for log in logs:
        log["_id"] = str(log["_id"])
        log["timestamp"] = log["timestamp"].isoformat() + "Z"

    return {"total": total, "page": page, "limit": limit, "data": logs}


# ═══════════════════════════════════════════════════════════════
# ⚠️  DEV-ONLY — DELETE THIS ENTIRE BLOCK BEFORE GOING LIVE  ⚠️
# ═══════════════════════════════════════════════════════════════
import os as _os
from app.core.dependencies import get_current_user as _get_current_user

@router.post("/dev/make-super-admin")
def dev_make_super_admin(current_user_id: str = Depends(_get_current_user)):
    """
    DEV-ONLY: promotes the currently logged-in user to super_admin.
    Guarded by DEBUG=true in .env — remove before production.
    """
    if not _os.getenv("DEBUG", "false").lower() in ("true", "1", "yes"):
        raise HTTPException(status_code=403, detail="Only available in DEBUG mode")

    result = db.users.update_one(
        {"_id": ObjectId(current_user_id)},
        {"$set": {"role": "super_admin"}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    return {"message": "You are now super_admin. Log out and log back in."}

@router.post("/dev/create-super-admin")
def dev_create_super_admin(data: dict):
    """
    DEV-ONLY: creates a brand new super_admin account.
    Does NOT require being logged in.
    Guarded by DEBUG=true in .env.
    """
    if not _os.getenv("DEBUG", "false").lower() in ("true", "1", "yes"):
        raise HTTPException(status_code=403, detail="Only available in DEBUG mode")

    name     = data.get("name")
    email    = data.get("email")
    password = data.get("password")

    if not all([name, email, password]):
        raise HTTPException(status_code=400, detail="name, email, and password are required")

    if db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="User already exists")

    new_admin = {
        "name":       name,
        "email":      email,
        "password":   hash_password(password),
        "role":       "super_admin",
        "created_at": datetime.utcnow(),
        "is_verified": True
    }

    db.users.insert_one(new_admin)
    return {"message": f"Super Admin {email} created! You can now log in."}
# ═══════════════════════════════════════════════════════════════
# ─── Bulk Upload ──────────────────────────────────────────────
@router.post("/bulk-upload")
def bulk_upload(payload: dict, user=Depends(require_role(SUPER_SUB))):
    """
    Robust bulk upload system for listings.
    Supports homes (listing-home), crashpads, and travel-buddy.
    """
    collection_type = payload.get("collectionType")
    dataRows = payload.get("data", [])
    
    if not collection_type or not dataRows:
        raise HTTPException(status_code=400, detail="Missing collectionType or dataRows")
    
    success_count = 0
    failure_count = 0
    error_rows = []
    
    now = datetime.utcnow()
    admin_id = ObjectId(user["id"])
    
    for i, row in enumerate(dataRows):
        try:
            # 1. Homes (listing-home)
            if collection_type == "listing-home":
                location_str = row.get("location", "")
                loc_parts = [p.strip() for p in location_str.split(",")]
                city = loc_parts[-3] if len(loc_parts) >= 3 else "Unknown"
                state = loc_parts[-2] if len(loc_parts) >= 2 else "Unknown"
                
                doc = {
                    "host_id": admin_id, # Default to admin as host for bulk upload
                    "title": row.get("title", "Untitled Home"),
                    "description": row.get("description", ""),
                    "property_type": row.get("property_type", "Apartment"),
                    "price_per_night": float(row.get("price", 0)),
                    "currency": "INR",
                    "location": {
                        "address_line": location_str,
                        "city": city.upper(),
                        "state": state.upper(),
                        "country": "INDIA",
                        "lat": float(row.get("lat")) if row.get("lat") else None,
                        "lng": float(row.get("lng")) if row.get("lng") else None,
                    },
                    "city": city.upper(),
                    "state": state.upper(),
                    "max_guests": int(row.get("max_guests", 1)),
                    "bedrooms": int(row.get("bedrooms", 1)),
                    "beds": int(row.get("beds", 1)),
                    "bathrooms": int(row.get("bathrooms", 1)),
                    "amenities": [a.strip() for a in str(row.get("amenities", "")).split(",") if a.strip()],
                    "images": [img.strip() for img in str(row.get("images", "")).split(",") if img.strip()],
                    "status": "approved",
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now
                }
                db.homes.insert_one(doc)
                
            # 2. Crashpads
            elif collection_type == "crashpads":
                location_str = row.get("location", "")
                loc_parts = [p.strip() for p in location_str.split(",")]
                city = loc_parts[-2] if len(loc_parts) >= 2 else "Unknown"
                state = loc_parts[-1] if len(loc_parts) >= 1 else "Unknown"
                
                desc = row.get("description", "")
                if row.get("nearbyTransport"):
                    desc += f"\n\nNearby Transport: {row.get('nearbyTransport')}"
                
                doc = {
                    "host_id": admin_id,
                    "title": row.get("name", "Untitled Crashpad"),
                    "description": desc,
                    "price_per_night": float(row.get("pricePerNight", 0)),
                    "location": {
                        "city": city.upper(),
                        "state": state.upper(),
                        "lat": float(row.get("lat")) if row.get("lat") else None,
                        "lng": float(row.get("lng")) if row.get("lng") else None,
                    },
                    "images": [img.strip() for img in str(row.get("images", "")).split(",") if img.strip()],
                    "preferences": [f.strip() for f in str(row.get("facilities", "")).split(",") if f.strip()],
                    "stay_type": "Hostel",
                    "host_bio": "Professional managed crashpad listing.",
                    "status": "approved",
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now
                }
                db.crashpads_listings.insert_one(doc)
                
            # 3. Travel Buddy
            elif collection_type == "travel-buddy":
                dates_str = row.get("travelDates", "")
                start_date, end_date = "2026-01-01", "2026-01-07"
                if " to " in dates_str:
                    parts = dates_str.split(" to ")
                    start_date = parts[0].strip()
                    end_date = parts[1].strip()
                
                doc = {
                    "user_id": admin_id,
                    "destination": row.get("destination", "New Delhi"),
                    "start_date": start_date,
                    "end_date": end_date,
                    "budget": float(row.get("budget", 0)),
                    "interests": [i.strip() for i in str(row.get("interests", "")).split(",") if i.strip()],
                    "description": row.get("bio", ""),
                    "created_at": now
                }
                db.travel_buddies.insert_one(doc)
            
            else:
                raise ValueError(f"Invalid collection type: {collection_type}")
                
            success_count += 1
            
        except Exception as e:
            failure_count += 1
            error_rows.append({
                "row_index": i,
                "data": row,
                "error": str(e)
            })
            
    _log(user, f"Bulk uploaded {success_count} listings to {collection_type} ({failure_count} failures)")
    
    return {
        "successCount": success_count,
        "failureCount": failure_count,
        "errorRows": error_rows
    }


# ─── Promotions & Messaging ───────────────────────────────────
@router.post("/send-promotions")
def send_promotions(payload: dict, user=Depends(require_role(SUPER))):
    """
    Safely sends batch-based promotional emails to users.
    Includes deduplication, logging, and error tracking.
    """
    subject = payload.get("subject")
    message = payload.get("message")
    recipients = payload.get("users", []) # Expects list of objects with an 'email' field
    cta_link = payload.get("ctaLink")

    if not subject or not message or not recipients:
        raise HTTPException(status_code=400, detail="Subject, message, and at least one recipient are required")

    # 1. Deduplicate & Clean
    raw_emails = [r.get("email", "").strip().lower() for r in recipients]
    unique_emails = list(dict.fromkeys([e for e in raw_emails if "@" in e])) # preserves order
    total_count = len(unique_emails)

    if total_count > 1000:
        raise HTTPException(status_code=400, detail="Max 1000 emails per campaign for safety.")

    # 2. Preparation
    success_count = 0
    failure_count = 0
    failed_emails = []
    html_body = promotional_email_template(message, cta_link)

    # 3. Batch Sending (50 per batch)
    BATCH_SIZE = 50
    for i in range(0, total_count, BATCH_SIZE):
        batch = unique_emails[i : i + BATCH_SIZE]
        
        for email in batch:
            try:
                # send_email from email_service
                res = send_email(email, subject, html_body)
                if res:
                    success_count += 1
                else:
                    failure_count += 1
                    failed_emails.append(email)
            except Exception as e:
                print(f"Error sending promotion to {email}: {e}")
                failure_count += 1
                failed_emails.append(email)
            
            # Small delay after each send to respect 2 req/sec limit
            time.sleep(0.55)

    # 4. Campaign Logging
    campaign = {
        "admin_id":  ObjectId(user["id"]),
        "subject":   subject,
        "message":   message,
        "total":     total_count,
        "sent":      success_count,
        "failed":    failure_count,
        "created_at": datetime.utcnow()
    }
    db.email_campaigns.insert_one(campaign)
    _log(user, f"Dispatched promotional campaign: {subject}", entity=str(total_count))

    return {
        "success": True,
        "total": total_count,
        "sent": success_count,
        "failed": failure_count,
        "failedEmails": failed_emails
    }
