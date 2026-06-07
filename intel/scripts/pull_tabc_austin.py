"""
Pull new TABC Mixed Beverage (MB) licenses issued in Travis County.
Saves to intel/raw/YYYY-MM-DD_tabc-travis.csv
"""

import csv
import json
import urllib.request
import urllib.parse
import datetime
import os

DATASET_ID = "7hf9-qc9f"
BASE_URL = f"https://data.texas.gov/resource/{DATASET_ID}.json"

LOOKBACK_DAYS = 180

# License types that indicate food/beverage service establishments
RESTAURANT_LICENSE_TYPES = ("MB", "BQ", "BE", "BF", "BB", "BW")

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "raw")


def fetch_tabc(app_token=None):
    cutoff = datetime.date.today() - datetime.timedelta(days=LOOKBACK_DAYS)
    cutoff_str = cutoff.strftime("%Y-%m-%dT00:00:00.000")
    type_list = ", ".join(f"'{t}'" for t in RESTAURANT_LICENSE_TYPES)

    where = (
        f"county = 'Travis' "
        f"AND original_issue_date >= '{cutoff_str}' "
        f"AND license_type IN ({type_list})"
    )

    params = {
        "$where": where,
        "$limit": "5000",
        "$order": "original_issue_date DESC",
        "$select": (
            "trade_name,owner,license_type,primary_status,"
            "address,city,zip,county,"
            "original_issue_date,expiration_date,tier"
        ),
    }

    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    if app_token:
        req.add_header("X-App-Token", app_token)

    print(f"Querying TABC dataset — Travis County, last {LOOKBACK_DAYS} days")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode())


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
    app_token = os.environ.get("TEXAS_APP_TOKEN")
    records = fetch_tabc(app_token)

    today = datetime.date.today().strftime("%Y-%m-%d")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"{today}_tabc-travis.csv")
    save_csv(records, output_path)

    if records:
        print("\nFirst 10 results:")
        for r in records[:10]:
            print(
                f"  {r.get('original_issue_date','')[:10]}  "
                f"{r.get('license_type',''):4}  "
                f"{r.get('trade_name') or '[no name]':<35}  "
                f"{r.get('address','')}"
            )


if __name__ == "__main__":
    main()
