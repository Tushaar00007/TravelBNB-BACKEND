from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

app = FastAPI()


# Allow frontend (React) to call backend
origins = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
]


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Routers
app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(home_router, prefix="/homes", tags=["Homes"])
app.include_router(booking_router, prefix="/bookings", tags=["Bookings"])
app.include_router(ml_router, prefix="/ml", tags=["ML Service"])
app.include_router(review_router, prefix="/api/reviews", tags=["Reviews"])
app.include_router(upload_router, prefix="/upload", tags=["Uploads"])
app.include_router(message_router, prefix="/api/messages", tags=["Messages"])
app.include_router(trip_router, prefix="/api/trips", tags=["Trips"])
app.include_router(expense_router, prefix="/api/trips", tags=["Expenses"])
app.include_router(crashpad_router, prefix="/crashpads", tags=["Crashpads"])
app.include_router(travel_buddy_router, prefix="/travel-buddies", tags=["Travel Buddy"])

@app.get("/")
def root():
    return {"message": "Backend Running 🚀"}