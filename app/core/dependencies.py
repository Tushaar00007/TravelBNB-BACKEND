from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from typing import Optional
import os
from bson import ObjectId

SECRET_KEY = os.getenv("JWT_SECRET")
if not SECRET_KEY:
    print("!!! WARNING: JWT_SECRET not found in environment. Using insecure fallback !!!")
    SECRET_KEY = "dev_fallback_secret_key_change_in_production"
ALGORITHM = "HS256"

security = HTTPBearer()

# ── Original (unchanged) ─────────────────────────────────────
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_current_user_optional(credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False))):
    """Try to get user from token, but return None if missing/invalid (no 401)."""
    if not credentials:
        return None
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("user_id")
    except Exception:
        return None


# ── Extended — returns {id, role} for admin routes ───────────
def get_current_user_full(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Decodes JWT and fetches full user (id + role) from DB."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Lazy import to avoid circular imports
    from app.core.database import db
    user = db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return {
        "id": str(user["_id"]),
        "name": user.get("name", ""),
        "email": user.get("email", ""),
        "role": user.get("role", "guest"),
    }


# ── RBAC helper ───────────────────────────────────────────────
def require_role(allowed_roles: list):
    """
    Returns a FastAPI dependency that checks the caller's role.
    Usage: user=Depends(require_role(["super_admin"]))
    """
    def role_checker(current_user: dict = Depends(get_current_user_full)):
        if current_user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Requires one of: {allowed_roles}",
            )
        return current_user
    return role_checker

