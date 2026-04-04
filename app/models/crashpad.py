from pydantic import BaseModel, Field, validator
from typing import List, Optional
from datetime import datetime

class Location(BaseModel):
    address_line: str
    flat_suite: Optional[str] = None
    landmark: Optional[str] = None
    district: str
    city: str
    state: str
    country: str = "INDIA"
    pincode: str
    lat: float
    lng: float

    @validator("district", "city", "state", pre=True)
    def to_uppercase(cls, v):
        if isinstance(v, str):
            return v.upper()
        return v

class CrashpadCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    stay_type: str  # couch | shared | private
    flat: Optional[str] = None
    address: str
    landmark: Optional[str] = None
    locality: Optional[str] = None
    district: Optional[str] = None
    city: str
    state: str
    country: str = "INDIA"
    pincode: str
    lat: float
    lng: float
    max_guests: int = 1
    max_nights: int = 3
    host_bio: Optional[str] = ""
    interests: List[str] = []
    languages: List[str] = []
    house_rules: List[str] = []
    preferences: List[str] = []
    is_free: bool = True
    price_per_night: float = 0.0
    images: List[str] = []

class CrashpadResponse(BaseModel):
    id: str
    crashpad_id: str
    host_id: str
    title: str
    description: str
    stay_type: str
    location: Location
    max_guests: int
    max_nights: int
    host_bio: str
    interests: List[str]
    languages: List[str]
    house_rules: List[str]
    preferences: List[str]
    is_free: bool
    price_per_night: float
    images: List[str]
    is_active: bool
    status: str
    created_at: datetime
    updated_at: datetime
