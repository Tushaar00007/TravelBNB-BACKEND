from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pathlib import Path

# Get project root (TRAVELBNB BACKEND)
project_root = Path(__file__).parent.parent
env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path)

from app.api.routes.auth import router as auth_router
from app.api.routes.homes import router as home_router
from app.api.routes.bookings import router as booking_router
from app.api.routes.ml import router as ml_router
from app.api.routes.reviews import router as review_router
from app.api.routes.uploads import router as upload_router
from app.api.routes.messages import router as message_router
from app.api.routes.trips import router as trip_router
from app.api.routes.expenses import router as expense_router
from app.api.routes.crashpads import router as crashpad_router
from app.api.routes.travel_buddy import router as travel_buddy_router
from app.api.routes.admin import router as admin_router
from app.api.routes.trust import router as trust_router
from app.api.routes.otp import router as otp_router
from app.api.routes.maps import router as maps_router
from app.api.routes.host import router as host_router
from app.api.routes.users import router as users_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# ✅ GLOBAL EXCEPTION HANDLER (Ensures CORS headers on 500 errors)
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"!!! CRITICAL SERVER ERROR: {str(exc)} !!!")
    import traceback
    print(traceback.format_exc())
    
    response = JSONResponse(
        status_code=500,
        content={"message": "Internal Server Error", "detail": str(exc)},
    )
    
    # Manually add CORS headers if the middleware skipped them due to the crash
    origin = request.headers.get("origin")
    if origin in [
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
        "http://localhost:3000", "http://127.0.0.1:3000"
    ]:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        
    return response

# Routers
app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])
app.include_router(home_router, prefix="/api/homes", tags=["Homes"])
app.include_router(booking_router, prefix="/api/bookings", tags=["Bookings"])
app.include_router(ml_router, prefix="/api/ml", tags=["ML Service"])
app.include_router(review_router, prefix="/api/reviews", tags=["Reviews"])
app.include_router(upload_router, prefix="/api/upload", tags=["Uploads"])
app.include_router(message_router, prefix="/api/messages", tags=["Messages"])
app.include_router(trip_router, prefix="/api/trips", tags=["Trips"])
app.include_router(expense_router, prefix="/api/trips", tags=["Expenses"])
app.include_router(crashpad_router, prefix="/api/crashpads", tags=["Crashpads"])
app.include_router(travel_buddy_router, prefix="/api/travel-buddies", tags=["Travel Buddy"])
app.include_router(admin_router, prefix="/api/admin", tags=["Admin"])
app.include_router(trust_router, prefix="/api/trust", tags=["Trust & Safety"])
app.include_router(otp_router, prefix="/api/otp", tags=["OTP Verification"])
app.include_router(maps_router, prefix="/api", tags=["Maps"])
app.include_router(host_router, prefix="/api/host", tags=["Host Management"])
app.include_router(users_router, prefix="/api/users", tags=["Users"])

# Removed 2dsphere index creation for scalar lat/lng migration as requested.
@app.get("/")
def root():
    return {"message": "Backend Running 🚀"}