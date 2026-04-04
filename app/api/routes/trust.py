from fastapi import APIRouter, Depends, HTTPException, Query
from app.core.database import db
from app.core.dependencies import get_current_user, require_role
from datetime import datetime
from bson import ObjectId

router = APIRouter()

# ========================
# REPORTING SYSTEM
# ========================

@router.post("/report")
def create_report(payload: dict, reporter_id: str = Depends(get_current_user)):
    target_id = payload.get("target_id")
    reason = payload.get("reason")
    description = payload.get("description", "")

    if not target_id or not reason:
        raise HTTPException(status_code=400, detail="Target user and reason are required")

    if target_id == reporter_id:
        raise HTTPException(status_code=400, detail="You cannot report yourself")

    target_user = db.users.find_one({"_id": ObjectId(target_id)})
    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found")

    report_doc = {
        "reporter_id": reporter_id,
        "target_id": target_id,
        "reason": reason,
        "description": description,
        "status": "pending", # pending | resolved | dismissed
        "created_at": datetime.utcnow()
    }

    db.reports.insert_one(report_doc)

    # Initial trust score penalty for getting reported (-5)
    db.users.update_one(
        {"_id": ObjectId(target_id)},
        {"$inc": {"trust_score": -5}}
    )

    return {"message": "Report submitted. Our safety team will review it shortly."}

@router.get("/admin/reports")
def get_reports(
    status: str = Query("pending"),
    user=Depends(require_role(["super_admin", "admin", "sub_admin"]))
):
    reports = list(db.reports.find({"status": status}).sort("created_at", -1))
    
    # Enrich report data with user names
    for report in reports:
        report["_id"] = str(report["_id"])
        reporter = db.users.find_one({"_id": ObjectId(report["reporter_id"])}, {"name": 1, "email": 1})
        target = db.users.find_one({"_id": ObjectId(report["target_id"])}, {"name": 1, "email": 1})
        
        report["reporter_name"] = reporter.get("name", "Unknown") if reporter else "Deleted User"
        report["target_name"] = target.get("name", "Unknown") if target else "Deleted User"
        report["target_email"] = target.get("email", "") if target else ""

    return reports

@router.put("/admin/reports/{report_id}")
def resolve_report(
    report_id: str, 
    payload: dict,
    user=Depends(require_role(["super_admin", "admin"]))
):
    status = payload.get("status") # resolved | dismissed
    action_taken = payload.get("action_taken", "")

    if status not in ["resolved", "dismissed"]:
        raise HTTPException(status_code=400, detail="Invalid status")

    report = db.reports.find_one({"_id": ObjectId(report_id)})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    db.reports.update_one(
        {"_id": ObjectId(report_id)},
        {"$set": {
            "status": status,
            "action_taken": action_taken,
            "resolved_by": user["id"],
            "resolved_at": datetime.utcnow()
        }}
    )

    # If resolved (confirmed issue), heavy trust penalty (-20)
    if status == "resolved":
        db.users.update_one(
            {"_id": ObjectId(report["target_id"])},
            {"$inc": {"trust_score": -20}}
        )

    return {"message": f"Report marked as {status}"}
