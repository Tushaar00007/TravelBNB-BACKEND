import cloudinary
import cloudinary.uploader
from pymongo import MongoClient
from dotenv import load_dotenv
import os
from bson import ObjectId

# Load environment variables
load_dotenv()

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)

# Connect to MongoDB
mongodb_url = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
db_name = os.getenv("DB_NAME", "travel_app")
client = MongoClient(mongodb_url)
db = client[db_name]

def migrate_collection(collection_name):
    docs = list(db[collection_name].find({}))
    print(f"\nMigrating {len(docs)} documents in '{collection_name}' collection...")
    
    migrated_count = 0
    skipped_count = 0
    error_count = 0
    
    for doc in docs:
        # Check both 'images' (list) and 'image' (string) fields
        images = doc.get("images", [])
        single_image = doc.get("image")
        
        changed = False
        
        # 1. Handle 'images' list
        if isinstance(images, list) and len(images) > 0:
            new_images = []
            for img in images:
                if isinstance(img, str) and img.startswith("data:image"):
                    print(f"  Uploading base64 image for: {doc.get('title', doc['_id'])}")
                    try:
                        result = cloudinary.uploader.upload(
                            img,
                            folder="travelbnb/listings",
                            resource_type="image",
                        )
                        new_images.append(result["secure_url"])
                        changed = True
                        print(f"    ✅ Uploaded: {result['secure_url']}")
                    except Exception as e:
                        print(f"    ❌ Failed to upload: {e}")
                        new_images.append(img)
                        error_count += 1
                else:
                    new_images.append(img)
            
            if changed:
                db[collection_name].update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"images": new_images}}
                )

        # 2. Handle 'image' string
        if isinstance(single_image, str) and single_image.startswith("data:image"):
            print(f"  Uploading single base64 image for: {doc.get('title', doc['_id'])}")
            try:
                result = cloudinary.uploader.upload(
                    single_image,
                    folder="travelbnb/listings",
                    resource_type="image",
                )
                db[collection_name].update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"image": result["secure_url"]}}
                )
                changed = True
                print(f"    ✅ Uploaded: {result['secure_url']}")
            except Exception as e:
                print(f"    ❌ Failed to upload: {e}")
                error_count += 1
        
        if changed:
            migrated_count += 1
        else:
            skipped_count += 1

    print(f"\nFinished migrating '{collection_name}':")
    print(f"  - Migrated: {migrated_count}")
    print(f"  - Skipped: {skipped_count}")
    print(f"  - Errors: {error_count}")

if __name__ == "__main__":
    # List of collections to migrate
    collections = ["homes", "properties", "crashpads_listings", "travel_buddy"]
    
    for coll in collections:
        if coll in db.list_collection_names():
            migrate_collection(coll)
        else:
            print(f"\nSkipping '{coll}' - collection not found.")
            
    client.close()
    print("\n🚀 Migration complete!")
