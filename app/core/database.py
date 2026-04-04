import os
import certifi
from pymongo import MongoClient

client = MongoClient(
    os.getenv("MONGO_URI"),
    tlsCAFile=certifi.where()
)

db = client[os.getenv("DB_NAME")]
