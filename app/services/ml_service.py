import httpx
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

async def get_itinerary_async(location: str, days: int, start_date: str) -> Dict[str, Any]:
    """
    Asynchronously calls the ML model to generate an itinerary.
    The ML model is expected to be running on localhost:9000.
    """
    url = "http://localhost:9000/generate_itinerary"
    
    payload = {
        "location": location,
        "days": days,
        "start_date": start_date
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    logger.info(f"Calling ML model at {url} for location: {location}, days: {days}, start_date: {start_date}")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            logger.info("Successfully received itinerary from ML model.")
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Error calling ML model for itinerary: {e}")
            return {"error": "Failed to generate itinerary. Please ensure the ML model is running."}

async def download_itinerary_pdf_async(location: str, days: int, start_date: str):
    """
    Asynchronously calls the ML model to generate an itinerary PDF.
    Returns a BytesIO stream of the PDF.
    """
    url = "http://localhost:9000/download_pdf"
    
    payload = {
        "location": location,
        "days": days,
        "start_date": start_date
    }
    
    logger.info(f"Requesting PDF from ML model at {url} for location: {location}")
    
    async with httpx.AsyncClient() as client:
        try:
            # We use timeout=None because PDF generation might take a few seconds
            response = await client.post(url, json=payload, timeout=None)
            response.raise_for_status()
            
            from io import BytesIO
            return BytesIO(response.content)
            
        except httpx.HTTPError as e:
            logger.error(f"Error downloading PDF from ML model: {e}")
            return {"error": "Failed to download PDF itinerary."}
