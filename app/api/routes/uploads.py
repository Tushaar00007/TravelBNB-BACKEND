import os
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

# Initialize Cloudinary
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)

MAX_SIZE_MB = 5
MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024

@router.post("/images")
async def upload_images(files: List[UploadFile] = File(...)):
    try:
        print(f"DEBUG: Files received: {len(files)}")
        for f in files:
            print(f"  - {f.filename} | {f.content_type} | size: unknown")
        
        results = []
        for file in files:
            content = await file.read()
            print(f"DEBUG: Read {len(content)} bytes from {file.filename}")
            
            if len(content) > MAX_SIZE_BYTES:
                raise HTTPException(status_code=400, detail=f"File {file.filename} exceeds {MAX_SIZE_MB}MB limit")

            upload_result = cloudinary.uploader.upload(
                content,
                folder="travelbnb/listings",
                resource_type="auto",
                public_id=f"listing_{file.filename.split('.')[0]}_{os.urandom(4).hex()}",
                overwrite=True,
                transformation=[
                    {"width": 1200, "crop": "limit", "quality": "auto:good"}
                ]
            )
            
            print(f"DEBUG: Cloudinary URL: {upload_result['secure_url']}")
            results.append({
                "url": upload_result["secure_url"],
                "public_id": upload_result["public_id"],
            })
        
        return {"images": results, "count": len(results)}
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print("DEBUG: UPLOAD ERROR:")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/image")
async def upload_single_image(file: UploadFile = File(...)):
    try:
        content = await file.read()
        result = cloudinary.uploader.upload(
            content,
            folder="travelbnb/listings",
            resource_type="auto",
        )
        return {
            "url": result["secure_url"],
            "public_id": result["public_id"],
        }
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/base64")
async def upload_base64_image(data: dict):
    try:
        base64_str = data.get("image", "")
        if not base64_str:
            raise HTTPException(status_code=400, detail="No image data provided")
        
        result = cloudinary.uploader.upload(
            base64_str,
            folder="travelbnb/listings",
            resource_type="image",
        )
        return {
            "url": result["secure_url"],
            "public_id": result["public_id"],
        }
    except Exception as e:
        print(f"Base64 upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
