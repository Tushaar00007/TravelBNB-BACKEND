import jwt
import os
from datetime import datetime, timedelta

from app.services.email_service import send_otp_email, send_verification_email

JWT_SECRET = os.getenv("JWT_SECRET", "supersecretkey123")


def generate_verification_token(email: str):
    payload = {
        "email": email,
        "exp": datetime.utcnow() + timedelta(hours=24),
        "type": "email_verification",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_verification_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        if payload.get("type") == "email_verification":
            return payload.get("email")
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    return None
