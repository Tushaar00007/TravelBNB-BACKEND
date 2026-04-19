from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from app.services.ml_service import get_itinerary_async, download_itinerary_pdf_async, forward_chat_async
from fastapi.responses import StreamingResponse

router = APIRouter()

class ItineraryRequest(BaseModel):
    location: str
    days: int
    start_date: str
    preferences: Optional[dict] = None

class ChatRequest(BaseModel):
    message: str

@router.post("/generate")
async def generate_itinerary(request: ItineraryRequest):
    """
    Endpoint to generate an itinerary using the external ML model.
    """
    result = await get_itinerary_async(
        location=request.location,
        days=request.days,
        start_date=request.start_date,
        preferences=request.preferences
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
        start_date=request.start_date,
        preferences=request.preferences
    )

    if isinstance(pdf_stream, dict) and "error" in pdf_stream:
        return pdf_stream

    filename = f"itinerary_{request.location.lower().replace(' ', '_')}.pdf"
    
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "application/pdf"
    }

    return StreamingResponse(
        pdf_stream,
        media_type="application/pdf",
        headers=headers
    )

@router.post("/chat")
async def chat(request: ChatRequest):
    """
    Proxy endpoint — forwards chat messages to the ML model and returns the reply.
    All frontend traffic goes through the backend only.
    """
    return await forward_chat_async(message=request.message)
