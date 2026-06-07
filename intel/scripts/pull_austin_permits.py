"""
Pull restaurant-related construction permits from Austin Open Data Portal.
Filters for recent permits with food/restaurant work descriptions.
Output: intel/raw/YYYY-MM-DD_austin-permits.csv
"""

import csv
import json
import urllib.request
import urllib.parse
import datetime
import os

DATASET_ID = "3syk-w9eu"
BASE_URL = f"https://data.austintexas.gov/resource/{DATASET_ID}.json"

# How far back to look (days)
LOOKBACK_DAYS = 90

# Keywords to match against work description
RESTAURANT_KEYWORDS = [
    "restaurant",
    "food service",
    "food establishment",
    "bar ",
    "tavern",
    "cafe",
    "cafeteria",
    "kitchen",
    "brewery",
    "winery",
    "bakery",
    "diner",
    "bistro",
    "cantina",
    "taqueria",
    "pizzeria",
    "sushi",
]

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "raw")


def build_where_clause(cutoff_date):
    date_str = cutoff_date.strftime("%Y-%m-%dT00:00:00.000")
    kw_conditions = " OR ".join(
        f"upper(description) LIKE '%{kw.upper()}%'" for kw in RESTAURANT_KEYWORDS
    )
    return f"issue_date >= '{date_str}' AND ({kw_conditions})"


def fetch_permits(app_token=None):
    cutoff = datetime.date.today() - datetime.timedelta(days=LOOKBACK_DAYS)
    where = build_where_clause(cutoff)

    params = {
        "$where": where,
        "$limit": "5000",
        "$order": "issue_date DESC",
        "$select": (
            "permit_type_desc,permit_number,issue_date,description,"
            "original_address1,original_zip,status_current,"
            "permit_class_mapped,work_class"
        ),
    }

    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    if app_token:
        req.add_header("X-App-Token", app_token)

    print(f"Querying: {BASE_URL}")
    print(f"Lookback: {LOOKBACK_DAYS} days (since {cutoff})")

    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())

    return data


def save_csv(records, output_path):
    if not records:
        print("No records returned.")
        return

    fieldnames = list(records[0].keys())
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    print(f"Saved {len(records)} records to {output_path}")


def main():
    # Optional: set your app token here or via env var AUSTIN_APP_TOKEN
    app_token = os.environ.get("AUSTIN_APP_TOKEN")
    if not app_token:
        print("No AUSTIN_APP_TOKEN set — running unauthenticated (rate-limited).")

    records = fetch_permits(app_token)

    today = datetime.date.today().strftime("%Y-%m-%d")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"{today}_austin-permits.csv")

    save_csv(records, output_path)

    # Print a quick preview
    if records:
        print(f"\nFirst 5 results:")
        for r in records[:5]:
            print(f"  {r.get('issue_date','')[:10]}  {r.get('description','')[:50]:<50}  {r.get('original_address1','')}")


if __name__ == "__main__":
    main()
