from fastapi import APIRouter, HTTPException, Depends
from app.core.database import db
from datetime import datetime
from bson import ObjectId
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter()

class SendMessageRequest(BaseModel):
    sender_id: str
    recipient_id: str
    message: str
    booking_request_id: Optional[str] = None
    booking_status: Optional[str] = None
    property_id: Optional[str] = None
    property_name: Optional[str] = None
    reply_to: Optional[str] = None

# ─────────────────────────────────────────────
# POST /api/messages/{message_id}/translate
# Cached per-message translation
# ─────────────────────────────────────────────
@router.post("/{message_id}/translate")
def translate_message(message_id: str, payload: dict):
    """
    Translate a specific message and cache the result on the message document.
    Subsequent requests for the same message + target language return the cached version.
    """
    from app.services.sarvam_service import translate_text

    target_lang = payload.get("targetLanguage", "en-IN")
    if not target_lang:
        raise HTTPException(status_code=400, detail="targetLanguage is required")

    try:
        oid = ObjectId(message_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid message ID")

    msg = db.messages.find_one({"_id": oid})
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    # Check cache first
    cached = (msg.get("translations") or {}).get(target_lang)
    if cached:
        return {
            "translated": cached,
            "target_language": target_lang,
            "cached": True,
        }

    # Get original text
    original = (
        msg.get("messageOriginal")
        or msg.get("message")
        or msg.get("content")
        or ""
    )
    if not original.strip():
        return {"translated": "", "target_language": target_lang, "cached": False}

    # Call Sarvam
    translated = translate_text(original, "auto", target_lang)

    # Cache on the message document under translations.<lang>
    db.messages.update_one(
        {"_id": oid},
        {"$set": {f"translations.{target_lang}": translated}}
    )

    return {
        "translated": translated,
        "target_language": target_lang,
        "cached": False,
    }

# ─────────────────────────────────────────────
# POST /api/messages/translate
# ─────────────────────────────────────────────
@router.post("/translate")
def translate_only(payload: dict):
    from app.services.sarvam_service import translate_text
    try:
        message = payload.get("message", "").strip()
        target_lang = payload.get("targetLanguage", "en-IN")
        if not message:
            raise HTTPException(status_code=400, detail="message is required")
        translated = translate_text(message, "auto", target_lang)
        return {"translated": translated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─────────────────────────────────────────────
# POST /api/messages/send
# ─────────────────────────────────────────────
@router.post("/send")
async def send_message(request: SendMessageRequest):
    try:
        from bson import ObjectId
        from datetime import datetime
        
        def to_oid(id_str):
            if not id_str: return None
            try:
                # Remove ANY accidental whitespace (fixes the "space in ID" bug)
                clean_id = str(id_str).replace(" ", "").strip()
                return ObjectId(clean_id)
            except:
                return str(id_str).replace(" ", "").strip()
        
        s_id = str(request.sender_id).replace(" ", "").strip()
        r_id = str(request.recipient_id).replace(" ", "").strip()
        p_id = str(request.property_id).replace(" ", "").strip() if request.property_id else None
        br_id = str(request.booking_request_id).replace(" ", "").strip() if request.booking_request_id else None

        new_msg = {
            # Store in camelCase to match existing DB format
            "senderId": to_oid(s_id),
            "receiverId": to_oid(r_id),
            "messageOriginal": request.message,
            "messageTranslated": request.message,
            "message": request.message,
            "propertyId": to_oid(p_id) if p_id else None,
            "property_name": request.property_name or "",
            "booking_request_id": to_oid(br_id) if br_id else None,
            "booking_status": request.booking_status or "pending",
            "sourceLanguage": "auto",
            "targetLanguage": "en-IN",
            "isRead": False,
            "reply_to": to_oid(request.reply_to) if request.reply_to else None,
            "createdAt": datetime.utcnow(),
            # Also store snake_case for backwards compatibility
            "sender_id": s_id,
            "recipient_id": r_id,
            "created_at": datetime.utcnow(),
        }
        
        result = db.messages.insert_one(new_msg)
        print(f"Message saved: {result.inserted_id}")
        
        return {
            "id": str(result.inserted_id),
            "status": "sent"
        }
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

# ─────────────────────────────────────────────
# GET /api/messages/conversations/{user_id}
# ─────────────────────────────────────────────
@router.get("/conversations/{user_id}")
async def get_conversations(user_id: str):
    try:
        from bson import ObjectId
        
        user_id_str = str(user_id)
        try:
            user_oid = ObjectId(user_id_str)
        except:
            user_oid = None
        
        id_variants = [user_id_str]
        if user_oid:
            id_variants.append(user_oid)
        
        print(f"Getting conversations for: {user_id_str}")
        
        # Query messages
        messages = list(db.messages.find({
            "$or": [
                {"senderId": {"$in": id_variants}},
                {"receiverId": {"$in": id_variants}},
                {"sender_id": {"$in": id_variants}},
                {"recipient_id": {"$in": id_variants}},
                {"receiver_id": {"$in": id_variants}},
            ]
        }).sort("createdAt", -1))
        
        if not messages:
            messages = list(db.messages.find({
                "$or": [
                    {"senderId": {"$in": id_variants}},
                    {"receiverId": {"$in": id_variants}},
                    {"sender_id": {"$in": id_variants}},
                    {"recipient_id": {"$in": id_variants}},
                ]
            }).sort("created_at", -1))
        
        # 1. Group by other_id and collect participant IDs
        conversations_raw = {}
        participant_ids = {user_id_str} 
        
        for msg in messages:
            sender = str(msg.get("senderId") or msg.get("sender_id", ""))
            receiver = str(msg.get("receiverId") or msg.get("receiver_id") or msg.get("recipient_id", ""))
            
            other_id = receiver if sender == user_id_str else sender
            if not other_id or other_id == user_id_str:
                continue
            
            participant_ids.add(other_id)
            if other_id not in conversations_raw:
                conversations_raw[other_id] = msg
        
        # 2. Bulk Fetch Participant Details
        participant_oids = []
        for pid in participant_ids:
            try: participant_oids.append(ObjectId(pid))
            except: pass
            
        users_cursor = db.users.find({
            "$or": [
                {"_id": {"$in": participant_oids}},
                {"id": {"$in": list(participant_ids)}}
            ]
        }, {"_id": 1, "id": 1, "name": 1, "profile_image": 1})
        
        user_map = {}
        for u in users_cursor:
            uid = str(u["_id"])
            user_map[uid] = {
                "_id": uid,
                "name": u.get("name", "User"),
                "avatar": u.get("profile_image", "")
            }
        
        # Ensure current user is in map
        if user_id_str not in user_map:
            user_map[user_id_str] = {"_id": user_id_str, "name": "You", "avatar": ""}

        # 3. Build Response
        result = []
        for other_id, msg in conversations_raw.items():
            other_user_info = user_map.get(other_id, {"_id": other_id, "name": "Unknown User", "avatar": ""})
            current_user_info = user_map.get(user_id_str, {"_id": user_id_str, "name": "You", "avatar": ""})
            
            # Add profile_image key to otherUser for frontend compatibility
            other_user_info["profile_image"] = other_user_info.get("avatar", "")
            current_user_info["profile_image"] = current_user_info.get("avatar", "")
            
            # Fetch property/home context to determine roles
            prop_id = str(msg.get("propertyId") or msg.get("property_id", ""))
            host_id = None
            guest_id = None
            is_host = False
            property_info = None
            
            if prop_id:
                try:
                    property_info = db.homes.find_one({"_id": ObjectId(prop_id)}) or db.properties.find_one({"_id": ObjectId(prop_id)})
                    if property_info:
                        host_id = str(property_info.get("host_id") or property_info.get("userId") or "")
                        is_host = (host_id == user_id_str)
                        # If I am host, other is guest. If I am guest, other is host.
                        if is_host:
                            guest_id = other_id
                        else:
                            guest_id = user_id_str
                            # host_id is already set from property_info
                except:
                    pass
            
            # Fallback for Travel Buddy or direct messages
            if not host_id:
                # For Travel Buddy, the listing owner (receiver of first message) is host
                if msg.get("message_type") == "travel_buddy_connect":
                    host_id = str(msg.get("receiver_id") or msg.get("receiverId") or "")
                    guest_id = str(msg.get("sender_id") or msg.get("senderId") or "")
                    is_host = (host_id == user_id_str)
                else:
                    # Generic: sender of first message in thread is guest, receiver is host
                    # But since we group by other_id, we just use a heuristic
                    is_host = False 
            
            last_msg = str(
                msg.get("messageOriginal") 
                or msg.get("messageTranslated")
                or msg.get("message")
                or msg.get("content")
                or ""
            )[:60]

            result.append({
                "_id": f"{user_id_str}_{other_id}",
                "conversation_id": f"{user_id_str}_{other_id}",
                "participants": [current_user_info, other_user_info],
                "otherUser": other_user_info,
                "other_user_id": other_id,
                "other_user_name": other_user_info["name"],
                "other_user_avatar": other_user_info["avatar"],
                "lastMessage": last_msg,
                "last_message": last_msg,
                "updatedAt": str(msg.get("createdAt") or msg.get("created_at", "")),
                "last_message_time": str(msg.get("createdAt") or msg.get("created_at", "")),
                "propertyName": property_info.get("title", "") if property_info else "",
                "property_name": property_info.get("title", "") if property_info else "",
                "property_id": prop_id,
                "booking_status": msg.get("booking_status", "pending"),
                "unread_count": 0,
                "reactions": msg.get("reactions", []),
                "isHost": is_host,
                "is_host": is_host,
                "host_id": host_id,
                "guest_id": guest_id
            })
            
        return result
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return []

# ─────────────────────────────────────────────
# GET /api/messages/{user_id}/{other_user_id}
# ─────────────────────────────────────────────
@router.get("/{user_id}/{other_user_id}")
async def get_messages(user_id: str, other_user_id: str):
    try:
        from bson import ObjectId
        
        def get_variants(id_str):
            clean_id = str(id_str).replace(" ", "").strip()
            variants = [clean_id]
            try:
                variants.append(ObjectId(clean_id))
            except:
                pass
            return variants
        
        user_variants = get_variants(user_id)
        other_variants = get_variants(other_user_id)
        
        messages = list(db.messages.find({
            "$or": [
                # camelCase format
                {
                    "senderId": {"$in": user_variants},
                    "receiverId": {"$in": other_variants},
                },
                {
                    "senderId": {"$in": other_variants},
                    "receiverId": {"$in": user_variants},
                },
                # snake_case format
                {
                    "sender_id": {"$in": user_variants},
                    "recipient_id": {"$in": other_variants},
                },
                {
                    "sender_id": {"$in": other_variants},
                    "recipient_id": {"$in": user_variants},
                },
            ]
        }).sort([("createdAt", 1), ("created_at", 1)]))
        
        print(f"Messages between {user_id} and {other_user_id}: {len(messages)}")
        
        result = []
        for msg in messages:
            sender = str(msg.get("senderId") or msg.get("sender_id", ""))
            result.append({
                "id": str(msg["_id"]),
                "sender_id": sender,
                "recipient_id": str(msg.get("receiverId") or msg.get("recipient_id", "")),
                "message": str(
                    msg.get("messageOriginal") 
                    or msg.get("messageTranslated")
                    or msg.get("message")
                    or msg.get("content")
                    or ""
                ),
                "translations": msg.get("translations", {}),
                "booking_request_id": str(msg.get("booking_request_id") or "") or None,
                "booking_status": msg.get("booking_status"),
                "created_at": str(msg.get("createdAt") or msg.get("created_at", "")),
                "is_read": msg.get("is_read", msg.get("isRead", False)),
                "reply_to": str(msg.get("reply_to")) if msg.get("reply_to") else None,
                "reply_to_text": str(db.messages.find_one({"_id": ObjectId(msg["reply_to"])}, {"message": 1})["message"]) if msg.get("reply_to") else None,
                "reactions": msg.get("reactions", []),
            })
        
        return result
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return []


# ─────────────────────────────────────────────
# PATCH /api/messages/{other_user_id}/{property_id}/read
# ─────────────────────────────────────────────
@router.patch("/{other_user_id}/{property_id}/read")
def mark_as_read(other_user_id: str, property_id: str, requesterId: str):
    """
    Mark all received messages in a conversation as read.
    """
    try:
        res = db.messages.update_many(
            {
                "$or": [
                    {"sender_id": other_user_id},
                    {"senderId": ObjectId(other_user_id)}
                ],
                "$or": [
                    {"recipient_id": requesterId},
                    {"receiverId": ObjectId(requesterId)}
                ],
                "$or": [
                    {"property_id": property_id},
                    {"propertyId": ObjectId(property_id)}
                ],
                "is_read": {"$ne": True}
            },
            {"$set": {"is_read": True}}
        )
        return {"success": True, "modified_count": res.modified_count}
    except Exception as e:
        print(f"❌ mark_as_read error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─────────────────────────────────────────────
# DELETE /api/messages/{message_id}
# ─────────────────────────────────────────────
@router.delete("/{message_id}")
def delete_message(message_id: str):
    try:
        db.messages.delete_one({"_id": ObjectId(message_id)})
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─────────────────────────────────────────────
# POST /api/messages/{message_id}/react
# ─────────────────────────────────────────────
@router.post("/{message_id}/react")
async def react_to_message(message_id: str, payload: dict):
    try:
        emoji = payload.get("emoji")
        user_id = payload.get("user_id") # Normally from session
        if not emoji:
            raise HTTPException(status_code=400, detail="Emoji required")
        
        # Simple toggle logic: if user already reacted with this emoji, remove it
        existing = db.messages.find_one({
            "_id": ObjectId(message_id),
            "reactions": {"$elemMatch": {"emoji": emoji, "user_id": user_id}}
        })
        
        if existing:
            db.messages.update_one(
                {"_id": ObjectId(message_id)},
                {"$pull": {"reactions": {"emoji": emoji, "user_id": user_id}}}
            )
        else:
            db.messages.update_one(
                {"_id": ObjectId(message_id)},
                {"$push": {"reactions": {"emoji": emoji, "user_id": user_id}}}
            )
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─────────────────────────────────────────────
# DELETE /api/messages/conversation/{user_id}/{other_user_id}
# ─────────────────────────────────────────────
@router.delete("/conversation/{user_id}/{other_id}")
def delete_conversation(user_id: str, other_id: str):
    try:
        def get_variants(id_str):
            v = [id_str]
            try: v.append(ObjectId(id_str))
            except: pass
            return v
        
        u_vars = get_variants(user_id)
        o_vars = get_variants(other_id)
        
        db.messages.delete_many({
            "$or": [
                {
                    "$or": [{"senderId": {"$in": u_vars}}, {"sender_id": {"$in": u_vars}}],
                    "$or": [{"receiverId": {"$in": o_vars}}, {"recipient_id": {"$in": o_vars}}, {"receiver_id": {"$in": o_vars}}]
                },
                {
                    "$or": [{"senderId": {"$in": o_vars}}, {"sender_id": {"$in": o_vars}}],
                    "$or": [{"receiverId": {"$in": u_vars}}, {"recipient_id": {"$in": u_vars}}, {"receiver_id": {"$in": u_vars}}]
                }
            ]
        })
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
