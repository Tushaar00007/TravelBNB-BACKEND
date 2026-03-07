from fastapi import APIRouter, HTTPException
from app.database import db
from app.utils import hash_password, verify_password, create_access_token
from datetime import datetime
from bson import ObjectId   # ← ADD THIS LINE (for MongoDB _id)

router = APIRouter()

@router.post("/register")
def register(user: dict):
    existing_user = db.users.find_one({"email": user["email"]})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already exists")

    hashed_pw = hash_password(user["password"])

    new_user = {
        "name": user["name"],
        "email": user["email"],
        "phone": user["phone"],
        "password": hashed_pw,
        "role": user.get("role", "guest"),
        "profile_image": "",
        "is_verified": False,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    db.users.insert_one(new_user)

    return {"message": "User registered successfully"}

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

