import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import httpx
import os
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

# Ensure environment variables are loaded
load_dotenv()

# Use the Google Maps API Key from the backend .env
GOOGLE_MAPS_API_KEY = os.getenv("VITE_GOOGLE_MAPS_API_KEY")

class GeocodeRequest(BaseModel):
    address: str

class ReverseGeocodeRequest(BaseModel):
    lat: float
    lng: float

class PincodeLookupRequest(BaseModel):
    pincode: str

@router.post("/geocode")
async def geocode(request: GeocodeRequest):
    if not GOOGLE_MAPS_API_KEY:
        raise HTTPException(status_code=500, detail="Google Maps API Key not configured on server.")

    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={request.address}&key={GOOGLE_MAPS_API_KEY}"
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        data = response.json()

        if data["status"] == "OK":
            result = data["results"][0]
            return {
                "lat": result["geometry"]["location"]["lat"],
                "lng": result["geometry"]["location"]["lng"],
                "formatted_address": result["formatted_address"]
            }
        else:
            raise HTTPException(status_code=400, detail=f"Geocoding failed: {data.get('status')}")

@router.post("/reverse-geocode")
async def reverse_geocode(request: ReverseGeocodeRequest):
    if not GOOGLE_MAPS_API_KEY:
        raise HTTPException(status_code=500, detail="Google Maps API Key not configured on server.")

    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={request.lat},{request.lng}&key={GOOGLE_MAPS_API_KEY}"
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        data = response.json()

        if data["status"] == "OK":
            return {
                "formatted_address": data["results"][0]["formatted_address"]
            }
        else:
            raise HTTPException(status_code=400, detail=f"Reverse geocoding failed: {data.get('status')}")

@router.get("/pincode-lookup")
async def pincode_lookup(pin: str):
    if not GOOGLE_MAPS_API_KEY:
        logger.error("Google Maps API Key is missing.")
        raise HTTPException(status_code=500, detail="Google Maps API Key not configured on server.")

    pincode = pin.strip()
    if not pincode.isdigit() or len(pincode) != 6:
        raise HTTPException(status_code=400, detail="Invalid PIN code format. Please check again.")

    logger.info(f"🔍 Starting PIN lookup for: {pincode}")

    # 1. Fetch from India Post API (api.postalpincode.in)
    post_url = f"https://api.postalpincode.in/pincode/{pincode}"
    city, district, state = "", "", ""
    lat, lng = 0.0, 0.0
    
    async with httpx.AsyncClient() as client:
        try:
            post_response = await client.get(post_url)
            post_data = post_response.json()
            
            if post_data and post_data[0]["Status"] == "Success":
                post_office = post_data[0]["PostOffice"][0]
                city = post_office.get("District", "")
                district = post_office.get("Name", "")
                state = post_office.get("State", "")
                logger.info(f"✅ India Post found: {district}, {city}, {state}")
            else:
                logger.warning(f"⚠️ India Post API returned: {post_data[0].get('Status') if post_data else 'No data'}")
        except Exception as e:
            logger.error(f"❌ India Post API error: {str(e)}")

        # 2. Try multiple Google Geocoding fallbacks for coordinates
        queries = [
            f"{pincode},INDIA", # Primary
            f"{district}, {city}, {state}, INDIA" if district else None, # Fallback 1: Area based
            f"{city}, {state}, INDIA" if city else None, # Fallback 2: City based
            f"{pincode}" # Fallback 3: Just the PIN
        ]
        
        # Filter out None queries
        queries = [q for q in queries if q]

        for query in queries:
            logger.info(f"📡 Attempting Google Geocode: '{query}'")
            google_url = f"https://maps.googleapis.com/maps/api/geocode/json?address={query}&key={GOOGLE_MAPS_API_KEY}"
            
            try:
                google_response = await client.get(google_url)
                google_data = google_response.json()

                if google_data["status"] == "OK":
                    result = google_data["results"][0]
                    lat = result["geometry"]["location"]["lat"]
                    lng = result["geometry"]["location"]["lng"]
                    
                    logger.info(f"📍 Geocode SUCCESS for '{query}': {lat}, {lng}")
                    
                    # Fill missing city/state from Google if still empty
                    if not city or not state:
                        for component in result["address_components"]:
                            if not city and ("locality" in component["types"] or "administrative_area_level_2" in component["types"]):
                                city = component["long_name"]
                            if not state and "administrative_area_level_1" in component["types"]:
                                state = component["long_name"]
                    break # Success! Exit fallback loop
                else:
                    logger.warning(f"❌ Google Geocode failed for '{query}': {google_data['status']}")
            except Exception as e:
                logger.error(f"❌ Google Geocode Exception: {str(e)}")

        if not lat or not lng:
            logger.error(f"🚫 All geocoding attempts FAILED for PIN: {pincode}")
            raise HTTPException(status_code=400, detail="Could not locate this PIN. Please check your address or pin the map manually.")

        return {
            "city": city.upper() if city else "MUMBAI",
            "district": district.upper() if district else (city.upper() if city else "MUMBAI"),
            "state": state.upper() if state else "MAHARASHTRA",
            "country": "INDIA",
            "lat": lat,
            "lng": lng
        }
