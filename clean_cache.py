#!/usr/bin/env python3
"""Remove empty Google Places cache entries."""
import json

with open('businesses_cache.json', 'r') as f:
    data = json.load(f)

# Remove entries with 0 businesses
cleaned = {k: v for k, v in data.items() 
           if not (k.startswith('google_') and v.get('count', -1) == 0)}

with open('businesses_cache.json', 'w') as f:
    json.dump(cleaned, f, indent=2)

print(f"Removed {len(data) - len(cleaned)} empty cache entries")
print(f"Remaining entries: {len(cleaned)}")
