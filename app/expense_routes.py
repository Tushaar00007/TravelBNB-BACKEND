from fastapi import APIRouter, HTTPException
from app.database import db
from app.trip_routes import to_oid, log_activity
from bson import ObjectId
from datetime import datetime, timezone

router = APIRouter()


def serialize_expense(e: dict) -> dict:
    return {
        "_id": str(e["_id"]),
        "trip_id": str(e.get("trip_id", "")),
        "title": e.get("title", ""),
        "amount": e.get("amount", 0),
        "paid_by": str(e.get("paid_by", "")),
        "split_between": [str(u) for u in e.get("split_between", [])],
        "created_at": e["created_at"].isoformat() if isinstance(e.get("created_at"), datetime) else "",
    }


def calculate_owe(expenses: list[dict]) -> dict:
    """
    Returns a dict: { userId: net_balance }
    Positive = is owed money, Negative = owes money.
    """
    balances: dict[str, float] = {}

    for exp in expenses:
        payer = str(exp.get("paid_by", ""))
        amount = float(exp.get("amount", 0))
        split = [str(u) for u in exp.get("split_between", [])]
        if not split:
            continue

        share = amount / len(split)

        # Payer gets credited full amount
        balances[payer] = balances.get(payer, 0) + amount

        # Each person in split gets debited their share
        for uid in split:
            balances[uid] = balances.get(uid, 0) - share

    return balances


# ─── POST /api/trips/{trip_id}/expenses ─────────────────────────────────────

@router.post("/{trip_id}/expenses")
def add_expense(trip_id: str, payload: dict):
    trip_oid = to_oid(trip_id, "trip_id")

    trip = db.trips.find_one({"_id": trip_oid})
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    title = payload.get("title", "").strip()
    amount = payload.get("amount")
    paid_by_str = payload.get("paid_by", "")
    split_between_strs = payload.get("split_between", [])

    if not title or amount is None or not paid_by_str:
        raise HTTPException(status_code=400, detail="title, amount, paid_by are required")

    paid_by_oid = to_oid(paid_by_str, "paid_by")
    split_oids = [to_oid(uid, "split_between user") for uid in split_between_strs]

    # Default: split among all members if not specified
    if not split_oids:
        split_oids = list(trip.get("members", []))

    expense_doc = {
        "trip_id": trip_oid,
        "title": title,
        "amount": float(amount),
        "paid_by": paid_by_oid,
        "split_between": split_oids,
        "created_at": datetime.now(timezone.utc),
    }

    result = db.expenses.insert_one(expense_doc)
    expense_doc["_id"] = result.inserted_id

    payer = db.users.find_one({"_id": paid_by_oid}, {"name": 1})
    payer_name = payer.get("name", "Someone") if payer else "Someone"
    log_activity(trip_oid, paid_by_oid, f"{payer_name} added expense: {title} (₹{amount})")

    return {"success": True, "expense": serialize_expense(expense_doc)}


# ─── GET /api/trips/{trip_id}/expenses ──────────────────────────────────────

@router.get("/{trip_id}/expenses")
def get_expenses(trip_id: str):
    trip_oid = to_oid(trip_id, "trip_id")

    expenses = list(db.expenses.find({"trip_id": trip_oid}).sort("created_at", 1))
    serialized = [serialize_expense(e) for e in expenses]

    # Enrich with payer name
    user_cache: dict[str, str] = {}
    for exp in serialized:
        pid = exp["paid_by"]
        if pid not in user_cache:
            u = db.users.find_one({"_id": ObjectId(pid)}, {"name": 1, "profile_image": 1}) if pid else None
            user_cache[pid] = u.get("name", "Unknown") if u else "Unknown"
        exp["paid_by_name"] = user_cache[pid]

    # Calculate balances
    balances = calculate_owe(expenses)

    # Format as readable "owes" list
    settlements = []
    user_ids = list(balances.keys())
    for i, uid_a in enumerate(user_ids):
        for uid_b in user_ids[i + 1:]:
            bal_a = balances.get(uid_a, 0)
            bal_b = balances.get(uid_b, 0)
            # If bal_a is negative and bal_b positive, a owes b
            if bal_a < 0 and bal_b > 0:
                amount = min(abs(bal_a), bal_b)
                if uid_a not in user_cache:
                    u = db.users.find_one({"_id": ObjectId(uid_a)}, {"name": 1}) if uid_a else None
                    user_cache[uid_a] = u.get("name", uid_a) if u else uid_a
                if uid_b not in user_cache:
                    u = db.users.find_one({"_id": ObjectId(uid_b)}, {"name": 1}) if uid_b else None
                    user_cache[uid_b] = u.get("name", uid_b) if u else uid_b
                settlements.append({
                    "from_id": uid_a,
                    "from_name": user_cache.get(uid_a, uid_a),
                    "to_id": uid_b,
                    "to_name": user_cache.get(uid_b, uid_b),
                    "amount": round(amount, 2),
                })
            elif bal_b < 0 and bal_a > 0:
                amount = min(abs(bal_b), bal_a)
                if uid_a not in user_cache:
                    u = db.users.find_one({"_id": ObjectId(uid_a)}, {"name": 1}) if uid_a else None
                    user_cache[uid_a] = u.get("name", uid_a) if u else uid_a
                if uid_b not in user_cache:
                    u = db.users.find_one({"_id": ObjectId(uid_b)}, {"name": 1}) if uid_b else None
                    user_cache[uid_b] = u.get("name", uid_b) if u else uid_b
                settlements.append({
                    "from_id": uid_b,
                    "from_name": user_cache.get(uid_b, uid_b),
                    "to_id": uid_a,
                    "to_name": user_cache.get(uid_a, uid_a),
                    "amount": round(amount, 2),
                })

    total = sum(e.get("amount", 0) for e in expenses)

    return {
        "expenses": serialized,
        "total": round(total, 2),
        "balances": {k: round(v, 2) for k, v in balances.items()},
        "settlements": settlements,
    }
