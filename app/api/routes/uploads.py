import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
import cloudinary
import cloudinary.uploader
from app.core.dependencies import get_current_user
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

# Initialize Cloudinary
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

MAX_SIZE_MB = 5
MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024

def validate_image(file: UploadFile):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are allowed")

    # Read the file to check size
    contents = file.file.read()
    if len(contents) > MAX_SIZE_BYTES:
        raise HTTPException(status_code=400, detail=f"Image size should not exceed {MAX_SIZE_MB}MB")
    
    # Seek back to start so it can be uploaded
    file.file.seek(0)
    return contents

@router.post("/property")
async def upload_property_image(file: UploadFile = File(...), user_id: str = Depends(get_current_user)):
    try:
        validate_image(file)
        result = cloudinary.uploader.upload(file.file, folder="travelbnb/properties")
        return {"url": result.get("secure_url")}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image upload failed: {str(e)}")

@router.post("/profile")
async def upload_profile_image(file: UploadFile = File(...), user_id: str = Depends(get_current_user)):
    try:
        validate_image(file)
        # Using user_id to overwrite their existing avatar to save space
        result = cloudinary.uploader.upload(
            file.file, 
            folder="travelbnb/profiles", 
            public_id=f"user_{user_id}",
            overwrite=True
        )
        return {"url": result.get("secure_url")}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image upload failed: {str(e)}")
