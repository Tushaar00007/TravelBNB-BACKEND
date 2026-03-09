from fastapi import APIRouter
from pydantic import BaseModel
from app.services.ml_service import get_itinerary_async, download_itinerary_pdf_async
from fastapi.responses import StreamingResponse

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

@router.post("/download_pdf")
async def download_pdf(request: ItineraryRequest):
    """
    Endpoint to download the itinerary PDF.
    """
    pdf_stream = await download_itinerary_pdf_async(
        location=request.location,
        days=request.days,
        start_date=request.start_date
    )
    
    if isinstance(pdf_stream, dict) and "error" in pdf_stream:
        return pdf_stream

    return StreamingResponse(
        pdf_stream,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=itinerary_{request.location.lower()}.pdf"
        }
    )
