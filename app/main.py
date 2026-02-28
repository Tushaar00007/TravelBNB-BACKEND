from fastapi import FastAPI
from app.auth_routes import router as auth_router
from app.home_routes import router as home_router
app = FastAPI()

app.include_router(auth_router, prefix="/auth")
app.include_router(home_router, prefix="/homes", tags=["Homes"])


@app.get("/")
def root():
    return {"message": "Backend Running 🚀"}