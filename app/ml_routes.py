from fastapi import APIRouter
from pydantic import BaseModel
from app.ml_service import get_itinerary_async

router = APIRouter()

class ItineraryRequest(BaseModel):
    location: str
    days: int
    start_date: str

@router.post("/generate")
async def generate_itinerary(request: ItineraryRequest):
    """
    Endpoint to generate an itinerary using the external ML model.
    """
    result = await get_itinerary_async(
        location=request.location,
        days=request.days,
        start_date=request.start_date
    )
    return result
