from fastapi import APIRouter, HTTPException
from app.database import db
from app.utils import hash_password, verify_password, create_access_token
from datetime import datetime

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