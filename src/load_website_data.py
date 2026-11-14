import json
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert

from src.database import engine
from src.models import WebsiteLocation


BASE_DIR = Path(__file__).resolve().parent.parent

JSON_FILE = BASE_DIR / "data" / "scraped_locations.json"


def load_website_data():

    with open(JSON_FILE, "r", encoding="utf-8") as file:
        records = json.load(file)

    valid_records = []

    for record in records:

        if not record.get("name"):
            continue

        if not record.get("source_url"):
            continue

        valid_records.append({
            "name": record["name"],
            "street": record.get("street"),
            "city": record.get("city"),
            "state": record.get("state"),
            "zip": record.get("zip"),
            "care_offerings": record.get("care_offerings", []),
            "source_url": record["source_url"],
            "raw_data": record
        })

    if not valid_records:
        print("No valid website records found.")
        return

    statement = insert(WebsiteLocation).values(valid_records)

    statement = statement.on_conflict_do_update(
        index_elements=["source_url"],
        set_={
            "name": statement.excluded.name,
            "street": statement.excluded.street,
            "city": statement.excluded.city,
            "state": statement.excluded.state,
            "zip": statement.excluded.zip,
            "care_offerings": statement.excluded.care_offerings,
            "raw_data": statement.excluded.raw_data
        }
    )

    with engine.begin() as connection:
        connection.execute(statement)

    print(f"Successfully loaded {len(valid_records)} website records.")


if __name__ == "__main__":
    load_website_data()