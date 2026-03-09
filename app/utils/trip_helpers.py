from fastapi import HTTPException
from bson import ObjectId
from datetime import datetime, timezone
from app.core.database import db


def to_oid(val: str, label: str = "id") -> ObjectId:
    """Convert a string to a MongoDB ObjectId, raising 400 on failure."""
    try:
        return ObjectId(val)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid {label}: {val}")


def log_activity(trip_id: ObjectId, user_id: ObjectId | None, action: str):
    """Insert an activity log entry for a trip."""
    db.trip_activities.insert_one({
        "trip_id": trip_id,
        "user_id": user_id,
        "action": action,
        "created_at": datetime.now(timezone.utc),
    })
