from fastapi import APIRouter, HTTPException
from app.database import db
from app.sarvam_service import translate_text
from datetime import datetime
from bson import ObjectId

router = APIRouter()


# ─────────────────────────────────────────────
# POST /api/messages/translate  (translate-only, no DB write)
# ─────────────────────────────────────────────
@router.post("/translate")
def translate_only(payload: dict):
    """
    Translate a message on demand without saving it.
    Body: { message, targetLanguage }
    Returns: { translated }
    """
    try:
        message = payload.get("message", "").strip()
        target_lang = payload.get("targetLanguage", "en-IN")
        if not message:
            raise HTTPException(status_code=400, detail="message is required")
        translated = translate_text(message, "auto", target_lang)
        return {"translated": translated}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# Helper: serialize a MongoDB message document
# ─────────────────────────────────────────────
def serialize_message(msg: dict) -> dict:
    return {
        "_id": str(msg["_id"]),
        "senderId": str(msg["senderId"]),
        "receiverId": str(msg["receiverId"]),
        "propertyId": str(msg["propertyId"]),
        "messageOriginal": msg.get("messageOriginal", ""),
        "messageTranslated": msg.get("messageTranslated", ""),
        "sourceLanguage": msg.get("sourceLanguage", ""),
        "targetLanguage": msg.get("targetLanguage", ""),
        "createdAt": msg["createdAt"].isoformat() if isinstance(msg.get("createdAt"), datetime) else str(msg.get("createdAt", "")),
    }


# ─────────────────────────────────────────────
# POST /api/messages/send
# ─────────────────────────────────────────────
@router.post("/send")
def send_message(payload: dict):
    """
    Send a message from one user to another for a given property.
    Automatically translates the message using Sarvam AI.

    Body:
        senderId, receiverId, propertyId, message, sourceLanguage, targetLanguage
    """
    try:
        sender_id_str = payload.get("senderId")
        receiver_id_str = payload.get("receiverId")
        property_id_str = payload.get("propertyId")
        message = payload.get("message", "").strip()
        source_lang = payload.get("sourceLanguage", "auto")   # auto = Sarvam language detection
        target_lang = payload.get("targetLanguage", "en-IN")

        # --- Validate required fields ---
        if not all([sender_id_str, receiver_id_str, property_id_str, message]):
            raise HTTPException(
                status_code=400,
                detail="Missing required fields: senderId, receiverId, propertyId, message",
            )

        # --- Validate ObjectIds ---
        try:
            sender_id = ObjectId(sender_id_str)
            receiver_id = ObjectId(receiver_id_str)
            property_id = ObjectId(property_id_str)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid senderId, receiverId, or propertyId format")

        # --- Validate sender and receiver exist ---
        if not db.users.find_one({"_id": sender_id}):
            raise HTTPException(status_code=404, detail="Sender not found")
        if not db.users.find_one({"_id": receiver_id}):
            raise HTTPException(status_code=404, detail="Receiver not found")

        # --- Validate property exists ---
        if not db.homes.find_one({"_id": property_id}):
            raise HTTPException(status_code=404, detail="Property not found")

        # --- Translate ---
        translated_message = translate_text(message, source_lang, target_lang)

        # --- Store ---
        new_message = {
            "senderId": sender_id,
            "receiverId": receiver_id,
            "propertyId": property_id,
            "messageOriginal": message,
            "messageTranslated": translated_message,
            "sourceLanguage": source_lang,
            "targetLanguage": target_lang,
            "createdAt": datetime.utcnow(),
        }

        result = db.messages.insert_one(new_message)
        new_message["_id"] = result.inserted_id

        print(f"✅ Message sent: {sender_id_str} → {receiver_id_str}")
        return {"success": True, "message": serialize_message(new_message)}

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ send_message error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# GET /api/messages/{user1_id}/{user2_id}/{property_id}
# ─────────────────────────────────────────────
@router.get("/{user1_id}/{user2_id}/{property_id}")
def get_chat_history(user1_id: str, user2_id: str, property_id: str):
    """
    Return all messages between two users for a given property,
    sorted by createdAt ascending.

    Security: Only the two participants can access their conversation.
    Pass the requesting user's ID as query param ?requesterId=...
    """
    try:
        try:
            u1 = ObjectId(user1_id)
            u2 = ObjectId(user2_id)
            prop = ObjectId(property_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid ID format")

        # Fetch messages where either user is the sender or receiver (bi-directional)
        messages = list(
            db.messages.find(
                {
                    "propertyId": prop,
                    "$or": [
                        {"senderId": u1, "receiverId": u2},
                        {"senderId": u2, "receiverId": u1},
                    ],
                }
            ).sort("createdAt", 1)  # ascending → oldest first
        )

        return {"messages": [serialize_message(m) for m in messages]}

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ get_chat_history error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# GET /api/messages/conversations/{user_id}
# ─────────────────────────────────────────────
@router.get("/conversations/{user_id}")
def get_conversations(user_id: str):
    """
    Return a deduplicated list of conversations for a user.
    Each item contains:
        propertyId, otherUserId, lastMessage, lastMessageTime, propertyTitle, otherUserName
    """
    try:
        try:
            uid = ObjectId(user_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid user_id format")

        # Fetch all messages involving this user
        all_messages = list(
            db.messages.find(
                {"$or": [{"senderId": uid}, {"receiverId": uid}]}
            ).sort("createdAt", -1)  # newest first so we easily grab lastMessage
        )

        # Group by (otherUserId, propertyId) keeping only the latest message
        seen = {}
        for msg in all_messages:
            sender = str(msg["senderId"])
            receiver = str(msg["receiverId"])
            prop = str(msg["propertyId"])

            other_user_id = receiver if sender == user_id else sender
            key = f"{other_user_id}_{prop}"

            if key not in seen:
                seen[key] = {
                    "propertyId": prop,
                    "otherUserId": other_user_id,
                    "lastMessage": msg.get("messageOriginal", ""),
                    "lastMessageTranslated": msg.get("messageTranslated", ""),
                    "lastMessageTime": msg["createdAt"].isoformat() if isinstance(msg.get("createdAt"), datetime) else str(msg.get("createdAt", "")),
                    "isSender": sender == user_id,
                }

        if not seen:
            return {"conversations": []}

        # Enrich with user names and property titles
        conversations = []
        for key, conv in seen.items():
            other_uid = conv["otherUserId"]
            prop_id = conv["propertyId"]

            # Fetch other user's name
            other_user = db.users.find_one({"_id": ObjectId(other_uid)}, {"name": 1, "profile_picture": 1})
            other_user_name = other_user.get("name", "User") if other_user else "User"
            other_user_pic = other_user.get("profile_picture", "") if other_user else ""

            # Fetch property title
            home = db.homes.find_one({"_id": ObjectId(prop_id)}, {"title": 1, "images": 1})
            property_title = home.get("title", "Property") if home else "Property"
            property_image = (home.get("images", [""])[0]) if home and home.get("images") else ""

            conversations.append({
                **conv,
                "otherUserName": other_user_name,
                "otherUserPic": other_user_pic,
                "propertyTitle": property_title,
                "propertyImage": property_image,
            })

        # Sort by lastMessageTime descending
        conversations.sort(key=lambda x: x["lastMessageTime"], reverse=True)

        print(f"✅ Conversations fetched for user {user_id}: {len(conversations)} found")
        return {"conversations": conversations}

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ get_conversations error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
