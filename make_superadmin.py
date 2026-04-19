from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "travel_app")
USER_ID = "69bef69b26a0c35604d5d5ef"

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

result = db.users.update_one(
    {"_id": ObjectId(USER_ID)},
    {"$set": {
        "role": "super_admin",
        "is_host": True,
        "is_verified": True,
        "updated_at": datetime.utcnow()
    }}
)

if result.matched_count == 0:
    print("User not found")
else:
    user = db.users.find_one({"_id": ObjectId(USER_ID)})
    print(f"Updated: {user['name']} ({user['email']})")
    print(f"  role: {user['role']}")
    print(f"  is_host: {user['is_host']}")

client.close()
