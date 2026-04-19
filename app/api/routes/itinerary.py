from fastapi import APIRouter, HTTPException, Depends
from app.core.database import db
from app.core.dependencies import get_current_user
from app.services.ml_service import download_itinerary_pdf_async
from fastapi.responses import StreamingResponse
from bson import ObjectId
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime

router = APIRouter()

class SaveItineraryRequest(BaseModel):
    location: str
    days: int
    start_date: str
    preferences: Optional[dict] = None
    planner_data: Any  # Full generated plan

@router.post("/save")
async def save_itinerary(request: SaveItineraryRequest, current_user: str = Depends(get_current_user)):
    """
    Saves a generated itinerary to the database.
    """
    doc = {
        "user_id": ObjectId(current_user),
        "location": request.location,
        "days": request.days,
        "start_date": request.start_date,
        "preferences": request.preferences,
        "planner_data": request.planner_data,
        "created_at": datetime.utcnow()
    }
    result = db.itineraries.insert_one(doc)
    return {"success": True, "itinerary_id": str(result.inserted_id)}

@router.get("/pdf/{itinerary_id}")
async def get_itinerary_pdf(itinerary_id: str):
    """
    Fetches a saved itinerary and returns its PDF.
    """
    try:
        oid = ObjectId(itinerary_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid itinerary ID")

    itinerary = db.itineraries.find_one({"_id": oid})
    if not itinerary:
        raise HTTPException(status_code=404, detail="Itinerary not found")

    # Call ML service to generate PDF
    # Note: Currently ml_service calls ML server which re-generates data.
    # In a production app, we'd pass 'itinerary["planner_data"]' to the ML server 
    # to ensure the PDF matches the saved/edited version.
    pdf_stream = await download_itinerary_pdf_async(
        location=itinerary["location"],
        days=itinerary["days"],
        start_date=itinerary["start_date"],
        preferences=itinerary["preferences"]
    )

    if isinstance(pdf_stream, dict) and "error" in pdf_stream:
        raise HTTPException(status_code=500, detail=pdf_stream["error"])

    filename = f"itinerary_{itinerary['location'].lower().replace(' ', '_')}.pdf"
    
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "application/pdf"
    }
    
    return StreamingResponse(
        pdf_stream,
        media_type="application/pdf",
        headers=headers
    )
