from pymongo import MongoClient
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Connect to MongoDB
# Try different env var names for robustness
MONGO_URL = os.getenv("MONGODB_URL") or os.getenv("MONGO_URI") or os.getenv("DATABASE_URL")
DB_NAME = os.getenv("DB_NAME", "travelbnb")

if not MONGO_URL:
    print("❌ ERROR: MONGODB_URL not found in .env")
    exit(1)

try:
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]

    # Update Shlok to host role
    # Case-insensitive update for email just in case
    target_email = "shloksukhija2505@gmail.com"
    
    # First, find current state
    user = db.users.find_one({"email": {"$regex": f"^{target_email}$", "$options": "i"}})
    
    if not user:
        print(f"❌ User not found with email: {target_email}")
    else:
        print(f"🔍 Found user: {user.get('name')} (Current Role: {user.get('role')})")
        
        result = db.users.update_one(
            {"_id": user["_id"]},
            {"$set": {"role": "host", "is_host": True}}
        )
        
        print(f"✅ Modified: {result.modified_count} user record(s)")
        
        # Verify
        updated_user = db.users.find_one({"_id": user["_id"]})
        print(f"✨ New Status -> role: {updated_user.get('role')}, is_host: {updated_user.get('is_host')}")

except Exception as e:
    print(f"❌ Connection error: {e}")
finally:
    if 'client' in locals():
        client.close()
