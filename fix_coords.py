import pandas as pd
import requests
import time

# Update this path to where your dataset is
df = pd.read_csv('/Users/tushaarrohatgi/Developer/planner/Ml_model/dataset/tourism_dataset_enriched_v2_updated.csv')

API_KEY = "AIzaSyDhABgndaxZ-Bk_hgW-lpl9dW3cyEMXzSo"

def get_real_coords(place_name, city, state):
    try:
        url = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
        params = {
            "input": f"{place_name} {city} {state} India",
            "inputtype": "textquery",
            "fields": "geometry",
            "key": API_KEY
        }
        r = requests.get(url, params=params, timeout=5)
        data = r.json()
        candidates = data.get("candidates", [])
        if candidates and candidates[0].get("geometry"):
            loc = candidates[0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except Exception as e:
        print(f"Error fetching {place_name}: {e}")
    return None, None

# Only process places with zero coordinates
zero_mask = df['Latitude'] == 0
zero_places = df[zero_mask].drop_duplicates(subset=['Name'])
print(f"Total places needing coords: {len(zero_places)}")

coords_map = {}
failed = []

for i, (_, row) in enumerate(zero_places.iterrows()):
    lat, lng = get_real_coords(row['Name'], row['City'], row['State'])
    if lat and lng:
        coords_map[row['Name']] = (lat, lng)
        print(f"[{i+1}/{len(zero_places)}] ✅ {row['Name']} → {lat}, {lng}")
    else:
        failed.append(row['Name'])
        print(f"[{i+1}/{len(zero_places)}] ❌ {row['Name']} — not found")
    time.sleep(0.1)  # avoid rate limiting

# Apply coords back to ALL rows 
# (same place name can appear multiple times in dataset)
def apply_lat(row):
    if row['Latitude'] == 0 and row['Name'] in coords_map:
        return coords_map[row['Name']][0]
    return row['Latitude']

def apply_lng(row):
    if row['Longitude'] == 0 and row['Name'] in coords_map:
        return coords_map[row['Name']][1]
    return row['Longitude']

df['Latitude'] = df.apply(apply_lat, axis=1)
df['Longitude'] = df.apply(apply_lng, axis=1)

# Save as v3
df.to_csv('/Users/tushaarrohatgi/Developer/planner/Ml_model/dataset/tourism_dataset_enriched_v3.csv', index=False)

print(f"\n✅ Done!")
print(f"Successfully geocoded: {len(coords_map)} places")
print(f"Failed: {len(failed)} places")
if failed:
    print("Failed places:", failed[:20])
print("Saved as: tourism_dataset_enriched_v3.csv")
