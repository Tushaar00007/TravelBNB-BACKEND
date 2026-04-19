import os
from pydantic import BaseModel
from typing import List
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables early
project_root = Path(__file__).parent.parent.parent
env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path)

class Settings(BaseModel):
    # MongoDB Config
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    DB_NAME: str = os.getenv("DB_NAME", "travelbnb")

    # Security Config
    # Check both JWT_SECRET (legacy/utility) and SECRET_KEY (standard)
    SECRET_KEY: str = os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY") or "dev_fallback_secret_key_change_in_production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 # 24 hours

    # CORS Config
    ALLOWED_ORIGINS: List[str] = os.getenv(
        "ALLOWED_ORIGINS", 
        "http://localhost:5173,http://localhost:5174,http://localhost:3000,http://127.0.0.1:5173,https://travel-bnb-frontend.vercel.app"
    ).split(",")

    # Application Info
    APP_NAME: str = "TravelBNB API"
    VERSION: str = "1.0.0"

settings = Settings()
