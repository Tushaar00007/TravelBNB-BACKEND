from fastapi import APIRouter, HTTPException, Depends, Form, File, UploadFile
import cloudinary
import cloudinary.uploader
from app.core.database import db
from app.utils.security import hash_password, verify_password, create_access_token
from datetime import datetime, timedelta
import secrets
from app.utils.email import send_verification_email, generate_verification_token, verify_verification_token
from app.core.dependencies import get_current_user
from bson import ObjectId
import os
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

# Initialize Cloudinary
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

router = APIRouter()

@router.post("/register")
async def register(
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    password: str = Form(...),
    profile_image: UploadFile = File(None)
):
    # Check if email exists
    if db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already exists")
    
    # Check if phone exists (to prevent 500 DuplicateKeyError)
    if db.users.find_one({"phone": phone}):
        raise HTTPException(status_code=400, detail="Phone number already registered")

    hashed_pw = hash_password(password)

    # Handle Profile Image Upload
    image_url = ""
    if profile_image:
        try:
            result = cloudinary.uploader.upload(profile_image.file, folder="travelbnb/profiles")
            image_url = result.get("secure_url")
        except Exception as e:
            print(f"Cloudinary Error: {e}")

    new_user = {
        "name": name,
        "email": email,
        "phone": phone,
        "password": hashed_pw,
        "role": "guest",
        "profile_image": image_url,
        "is_verified": False,
        "id_document": "",
        "selfie_image": "",
        "auth_provider": "email",
        "is_email_verified": False,
        "is_phone_verified": False,
        "email_verification_token": secrets.token_urlsafe(32),
        "token_expiry": datetime.utcnow() + timedelta(hours=24),
        "trust_score": 0,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    db.users.insert_one(new_user)
    
    # Send Verification Email
    token = generate_verification_token(email)
    email_sent = send_verification_email(email, name, token)

    if not email_sent:
        print(f"Verification email send failed for {email}")

    return {"message": "User registered successfully. Please check your email to verify your account."}

@router.post("/login")
def login(user: dict):
    db_user = db.users.find_one({"email": user["email"]})

    if not db_user:
        raise HTTPException(status_code=400, detail="Invalid credentials")

    if not verify_password(user["password"], db_user["password"]):
        raise HTTPException(status_code=400, detail="Invalid credentials")

    token = create_access_token({"user_id": str(db_user["_id"])})

    return {"access_token": token}


# ========================
# GOOGLE LOGIN ROUTE
# ========================
@router.post("/google-login")
def google_login(payload: dict):
    try:
        token = payload.get("token")
        phone = payload.get("phone")
        if not token:
            raise HTTPException(status_code=400, detail="Token is required")

        # Verify the Google ID token
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        id_info = id_token.verify_oauth2_token(token, google_requests.Request(), client_id)

        email = id_info.get("email")
        name = id_info.get("name")
        picture = id_info.get("picture")

        # Check if user exists
        db_user = db.users.find_one({"email": email})

        if not db_user:
            # User doesn't exist. If no phone provided, we need it.
            if not phone:
                return {"needs_phone": True}
            
            # Create new user
            new_user = {
                "name": name,
                "email": email,
                "phone": phone,
                "profile_image": picture,
                "role": "guest",
                "auth_provider": "google",
                "is_email_verified": True,
                "is_phone_verified": False,
                "is_verified": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            result = db.users.insert_one(new_user)
            user_id = str(result.inserted_id)
        else:
            user_id = str(db_user["_id"])
            # If user exists but fields are missing/outdated
            update_fields = {}
            if not db_user.get("phone") and phone:
                update_fields["phone"] = phone
            if not db_user.get("auth_provider"):
                update_fields["auth_provider"] = "google"
            if not db_user.get("is_email_verified"):
                update_fields["is_email_verified"] = True
            
            if update_fields:
                db.users.update_one({"_id": db_user["_id"]}, {"$set": update_fields})

        # Create our own JWT
        jwt_token = create_access_token({"user_id": user_id})

        return {
            "access_token": jwt_token,
            "user": {
                "id": user_id,
                "name": name,
                "email": email,
                "profile_image": picture
            }
        }

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Google token")
    except Exception as e:
        print(f"❌ Google login error: {e}")
        raise HTTPException(status_code=500, detail="Google authentication failed")


# ========================
# NEW ROUTE - THIS FIXES THE 404 ERROR
# ========================
@router.get("/user/{user_id}")
def get_user(user_id: str):
    try:
        # Convert string ID to MongoDB ObjectId
        user = db.users.find_one({"_id": ObjectId(user_id)})

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Remove sensitive data before sending to frontend
        user.pop("password", None)

        # Convert _id to string so React can read it easily
        user["_id"] = str(user["_id"])

        print(f"✅ User fetched for navbar: {user['name']}")  # you will see this in terminal
        return user

    except Exception as e:
        print(f"❌ Backend error fetching user: {e}")
        raise HTTPException(status_code=404, detail="User not found")


# ========================
# UPDATE USER ROUTE
# ========================
@router.put("/user/{user_id}")
def update_user(user_id: str, payload: dict):
    try:
        # Find user
        db_user = db.users.find_one({"_id": ObjectId(user_id)})
        if not db_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Prepare update data (only allow specific fields)
        update_data = {}
        if "name" in payload:
            update_data["name"] = payload["name"]
        if "phone" in payload:
            update_data["phone"] = payload["phone"]
        if "address" in payload:
            update_data["address"] = payload["address"]
        if "preferences" in payload:
            update_data["preferences"] = payload["preferences"]
        if "profile_picture" in payload:
            update_data["profile_picture"] = payload["profile_picture"]
        if "id_document" in payload:
            update_data["id_document"] = payload["id_document"]
        if "selfie_image" in payload:
            update_data["selfie_image"] = payload["selfie_image"]
        
        if update_data:
            update_data["updated_at"] = datetime.utcnow()
            
            # Update in DB
            db.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": update_data}
            )

        # Fetch updated user to return
        updated_user = db.users.find_one({"_id": ObjectId(user_id)})
        updated_user.pop("password", None)
        updated_user["_id"] = str(updated_user["_id"])

        print(f"✅ User updated: {updated_user['name']}")
        return {"message": "Profile updated successfully", "user": updated_user}

    except Exception as e:
        print(f"❌ Backend error updating user: {e}")
        raise HTTPException(status_code=500, detail="Failed to update user profile")


# ========================
# UPDATE PASSWORD ROUTE
# ========================
@router.put("/user/{user_id}/password")
def update_password(user_id: str, payloads: dict):
    try:
        db_user = db.users.find_one({"_id": ObjectId(user_id)})
        if not db_user:
            raise HTTPException(status_code=404, detail="User not found")

        current_password = payloads.get("currentPassword")
        new_password = payloads.get("newPassword")

        if not verify_password(current_password, db_user["password"]):
            raise HTTPException(status_code=400, detail="Incorrect current password")

        hashed_new_pw = hash_password(new_password)
        db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {
                "password": hashed_new_pw,
                "updated_at": datetime.utcnow()
            }}
        )

        return {"message": "Password updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Backend error updating password: {e}")
        raise HTTPException(status_code=500, detail="Failed to update password")

# ========================
# EMAIL VERIFICATION
# ========================
@router.get("/verify-email")
def verify_email(token: str):
    email = verify_verification_token(token)

    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user = db.users.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.get("is_email_verified"):
        return {"message": "Email already verified"}

    db.users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "is_email_verified": True,
                "trust_score": user.get("trust_score", 0) + 10,
                "updated_at": datetime.utcnow()
            }
        }
    )
    return {"message": "Email verified! +10 Trust Points earned."}

@router.post("/resend-verification")
def resend_verification(payload: dict = None, user_id: str = Depends(get_current_user)):
    user = db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.get("auth_provider") == "google":
        return {"message": "Google users are automatically verified"}
    
    if user.get("is_email_verified"):
        return {"message": "Email is already verified"}

    token = generate_verification_token(user["email"])
    email_sent = send_verification_email(user["email"], user["name"], token)

    if not email_sent:
        raise HTTPException(status_code=500, detail="Failed to send verification email")
    
    return {"message": "Verification email resent"}
