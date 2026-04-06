from pymongo import MongoClient
import bcrypt
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Connect to MongoDB
MONGO_URL = os.getenv("MONGODB_URL") or os.getenv("MONGO_URI") or os.getenv("DATABASE_URL")
DB_NAME = os.getenv("DB_NAME") or "travelbnb"

print(f"Connecting to: {MONGO_URL[:20]}... (DB: {DB_NAME})")

try:
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    
    # Use bcrypt directly to avoid passlib attribute errors
    # bcrypt usage:
    # hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    # verify = bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    
    # Target User
    email = "shloksukhija2505@gmail.com"
    user = db.users.find_one({"email": email})
    
    if user:
        print(f"✅ User found: {user.get('name')}")
        stored_password = user.get('password', 'NOT SET')
        
        # Force reset to working state
        new_password = "Shlok123"
        print(f"Force resetting password to: {new_password}")
        
        new_hash = bcrypt.hashpw(
            new_password.encode('utf-8'), 
            bcrypt.gensalt()
        ).decode('utf-8')
        
        print(f"New hash: {new_hash[:30]}...")
        
        # Verify the new hash before saving
        verify_local = bcrypt.checkpw(
            new_password.encode('utf-8'),
            new_hash.encode('utf-8')
        )
        print(f"Local verification success: {verify_local}")
        
        if not verify_local:
            print("❌ LOCAL HASH VERIFICATION FAILED. ABORTING.")
            exit(1)
            
        # Update user in DB
        db.users.update_one(
            {"email": email},
            {"$set": {
                "password": new_hash,
                "updated_at": "2026-04-06T10:38:00Z"
            }}
        )
        print(f"✅ Database updated for {email}")
        
        # Final verify
        updated_user = db.users.find_one({"email": email})
        verify_final = bcrypt.checkpw(
            new_password.encode('utf-8'),
            updated_user["password"].encode('utf-8')
        )
        print(f"✅ FINAL DB VERIFICATION: {verify_final}")
            
    else:
        print(f"❌ User not found: {email}")

except Exception as e:
    import traceback
    print(f"❌ Script failed: {e}")
    traceback.print_exc()
finally:
    if 'client' in locals():
        client.close()
