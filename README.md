# TravelBNB — Backend API

FastAPI backend for TravelBNB, an AI-powered travel booking and planning platform. Handles authentication, bookings, listings, messaging, admin operations, and proxies ML requests to the AI service.

This is one of three services that make up TravelBNB:
- **Frontend** — [travel-bnb-frontend](https://github.com/Tushaar00007/travel-bnb-frontend) (React + Vite)
- **Backend** (this repo) — FastAPI + MongoDB
- **ML Service** — [ai-travel-planner](https://github.com/Tushaar00007/ai-travel-planner) (FastAPI + Python ML)

---

## Live Deployment

| Service | URL |
|---------|-----|
| Backend API (Render) | https://travelbnb-backend.onrender.com |
| Frontend | https://travel-bnb-frontend.vercel.app |
| ML Service | https://ai-travel-planner-txji.onrender.com |

---

## Project Structure

```
travelbnb-backend/
├── app/
│   ├── main.py                 # FastAPI app, CORS, router registration
│   ├── core/
│   │   └── config.py           # Settings, ALLOWED_ORIGINS, DB config
│   ├── routers/
│   │   ├── auth.py             # Register, login, user CRUD
│   │   ├── bookings.py         # Booking creation and approval
│   │   ├── crashpads.py        # Crashpad CRUD
│   │   ├── ml.py               # ML service proxy
│   │   ├── itinerary.py        # Save/fetch itineraries, PDF export
│   │   ├── admin.py            # Admin stats and user management
│   │   └── messages.py         # Host-guest messaging
│   ├── services/
│   │   └── ml_service.py       # Proxy client for ML service
│   ├── models/                 # Pydantic models
│   ├── db/                     # MongoDB client
│   └── utils/
│       └── auth.py             # JWT encoding/decoding
├── migrations/                 # One-off DB fix scripts
│   ├── fix_role.py
│   ├── migrate_images.py
│   ├── fix_coords.py
│   └── make_superadmin.py
├── requirements.txt
└── .env                        # MONGO_URI, JWT_SECRET, CLOUDINARY, etc.
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | FastAPI (Python 3.11) |
| Database | MongoDB (`travel_app` database) |
| Authentication | JWT (Bearer tokens) + Google OAuth |
| Image Storage | Cloudinary |
| ML Integration | HTTP proxy to Python ML service |
| CORS | `CORSMiddleware` with env-configurable origins |
| Deployment | Render |

---

## Environment Setup

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env` file (see variables below), then:

```bash
uvicorn app.main:app --reload --port 8000
```

### Required Environment Variables

```env
# Database
MONGO_URI=mongodb://localhost:27017
DB_NAME=travel_app

# Auth
JWT_SECRET=your-secret-here
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440

# Cloudinary
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...

# Google OAuth
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_CALLBACK_URL=http://localhost:8000/api/auth/google/callback

# ML Service
ML_BASE_URL=http://localhost:9000

# CORS (comma-separated, no spaces)
ALLOWED_ORIGINS=http://localhost:5173,https://travel-bnb-frontend.vercel.app

# Debug
DEBUG=true
```

---

## API Endpoints

All routes are prefixed with `/api`.

### Auth — `/api/auth/*`

| Method | Endpoint | Description | Body |
|--------|----------|-------------|------|
| `POST` | `/api/auth/register` | Register new user | `{ fullName, email, password, role }` |
| `POST` | `/api/auth/login` | Login with email and password | `{ email, password }` |
| `GET` | `/api/auth/me` | Get current user profile | — |
| `GET` | `/api/auth/user/{user_id}` | Get user by ID | — |
| `PUT` | `/api/auth/user/{user_id}` | Update user profile | `{ fullName?, phone?, bio? }` |

**Roles:** `user` | `host` | `admin` | `super_admin`

---

### Bookings — `/api/bookings/*`

| Method | Endpoint | Description | Body |
|--------|----------|-------------|------|
| `POST` | `/api/bookings/` | Create a new booking | `BookingRequest` |
| `GET` | `/api/bookings/user/all` | Get all bookings for current user | — |
| `PATCH` | `/api/bookings/{booking_id}/approve` | Host approves booking | — |

**BookingRequest:**
```json
{
  "propertyId": "...",
  "hostId": "...",
  "checkIn": "2026-05-01",
  "checkOut": "2026-05-05",
  "guests": 2,
  "totalPrice": 12000
}
```

---

### Crashpads — `/api/crashpads/*`

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/crashpads/` | List all crashpads |
| `POST` | `/api/crashpads/` | Create a new crashpad listing |

---

### Admin — `/api/admin/*`

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/admin/stats` | Dashboard stats (users, listings, bookings, revenue) |
| `GET` | `/api/admin/users` | List all users |
| `GET` | `/api/admin/listings` | List all property listings |
| `GET` | `/api/admin/bookings` | List all bookings |
| `GET` | `/api/admin/admins` | List admin accounts |
| `POST` | `/api/admin/create` | Create new admin account |
| `DELETE` | `/api/admin/admins/{admin_id}` | Remove admin account |

Requires `admin` or `super_admin` role.

---

### Messaging — `/api/messages/*`

| Method | Endpoint | Description | Body |
|--------|----------|-------------|------|
| `GET` | `/api/messages/{currentUserId}/{otherId}` | Fetch conversation | — |
| `POST` | `/api/messages/send` | Send a message | `{ senderId, receiverId, text }` |

Booking metadata (dates, guest count) is embedded in message text and extracted via regex on the frontend.

---

### ML Proxy — `/api/ml/*` and `/api/itinerary/*`

| Method | Endpoint | Description | Body |
|--------|----------|-------------|------|
| `POST` | `/api/ml/generate` | Generate travel itinerary | `ItineraryRequest` |
| `POST` | `/api/ml/chat` | Chat with travel assistant | `{ message, context }` |
| `POST` | `/api/ml/download_pdf` | Download itinerary as PDF | `{ itineraryId }` |
| `POST` | `/api/itinerary/save` | Save generated itinerary | `ItineraryData` |
| `GET` | `/api/itinerary/pdf/{itinerary_id}` | Fetch saved PDF | — |

**ItineraryRequest:**
```json
{
  "destination": "Goa",
  "budget": 25000,
  "days": 4,
  "travelers": 2,
  "preferences": ["beach", "nightlife", "food"],
  "travelMode": "flight"
}
```

These endpoints proxy to the ML service at `ML_BASE_URL`. The frontend never calls the ML service directly.

---

## Authentication

All protected endpoints require:
```
Authorization: Bearer <accessToken>
```

Tokens are issued by `/api/auth/login` and expire after `JWT_EXPIRE_MINUTES` (default 1440 = 24 hours). The frontend stores tokens in localStorage and attaches them via an axios interceptor.

---

## CORS Configuration

Configured in `app/main.py` via `CORSMiddleware`. Origins are read from the `ALLOWED_ORIGINS` environment variable (comma-separated):

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

For Vercel preview deployments, consider switching to `allow_origin_regex` to match preview URLs dynamically.

---

## Database Schema

MongoDB database: `travel_app`

Key collections:
- `users` — user accounts, roles, profiles
- `properties` and `homes` — property listings (both collections queried with `$or` due to legacy data)
- `bookings` — booking records
- `messages` — host-guest conversations
- `itineraries` — saved AI-generated trip plans

Mixed camelCase and snake_case field names exist across collections; queries use `$or` to cover all variants.

---

## Deployment (Render)

1. New Web Service → connect this repo
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add all environment variables from `.env`
5. Set `ALLOWED_ORIGINS` to include production frontend URL
6. Set `ML_BASE_URL` to the deployed ML service URL

Free tier note: Render free tier sleeps after 15 min of inactivity. First request after sleep takes 30–60 seconds.

---

## Migrations

One-off DB scripts in `migrations/`:

- `fix_role.py` — corrects role field values
- `migrate_images.py` — moves base64 images from MongoDB to Cloudinary
- `fix_coords.py` — fills missing geocoordinates
- `make_superadmin.py` — promotes a user to super_admin
- `fix_password.py` — resets password hashes

Run with: `python migrations/script_name.py`

---

## Key Design Decisions

- **ML service is proxied** — the frontend never calls the ML service directly. All ML requests go through `/api/ml/*` which forwards to the ML service. Keeps CORS config simple and allows the backend to add auth, caching, and rate limiting.
- **Router registration is explicit** — every router must be registered in `main.py` via `app.include_router()` or endpoints silently 404.
- **Field name normalization via `$or`** — mixed camelCase/snake_case across collections requires queries that match both.
- **JWT stored in localStorage** — accepted trade-off for simplicity; consider httpOnly cookies for production hardening.
- **CORS origins via env var** — `ALLOWED_ORIGINS` is comma-separated in `.env` to avoid hardcoded lists.
