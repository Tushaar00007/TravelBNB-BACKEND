from pydantic import BaseModel
from typing import Optional

class LoginSchema(BaseModel):
    email: str
    password: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class ForgotPasswordRequest(BaseModel):
    email: str

class BookingRequestSchema(BaseModel):
    property_id: str
    host_id: str
    guest_id: Optional[str] = None
    check_in: str
    check_out: str
    guests: int = 1
    total_price: float
    status: Optional[str] = "pending"

class PaymentConfirmation(BaseModel):
    booking_request_id: str
    payment_method: str
    amount: float
    transaction_id: str
