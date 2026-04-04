from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "travelbnb")

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

def migrate_collection(collection_name):
    print(f"--- Migrating {collection_name} ---")
    docs = list(db[collection_name].find({"location.coordinates": {"$exists": True}}))
    print(f"Found {len(docs)} documents to migrate.")
    
    count = 0
    for doc in docs:
        coords = doc["location"].get("coordinates", {})
        if coords.get("type") == "Point" and "coordinates" in coords:
            lng, lat = coords["coordinates"]
            
            # Update the document: remove coordinates, add lat/lng
            db[collection_name].update_one(
                {"_id": doc["_id"]},
                {
                    "$set": {
                        "location.lat": lat,
                        "location.lng": lng,
                        "location.city": doc["location"].get("city", "").upper(),
                        "location.state": doc["location"].get("state", "").upper(),
                        "location.country": doc["location"].get("country", "INDIA").upper(),
                    },
                    "$unset": {"location.coordinates": ""}
                }
            )
            count += 1
            
    print(f"Successfully migrated {count} documents in {collection_name}.")

if __name__ == "__main__":
    migrate_collection("crashpads_listings")
    migrate_collection("homes")
    print("\n✅ Migration complete!")
