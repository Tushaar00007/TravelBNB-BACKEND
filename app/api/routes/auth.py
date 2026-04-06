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
from app.models.schemas import LoginSchema, ForgotPasswordRequest, ResetPasswordRequest
from app.services.email_service import send_password_reset_email

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
async def login(credentials: LoginSchema):
    try:
        print(f"DEBUG: Login attempt for: {credentials.email}")
        
        # Find user
        db_user = db.users.find_one({"email": credentials.email})
        print(f"DEBUG: User found in DB: {db_user is not None}")
        
        if not db_user:
            print(f"DEBUG: No user found with email {credentials.email}")
            raise HTTPException(
                status_code=401, 
                detail="Invalid email or password"
            )
        
        # Verify password
        stored_password = db_user.get("password", "")
        print(f"DEBUG: Stored hash starts with: {stored_password[:10]}")
        
        # Check if password is valid bcrypt hash format
        if not (stored_password.startswith("$2b$") or stored_password.startswith("$2a$")):
            print(f"INVALID HASH FORMAT for {credentials.email}")
            raise HTTPException(
                status_code=401,
                detail="Account password format is outdated. Please reset your password using Forgot Password."
            )
        
        try:
            is_valid = verify_password(credentials.password, stored_password)
            print(f"DEBUG: Password verification result: {is_valid}")
        except Exception as hash_err:
            print(f"Hash verification error for {credentials.email}: {hash_err}")
            raise HTTPException(
                status_code=401,
                detail="Account password is corrupted. Please use Forgot Password to set a new one."
            )
        
        if not is_valid:
            print(f"DEBUG: Password mismatch for user {credentials.email}")
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )
        
        # Create access token
        user_id = str(db_user["_id"])
        token = create_access_token({"user_id": user_id})
        print(f"DEBUG: Access token generated for user_id: {user_id}")
        
        # Improved host detection: Include admins/super_admins and users with listings in any collection
        user_id_str = str(db_user["_id"])
        user_oid = db_user["_id"]
        
        id_query = {
            "$or": [
                {"host_id": user_oid},
                {"host_id": user_id_str},
                {"user_id": user_oid},
                {"user_id": user_id_str},
            ]
        }
        
        has_home = db.properties.find_one(id_query) is not None
        has_crashpad = db.crashpads_listings.find_one(id_query) is not None
        has_buddy = db.buddy_applications.find_one(id_query) is not None
        
        role = db_user.get("role", "guest")
        is_host = (
            role in ["host", "super_admin", "admin"] or
            has_home or has_crashpad or has_buddy
        )
        
        print(f"DEBUG: is_host for {db_user.get('email')}: {is_host} (role:{role} home:{has_home} crashpad:{has_crashpad})")
        
        response_data = {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": user_id_str,
                "name": db_user.get("name", ""),
                "email": db_user.get("email", ""),
                "profile_image": db_user.get("profile_image", "") or db_user.get("avatar", ""),
                "is_host": is_host,
                "role": role,
                "is_verified": db_user.get("is_verified", False),
            }
        }
        print(f"DEBUG: Login successful for {credentials.email}")
        return response_data
        
    except HTTPException:
        # Re-raise HTTP exceptions to maintain specific error codes
        raise
    except Exception as e:
        import traceback
        print(f"ERROR: Unexpected login crash: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500, 
            detail=f"Internal Server Error: {str(e)}"
        )


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

        # Simple role-based host detection
        is_host = db_user.get("role") == "host" if db_user else False

        return {
            "access_token": jwt_token,
            "user": {
                "id": user_id,
                "name": name,
                "email": email,
                "profile_image": picture,
                "is_host": is_host,
                "role": db_user.get("role", "guest") if db_user else "guest"
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
async def get_user(user_id: str):
    try:
        from bson import ObjectId
        import traceback
        
        print(f"Fetching user: {user_id}")
        
        # Try to find by ObjectId
        try:
            user = db.users.find_one({"_id": ObjectId(user_id)})
        except Exception as oid_err:
            print(f"ObjectId conversion failed: {oid_err}")
            user = db.users.find_one({"_id": user_id})
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Improved host detection logic
        user_id_str = str(user["_id"])
        user_oid = user["_id"]
        
        id_query = {
            "$or": [
                {"host_id": user_oid},
                {"host_id": user_id_str},
                {"user_id": user_oid},
                {"user_id": user_id_str},
            ]
        }
        
        has_home = db.properties.find_one(id_query) is not None
        has_crashpad = db.crashpads_listings.find_one(id_query) is not None
        has_buddy = db.buddy_applications.find_one(id_query) is not None
        
        role = user.get("role", "guest")
        is_host = (
            role in ["host", "super_admin", "admin"] or
            has_home or has_crashpad or has_buddy
        )
        print(f"User found: {user.get('name')}, is_host: {is_host}")
        
        return {
            "id": user_id_str,
            "name": user.get("name", ""),
            "email": user.get("email", ""),
            "phone": user.get("phone", ""),
            "avatar": user.get("profile_image", "") or user.get("avatar", ""),
            "is_host": is_host,
            "role": role,
            "is_verified": user.get("is_verified", False),
            "created_at": str(user.get("created_at", "")),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching user {user_id}:")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/me")
async def get_me(user_id: str = Depends(get_current_user)):
    try:
        user = db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        # Improved host detection logic
        user_id_str = str(user["_id"])
        user_oid = user["_id"]
        
        id_query = {
            "$or": [
                {"host_id": user_oid},
                {"host_id": user_id_str},
                {"user_id": user_oid},
                {"user_id": user_id_str},
            ]
        }
        
        has_home = db.properties.find_one(id_query) is not None
        has_crashpad = db.crashpads_listings.find_one(id_query) is not None
        has_buddy = db.buddy_applications.find_one(id_query) is not None
        
        role = user.get("role", "guest")
        is_host = (
            role in ["host", "super_admin", "admin"] or
            has_home or has_crashpad or has_buddy
        )
        
        return {
            "id": user_id_str,
            "name": user.get("name", ""),
            "email": user.get("email", ""),
            "profile_image": user.get("profile_image", "") or user.get("avatar", ""),
            "is_host": is_host,
            "role": role,
        }
    except Exception as e:
        print(f"❌ /me error: {e}")
        raise HTTPException(status_code=401, detail=str(e))


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

# ========================
# FORGOT & RESET PASSWORD
# ========================
@router.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    try:
        email = request.email.lower()
        print(f"DEBUG: Forgot password (DEV MODE) for: {email}")
        
        user = db.users.find_one({"email": email})
        
        if not user:
            print(f"DEBUG: [Dev Mode] User not found: {email}")
            return {
                "message": "If account exists, reset link generated",
                "reset_link": None,
                "dev_mode": True
            }
        
        # Generate token
        token = secrets.token_urlsafe(32)
        expiry = datetime.utcnow() + timedelta(hours=1)
        
        # Clear old tokens and save new one
        db.password_resets.delete_many({"email": email})
        db.password_resets.insert_one({
            "email": email,
            "token": token,
            "expiry": expiry,
            "used": False,
            "created_at": datetime.utcnow()
        })
        
        FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
        reset_link = f"{FRONTEND_URL.rstrip('/')}/reset-password?token={token}"
        
        print(f"DEBUG: [Dev Mode] Reset link for {email}: {reset_link}")
        
        return {
            "message": "Reset link generated (Dev Mode)",
            "reset_link": reset_link,
            "dev_mode": True,
            "expires_in": "1 hour"
        }
        
    except Exception as e:
        print(f"ERROR: Forgot password dev-mode logic failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest):
    try:
        token = request.token
        new_password = request.new_password
        
        print(f"DEBUG: Reset attempt with token: {token[:10]}...")
        
        # Validate token
        reset_record = db.password_resets.find_one({
            "token": token,
            "used": False
        })
        
        if not reset_record:
            print(f"DEBUG: Invalid or used token: {token[:10]}...")
            raise HTTPException(status_code=400, detail="Invalid or expired reset link")
            
        if datetime.utcnow() > reset_record["expiry"]:
            print(f"DEBUG: Expired token for {reset_record['email']}")
            raise HTTPException(status_code=400, detail="Reset link has expired")
            
        # Hash and double-verify before saving (Robustness fix)
        hashed_pw = hash_password(new_password)
        print(f"DEBUG: New hash generated for {reset_record['email']}: {hashed_pw[:20]}...")
        
        # Pre-save verification test
        if not verify_password(new_password, hashed_pw):
            print(f"CRITICAL: Password hashing verification failed for {reset_record['email']}!")
            raise HTTPException(status_code=500, detail="Internal hashing error. Please try again.")

        # Update in DB
        result = db.users.update_one(
            {"email": reset_record["email"]},
            {"$set": {
                "password": hashed_pw,
                "updated_at": datetime.utcnow()
            }}
        )
        print(f"DEBUG: Updated {result.modified_count} user password record")
        
        # Mark token as used
        db.password_resets.update_one(
            {"token": token},
            {"$set": {"used": True}}
        )
        
        print(f"SUCCESS: Password reset complete for {reset_record['email']}")
        return {"message": "Password updated successfully. You can now login."}
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"ERROR: Reset password system failure: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal server error during password reset")
