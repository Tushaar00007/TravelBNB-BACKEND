from fastapi import APIRouter, Depends, HTTPException
from app.core.database import db
from app.core.dependencies import get_current_user
from bson import ObjectId
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import traceback
from pydantic import BaseModel

router = APIRouter()

class ReviewReplyRequest(BaseModel):
    reply: str

class BlockDateRequest(BaseModel):
    dates: List[str]
    listing_id: Optional[str] = None

def json_serialize(obj):
    """
    Recursively convert MongoDB types (ObjectId, datetime) into JSON-serializable types.
    """
    if isinstance(obj, list):
        return [json_serialize(item) for item in obj]
    if isinstance(obj, dict):
        return {k: json_serialize(v) for k, v in obj.items()}
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj

def serialize_doc(doc):
    """
    Backward compatibility wrapper for json_serialize that also ensures 
    _id is converted to id.
    """
    if not doc: return None
    res = json_serialize(doc)
    if "_id" in doc:
        res["id"] = str(doc["_id"])
    return res

@router.get("/dashboard/me")
async def get_host_dashboard(
    current_user: str = Depends(get_current_user),
):
    try:
        user_id_str = str(current_user)
        try:
            user_oid = ObjectId(user_id_str)
        except:
            user_oid = None
        
        def make_query(field="host_id"):
            variants = [user_id_str]
            if user_oid:
                variants.append(user_oid)
            return {field: {"$in": variants}}
        
        host_query = make_query("host_id")

        print("DEBUG user_id_str:", user_id_str)
        print("DEBUG user_oid:", user_oid)
        print("DEBUG host_query:", host_query)

        homes = list(db.properties.find(host_query).sort("created_at", -1)) + \
                list(db.homes.find(host_query).sort("created_at", -1))
        crashpads = list(db.crashpads_listings.find(host_query).sort("created_at", -1))
        travel_buddies = list(db.buddy_requests.find(
            make_query("user_id")
        ).sort("created_at", -1))

        print("DEBUG homes count:", len(homes))
        print("DEBUG crashpads count:", len(crashpads))
        print("DEBUG travel_buddies count:", len(travel_buddies))

        # Sample docs to inspect field structure
        sample = db.buddy_requests.find_one({})
        print("DEBUG buddy_requests sample doc:", sample)

        sample_crashpad = db.crashpads_listings.find_one({})
        print("DEBUG crashpads_listings sample doc:", sample_crashpad)

        for b in travel_buddies:
            b.setdefault("title", f"Travel Buddy: {b.get('destination', b.get('city', 'Trip'))}")
            b.setdefault("status", "approved")
            b.setdefault("price_per_night", 0)
            b.setdefault("city", b.get("destination", ""))
            b.setdefault("is_active", True)

        return {
            "homes": [serialize_doc(h) for h in homes],
            "crashpads": [serialize_doc(c) for c in crashpads],
            "travel_buddies": [serialize_doc(b) for b in travel_buddies]
        }
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/overview")
async def get_host_overview(
    current_user: str = Depends(get_current_user),
):
    try:
        user_id_str = str(current_user)
        try:
            user_oid = ObjectId(user_id_str)
        except:
            user_oid = None
        
        id_variants = [user_id_str]
        if user_oid:
            id_variants.append(user_oid)
        
        all_listing_ids = []
        for col in ['properties', 'homes', 'crashpads_listings']:
            listings = list(db[col].find({"host_id": {"$in": id_variants}}, {"_id": 1}))
            all_listing_ids.extend([l["_id"] for l in listings])
        
        all_variants = all_listing_ids + [str(l) for l in all_listing_ids]
        
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0)
        
        confirmed = list(db.bookings.find({
            "$or": [{"property_id": {"$in": all_variants}}, {"listing_id": {"$in": all_variants}}],
            "status": "confirmed",
            "created_at": {"$gte": month_start}
        }))
        total_earnings = sum([b.get("total_price", 0) for b in confirmed])
        
        today_str = now.strftime("%Y-%m-%d")
        upcoming = list(db.bookings.find({
            "$or": [{"property_id": {"$in": all_variants}}, {"listing_id": {"$in": all_variants}}],
            "check_in": {"$gte": today_str},
            "status": {"$in": ["confirmed", "approved"]}
        }).sort("check_in", 1).limit(5))
        
        reviews = list(db.reviews.find({
            "$or": [{"listing_id": {"$in": all_variants}}, {"property_id": {"$in": all_variants}}]
        }))
        avg_rating = sum([r.get("rating", 0) for r in reviews]) / len(reviews) if reviews else 0
        
        monthly = []
        for i in range(5, -1, -1):
            ms = (now.replace(day=1) - timedelta(days=i*30))
            me = (ms + timedelta(days=32)).replace(day=1)
            mb = list(db.bookings.find({
                "$or": [{"property_id": {"$in": all_variants}}, {"listing_id": {"$in": all_variants}}],
                "status": "confirmed",
                "created_at": {"$gte": ms, "$lt": me}
            }))
            monthly.append({
                "month": ms.strftime("%b"),
                "earnings": sum([b.get("total_price", 0) for b in mb])
            })
            
        upcoming_list = []
        for b in upcoming:
            guest_id = str(b.get("guest_id", ""))
            guest = db.users.find_one({"_id": ObjectId(guest_id)}) if guest_id else None
            upcoming_list.append({
                "id": str(b["_id"]),
                "guest_name": guest.get("name", "Guest") if guest else "Guest",
                "property_id": str(b.get("property_id", b.get("listing_id", ""))),
                "check_in": str(b.get("check_in", "")),
                "check_out": str(b.get("check_out", "")),
                "total_price": b.get("total_price", 0),
                "status": b.get("status", "pending"),
            })
            
        return {
            "total_earnings": total_earnings,
            "upcoming_count": len(upcoming),
            "occupancy_rate": min(round((len(confirmed)/30)*100), 100),
            "avg_rating": round(avg_rating, 1),
            "total_reviews": len(reviews),
            "monthly_earnings": monthly,
            "upcoming_bookings_list": upcoming_list,
        }
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/bookings")
async def get_host_bookings(
    current_user: str = Depends(get_current_user),
):
    try:
        user_id_str = str(current_user)
        try:
            user_oid = ObjectId(user_id_str)
        except:
            user_oid = None
        
        id_variants = [user_id_str]
        if user_oid:
            id_variants.append(user_oid)
            
        all_listings = []
        for col in ['properties', 'homes', 'crashpads_listings']:
            listings = list(db[col].find({"host_id": {"$in": id_variants}}, {"_id": 1, "title": 1}))
            all_listings.extend(listings)
            
        listing_map = {str(l["_id"]): l.get("title", "Property") for l in all_listings}
        all_id_variants = [l["_id"] for l in all_listings] + [str(l["_id"]) for l in all_listings]
        
        bookings = list(db.bookings.find({
            "$or": [{"property_id": {"$in": all_id_variants}}, {"listing_id": {"$in": all_id_variants}}]
        }).sort("check_in", 1))
        
        result = []
        for b in bookings:
            guest_id = str(b.get("guest_id", ""))
            guest = db.users.find_one({"_id": ObjectId(guest_id)}) if guest_id else None
            prop_id = str(b.get("property_id", b.get("listing_id", "")))
            result.append({
                "id": str(b["_id"]),
                "property_id": prop_id,
                "property_title": listing_map.get(prop_id, "Property"),
                "guest_name": guest.get("name", "Guest") if guest else "Guest",
                "guest_email": guest.get("email", "") if guest else "",
                "check_in": str(b.get("check_in", "")),
                "check_out": str(b.get("check_out", "")),
                "total_price": b.get("total_price", 0),
                "status": b.get("status", "pending"),
                "guests": b.get("guests", 1),
            })
            
        blocked = list(db.blocked_dates.find({
            "host_id": {"$in": id_variants}
        }))
        blocked_dates = [b.get("date", "") for b in blocked if b.get("date")]
            
        return {
            "bookings": result,
            "blocked_dates": blocked_dates,
            "listings": [{"id": str(l["_id"]), "title": l.get("title", "Property")} for l in all_listings]
        }
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/bookings/{booking_id}/approve")
async def approve_booking(booking_id: str, current_user: str = Depends(get_current_user)):
    db.bookings.update_one({"_id": ObjectId(booking_id)}, {"$set": {"status": "confirmed"}})
    return {"message": "Booking confirmed"}

@router.patch("/bookings/{booking_id}/decline")
async def decline_booking(booking_id: str, current_user: str = Depends(get_current_user)):
    db.bookings.update_one({"_id": ObjectId(booking_id)}, {"$set": {"status": "rejected"}})
    return {"message": "Booking rejected"}

@router.get("/bookings/{booking_id}")
async def get_booking_details(
  booking_id: str,
  current_user: str = Depends(get_current_user)
):
  try:
    from bson import ObjectId
    
    booking = db.bookings.find_one({"_id": ObjectId(booking_id)})
    if not booking:
      raise HTTPException(status_code=404, detail="Booking not found")
    
    # Get guest info
    guest_id = str(booking.get("guest_id", ""))
    guest = None
    try:
      guest = db.users.find_one({"_id": ObjectId(guest_id)})
    except:
      pass
    
    # Get property info
    prop_id = str(booking.get("property_id", booking.get("listing_id", "")))
    property_info = None
    for col in ['properties', 'homes', 'crashpads_listings']:
      try:
        property_info = db[col].find_one({"_id": ObjectId(prop_id)})
        if property_info:
          break
      except:
        pass
    
    # Get guest's previous bookings count
    guest_bookings_count = 0
    if guest_id:
      try:
        guest_bookings_count = db.bookings.count_documents({
          "guest_id": ObjectId(guest_id),
          "status": "confirmed"
        })
      except:
        pass
    
    # Get guest's reviews count
    guest_reviews = 0
    if guest_id:
      try:
        guest_reviews = db.reviews.count_documents({
          "reviewer_id": ObjectId(guest_id)
        })
      except:
        pass
    
    def get_img(img):
      if not img: return None
      if isinstance(img, dict): return img.get('secure_url') or img.get('url')
      if isinstance(img, str) and img.startswith('http'): return img
      return None
    
    property_images = []
    if property_info:
      raw = property_info.get('images', [])
      property_images = [get_img(i) for i in raw if get_img(i)]
    
    return {
      "id": str(booking["_id"]),
      "status": booking.get("status", "pending"),
      "check_in": str(booking.get("check_in", "")),
      "check_out": str(booking.get("check_out", "")),
      "nights": booking.get("nights", 1),
      "guests": booking.get("guests", 1),
      "total_price": booking.get("total_price", 0),
      "created_at": str(booking.get("created_at", "")),
      "payment_status": booking.get("payment_status", "pending"),
      "special_requests": booking.get("special_requests", ""),
      
      "guest": {
        "id": guest_id,
        "name": guest.get("name", "Guest") if guest else "Guest",
        "email": guest.get("email", "") if guest else "",
        "phone": guest.get("phone", "") if guest else "",
        "profile_image": guest.get("profile_image", "") if guest else "",
        "is_verified": guest.get("is_verified", False) if guest else False,
        "trust_score": guest.get("trust_score", 0) if guest else 0,
        "member_since": str(guest.get("created_at", ""))[:10] if guest else "",
        "total_trips": guest_bookings_count,
        "total_reviews": guest_reviews,
        "address": guest.get("address", "") if guest else "",
        "id_verified": bool(guest.get("id_document")) if guest else False,
      },
      
      "property": {
        "id": prop_id,
        "title": property_info.get("title", "") if property_info else "",
        "city": property_info.get("city", "") if property_info else "",
        "state": property_info.get("state", "") if property_info else "",
        "images": property_images,
        "price_per_night": property_info.get("price_per_night", 0) 
          if property_info else 0,
        "property_type": property_info.get("property_type", "") 
          if property_info else "",
        "amenities": property_info.get("amenities", []) 
          if property_info else [],
      }
    }
    
  except HTTPException:
    raise
  except Exception as e:
    import traceback
    print(traceback.format_exc())
    raise HTTPException(status_code=500, detail=str(e))

@router.post("/calendar/block")
async def block_calendar_dates(body: BlockDateRequest, current_user: str = Depends(get_current_user)):
    try:
        user_id_str = str(current_user)
        for date_str in body.dates:
            db.blocked_dates.update_one(
                {"host_id": user_id_str, "date": date_str},
                {"$set": {
                    "host_id": user_id_str,
                    "date": date_str,
                    "listing_id": body.listing_id,
                    "created_at": datetime.utcnow()
                }},
                upsert=True
            )
        return {"status": "success", "message": f"Blocked {len(body.dates)} date(s)"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/calendar/block")
async def unblock_calendar_dates(body: BlockDateRequest, current_user: str = Depends(get_current_user)):
    try:
        user_id_str = str(current_user)
        result = db.blocked_dates.delete_many({
            "host_id": user_id_str,
            "date": {"$in": body.dates}
        })
        return {"status": "success", "message": f"Unblocked {result.deleted_count} date(s)"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/calendar/blocked")
async def get_blocked_calendar_dates(current_user: str = Depends(get_current_user)):
    try:
        user_id_str = str(current_user)
        try:
            user_oid = ObjectId(user_id_str)
        except:
            user_oid = None
            
        id_variants = [user_id_str]
        if user_oid: id_variants.append(user_oid)
            
        blocked = list(db.blocked_dates.find({
            "host_id": {"$in": id_variants}
        }))
        blocked_dates = [b.get("date", "") for b in blocked if b.get("date")]
        return {"status": "success", "blocked_dates": blocked_dates}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/earnings")
async def get_host_earnings(period: str = "month", current_user: str = Depends(get_current_user)):
    try:
        user_id_str = str(current_user)
        try:
            user_oid = ObjectId(user_id_str)
        except:
            user_oid = None
        
        id_variants = [user_id_str]
        if user_oid: id_variants.append(user_oid)
            
        all_listing_ids = []
        for col in ['properties', 'homes', 'crashpads_listings']:
            listings = list(db[col].find({"host_id": {"$in": id_variants}}, {"_id": 1}))
            all_listing_ids.extend([l["_id"] for l in listings])
        
        all_variants = all_listing_ids + [str(l) for l in all_listing_ids]
        
        now = datetime.utcnow()
        if period == "day": start_date = now.replace(hour=0, minute=0, second=0)
        elif period == "week": start_date = now - timedelta(days=7)
        elif period == "year": start_date = now.replace(month=1, day=1, hour=0, minute=0)
        else: start_date = now.replace(day=1, hour=0, minute=0)
        
        bookings = list(db.bookings.find({
            "$or": [{"property_id": {"$in": all_variants}}, {"listing_id": {"$in": all_variants}}],
            "status": "confirmed",
            "created_at": {"$gte": start_date}
        }))
        
        gross = sum([b.get("total_price", 0) for b in bookings])
        fee = round(gross * 0.10, 2)
        net = gross - fee
        
        pending_bookings = list(db.bookings.find({
            "$or": [{"property_id": {"$in": all_variants}}, {"listing_id": {"$in": all_variants}}],
            "status": "approved"
        }))
        pending = sum([b.get("total_price", 0) for b in pending_bookings])
        
        monthly_trend = []
        for i in range(5, -1, -1):
            ms = (now.replace(day=1) - timedelta(days=i*30))
            me = (ms + timedelta(days=32)).replace(day=1)
            mb = list(db.bookings.find({
                "$or": [{"property_id": {"$in": all_variants}}, {"listing_id": {"$in": all_variants}}],
                "status": "confirmed",
                "created_at": {"$gte": ms, "$lt": me}
            }))
            monthly_trend.append({"month": ms.strftime("%b"), "earnings": sum([b.get("total_price", 0) for b in mb])})
            
        earnings_table = []
        for b in bookings:
            guest_id = str(b.get("guest_id", ""))
            guest = db.users.find_one({"_id": ObjectId(guest_id)}) if guest_id else None
            amount = b.get("total_price", 0)
            earnings_table.append({
                "date": str(b.get("created_at", ""))[:10],
                "guest": guest.get("name", "Guest") if guest else "Guest",
                "property": str(b.get("property_id", b.get("listing_id", "")))[:8],
                "nights": b.get("nights", 1),
                "amount": amount,
                "fee": round(amount * 0.1, 2),
                "net": round(amount * 0.9, 2),
                "status": "paid",
            })
            
        return {
            "gross": gross, "fee": fee, "net": net, "pending": pending,
            "monthly_trend": monthly_trend, "earnings_table": earnings_table, "total_bookings": len(bookings)
        }
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reviews")
async def get_host_reviews(current_user: str = Depends(get_current_user)):
    try:
        user_id_str = str(current_user)
        try:
            user_oid = ObjectId(user_id_str)
        except:
            user_oid = None
        id_variants = [user_id_str]
        if user_oid: id_variants.append(user_oid)
            
        listing_ids = []
        for col in ['properties', 'homes', 'crashpads_listings']:
            listings = list(db[col].find({"host_id": {"$in": id_variants}}, {"_id": 1}))
            listing_ids.extend([l["_id"] for l in listings])
            
        all_listing_variants = listing_ids + [str(l) for l in listing_ids]
        reviews = list(db.reviews.find({
            "$or": [{"listing_id": {"$in": all_listing_variants}}, {"property_id": {"$in": all_listing_variants}}]
        }).sort("created_at", -1))
        
        result = []
        for r in reviews:
            reviewer_id = str(r.get("reviewer_id", r.get("user_id", "")))
            reviewer = db.users.find_one({"_id": ObjectId(reviewer_id)}) if reviewer_id else None
            result.append({
                "id": str(r["_id"]),
                "reviewer_name": reviewer.get("name", "Guest") if reviewer else "Guest",
                "reviewer_avatar": reviewer.get("profile_image", "") if reviewer else "",
                "rating": r.get("rating", 5),
                "comment": r.get("comment", r.get("text", "")),
                "host_reply": r.get("host_reply", None),
                "created_at": str(r.get("created_at", ""))[:10],
                "cleanliness": r.get("cleanliness", 5),
                "location": r.get("location", 5),
                "communication": r.get("communication", 5),
                "value": r.get("value", 5),
            })
            
        total = len(result)
        avg = sum([r["rating"] for r in result]) / total if total else 0
        dist = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
        for r in result:
            rt = int(r["rating"])
            if rt in dist: dist[rt] += 1
        dist_pct = {k: round((v/total)*100) if total else 0 for k, v in dist.items()}
        
        return {
            "reviews": result,
            "stats": {
                "avg_rating": round(avg, 1), "total_reviews": total, "distribution": dist_pct,
                "cleanliness": round(sum([r["cleanliness"] for r in result])/total if total else 0, 1),
                "location": round(sum([r["location"] for r in result])/total if total else 0, 1),
                "communication": round(sum([r["communication"] for r in result])/total if total else 0, 1),
                "value": round(sum([r["value"] for r in result])/total if total else 0, 1),
            }
        }
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/reviews/{review_id}/reply")
async def reply_to_review(review_id: str, request: ReviewReplyRequest, current_user: str = Depends(get_current_user)):
    db.reviews.update_one({"_id": ObjectId(review_id)}, {"$set": {"host_reply": request.reply, "host_reply_at": datetime.utcnow()}})
    return {"message": "Reply submitted successfully"}

@router.get("/notifications")
async def get_host_notifications(current_user: str = Depends(get_current_user)):
    try:
        user_id_str = str(current_user)
        notifs = list(db.notifications.find({"user_id": user_id_str}).sort("created_at", -1).limit(50))
        
        if not notifs:
            bookings = list(db.bookings.find({"host_id": user_id_str}).sort("created_at", -1).limit(20))
            for b in bookings:
                guest = db.users.find_one({"_id": ObjectId(b.get("guest_id"))})
                status = b.get("status", "pending")
                title = "New booking request" if status == "pending" else "Booking confirmed" if status == "confirmed" else "Booking update"
                desc = f"{guest.get('name', 'A guest') if guest else 'A guest'} {status} to book your property"
                notifs.append({"_id": b["_id"], "title": title, "description": desc, "type": "booking", "is_read": False, "created_at": b.get("created_at")})
                
        return {
            "notifications": [{"id": str(n["_id"]), "title": n.get("title", ""), "description": n.get("description", ""), "is_read": n.get("is_read", False), "created_at": str(n.get("created_at", ""))[:10]} for n in notifs],
            "unread_count": len([n for n in notifs if not n.get("is_read")])
        }
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/listings/{listing_id}/toggle")
def toggle_listing_active(listing_id: str, user_id: str = Depends(get_current_user)):
    if not ObjectId.is_valid(listing_id):
        raise HTTPException(status_code=400, detail="Invalid listing ID")

    uid = ObjectId(user_id)
    oid = ObjectId(listing_id)

    # Try every collection where listings might live
    collections_to_try = ["homes", "crashpads_listings", "travel_buddies", "buddy_requests", "properties"]

    for collection_name in collections_to_try:
        coll = getattr(db, collection_name, None)
        if coll is None:
            continue

        # Try every host field variant: host_id, hostId, user_id, userId, owner_id, ownerId
        ownership_query = {
            "$or": [
                {"host_id": uid}, {"host_id": user_id},
                {"hostId": uid}, {"hostId": user_id},
                {"user_id": uid}, {"user_id": user_id},
                {"userId": uid}, {"userId": user_id},
                {"owner_id": uid}, {"owner_id": user_id},
                {"ownerId": uid}, {"ownerId": user_id},
            ]
        }

        listing = coll.find_one({"_id": oid, **ownership_query})
        if listing:
            new_state = not bool(listing.get("is_active", True))
            coll.update_one(
                {"_id": oid},
                {"$set": {"is_active": new_state, "updated_at": datetime.utcnow()}}
            )
            print(f"✅ Toggled {listing_id} in {collection_name} -> is_active={new_state}")
            return {"id": listing_id, "is_active": new_state, "collection": collection_name, "message": "Listing toggled"}

    raise HTTPException(status_code=404, detail="Listing not found or not owned by host")

@router.delete("/listings/{listing_id}")
async def delete_listing(listing_id: str, current_user: str = Depends(get_current_user)):
    oid = ObjectId(listing_id)
    for col in [db.homes, db.properties]:
        if col.delete_one({"_id": oid}).deleted_count:
            return {"message": "Deleted"}
    raise HTTPException(status_code=404, detail="Not found")

@router.delete("/crashpads/{crashpad_id}")
async def delete_crashpad_host(crashpad_id: str, current_user: str = Depends(get_current_user)):
    oid = ObjectId(crashpad_id)
    if db.crashpads_listings.delete_one({"_id": oid}).deleted_count:
        return {"message": "Deleted"}
    raise HTTPException(status_code=404, detail="Not found")

@router.get("/stats/{listing_id}")
async def get_listing_stats(listing_id: str, current_user: str = Depends(get_current_user)):
    try:
        id_variants = [listing_id, ObjectId(listing_id)] 
        views = db.views.count_documents({"listing_id": {"$in": id_variants}})
        bookings = list(db.bookings.find({"property_id": {"$in": id_variants}}))
        revenue = sum([b.get("total_price", 0) for b in bookings if b.get("status") == "confirmed"])
        reviews = list(db.reviews.find({"listing_id": {"$in": id_variants}}))
        avg = sum([r.get("rating", 0) for r in reviews]) / len(reviews) if reviews else 0
        return {
            "views": views, "total_bookings": len(bookings), "total_revenue": revenue, "avg_rating": round(avg, 1),
            "confirmed_bookings": len([b for b in bookings if b.get("status") == "confirmed"]),
            "pending_bookings": len([b for b in bookings if b.get("status") == "pending"]),
            "rejected_bookings": len([b for b in bookings if b.get("status") == "rejected"]),
            "occupancy_rate": round((len([b for b in bookings if b.get("status") == "confirmed"]) / 30) * 100)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/host/reviews-summary")
async def get_host_reviews_summary(current_user: dict = Depends(get_current_user)):
    host_id = str(current_user["_id"])
    
    listings = list(db.listings.find({
        "$or": [{"host_id": host_id}, {"hostId": host_id}]
    }))
    listing_ids = [str(l["_id"]) for l in listings]
    listing_map = {str(l["_id"]): l.get("title", "Listing") for l in listings}
    
    if not listing_ids:
        return {
            "overall_rating": 0.0,
            "total_reviews": 0,
            "distribution": {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0},
            "category_ratings": {"cleanliness": 0.0, "location": 0.0, "communication": 0.0, "value": 0.0},
            "recent_reviews": []
        }
    
    reviews = list(db.reviews.find({
        "$or": [{"listing_id": {"$in": listing_ids}}, {"listingId": {"$in": listing_ids}}]
    }))
    
    total = len(reviews)
    if total == 0:
        return {
            "overall_rating": 0.0,
            "total_reviews": 0,
            "distribution": {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0},
            "category_ratings": {"cleanliness": 0.0, "location": 0.0, "communication": 0.0, "value": 0.0},
            "recent_reviews": []
        }
    
    ratings = [r.get("rating", 0) for r in reviews]
    overall = round(sum(ratings) / total, 1)
    
    dist = {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0}
    for r in ratings:
        key = str(int(round(r)))
        if key in dist:
            dist[key] += 1
    distribution = {k: round((v / total) * 100) for k, v in dist.items()}
    
    def cat_avg(field):
        vals = [r.get(field, r.get("rating", 0)) for r in reviews]
        return round(sum(vals) / len(vals), 1) if vals else 0.0
    
    category_ratings = {
        "cleanliness": cat_avg("cleanliness"),
        "location": cat_avg("location"),
        "communication": cat_avg("communication"),
        "value": cat_avg("value")
    }
    
    sorted_reviews = sorted(reviews, key=lambda r: r.get("created_at", r.get("createdAt", "")), reverse=True)[:10]
    recent = [{
        "_id": str(r["_id"]),
        "guest_name": r.get("guest_name", r.get("guestName", "Guest")),
        "rating": r.get("rating", 0),
        "comment": r.get("comment", ""),
        "created_at": str(r.get("created_at", r.get("createdAt", ""))),
        "listing_title": listing_map.get(str(r.get("listing_id", r.get("listingId", ""))), "Listing")
    } for r in sorted_reviews]
    
    return {
        "overall_rating": overall,
        "total_reviews": total,
        "distribution": distribution,
        "category_ratings": category_ratings,
        "recent_reviews": recent
    }
