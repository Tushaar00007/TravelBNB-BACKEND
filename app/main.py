from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth_routes import router as auth_router
from app.home_routes import router as home_router
from app.booking_routes import router as booking_router
from app.ml_routes import router as ml_router
from app.review_routes import router as review_router
from app.upload_routes import router as upload_router

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

@app.get("/")
def root():
    return {"message": "Backend Running 🚀"}