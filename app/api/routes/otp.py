import random
import os
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from app.core.database import db
from pydantic import BaseModel
from app.utils.email import send_otp_email

router = APIRouter()

# In-memory store for development
# Structure: { "identifier": { "otp": "123456", "expires_at": datetime } }
otp_store = {}

class OTPSendRequest(BaseModel):
    identifier: str

class OTPVerifyRequest(BaseModel):
    identifier: str
    otp: str

def generate_otp():
    """Generate a 6-digit random OTP."""
    return str(random.randint(100000, 999999))


def is_email_identifier(identifier: str) -> bool:
    return "@" in identifier

@router.post("/send-otp")
async def send_otp(payload: OTPSendRequest):
    identifier = payload.identifier
    otp = generate_otp()
    
    # Store OTP with 5-minute expiry
    otp_store[identifier] = {
        "otp": otp,
        "expires_at": datetime.utcnow() + timedelta(minutes=5)
    }

    if is_email_identifier(identifier):
        email_sent = send_otp_email(identifier, otp, purpose="verification")
        if not email_sent:
            del otp_store[identifier]
            raise HTTPException(status_code=500, detail="Failed to send OTP email")
    else:
        print("\n" + "="*50)
        print(f"📱 OTP for {identifier}: {otp}")
        print("="*50 + "\n")

    response = {"message": "OTP sent successfully."}
    
    # Return OTP in response if in DEBUG mode
    if os.getenv("DEBUG") == "true":
        response["otp"] = otp
        response["message"] += " (Dev Mode)"
    
    return response

from app.utils.security import create_access_token

@router.post("/verify-otp")
async def verify_otp(payload: OTPVerifyRequest):
    identifier = payload.identifier
    otp = payload.otp
    
    record = otp_store.get(identifier)
    
    if not record:
        raise HTTPException(status_code=400, detail="No OTP found. Please request a new one.")
    
    if datetime.utcnow() > record["expires_at"]:
        if identifier in otp_store:
            del otp_store[identifier]
        raise HTTPException(status_code=400, detail="OTP has expired. Please request a new one.")
    
    if record["otp"] != otp:
        raise HTTPException(status_code=400, detail="Invalid OTP. Please try again.")
    
    # Clear OTP after successful verification
    del otp_store[identifier]
    
    # Check if user exists (by email or phone)
    user = db.users.find_one({
        "$or": [
            {"phone": identifier},
            {"email": identifier}
        ]
    })
    
    if user:
        # Update verification status
        update_field = "is_phone_verified" if "@" not in identifier else "is_email_verified"
        db.users.update_one(
            {"_id": user["_id"]},
            {"$set": {update_field: True}}
        )
        
        # Return a token for login
        token = create_access_token({"user_id": str(user["_id"])})
        return {
            "message": "Verified successfully", 
            "is_verified": True,
            "access_token": token,
            "user": {
                "id": str(user["_id"]),
                "name": user.get("name"),
                "email": user.get("email")
            }
        }
        
    return {"message": "OTP verified successfully", "is_verified": True}

@router.post("/login-otp")
async def login_otp(payload: OTPSendRequest):
    identifier = payload.identifier
    
    # Check if user exists
    user = db.users.find_one({
        "$or": [
            {"phone": identifier},
            {"email": identifier}
        ]
    })
    
    if not user:
        raise HTTPException(status_code=404, detail="No account found with this identifier.")
    
    otp = generate_otp()
    otp_store[identifier] = {
        "otp": otp,
        "expires_at": datetime.utcnow() + timedelta(minutes=5)
    }

    if is_email_identifier(identifier):
        email_sent = send_otp_email(identifier, otp, purpose="login")
        if not email_sent:
            del otp_store[identifier]
            raise HTTPException(status_code=500, detail="Failed to send OTP email")
    else:
        print("\n" + "="*50)
        print(f"🔑 LOGIN OTP for {identifier}: {otp}")
        print("="*50 + "\n")

    response = {"message": "OTP sent successfully."}
    
    if os.getenv("DEBUG") == "true":
        response["otp"] = otp
        response["message"] += " (Dev Mode)"
    
    return response
