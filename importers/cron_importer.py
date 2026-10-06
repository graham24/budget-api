import datetime

from importers.importer import Importer
from models.household import Household

if __name__ == "__main__":
    households = Household.load_by_filter(limit=None)
    for household in households:
        if not household.simplefin_access_url:
            print(
                f"Skipping Household: {household.name} ({household.id}) because access url is missing."
            )
            continue
        try:
            start_time = datetime.datetime.now()
            print(f"{start_time}: Transaction Fetch Started")
            Importer.import_household_from_simplefin(household=household)
            print(
                f"{datetime.datetime.now()}: Transaction Fetch Finished in {datetime.datetime.now() - start_time}"
            )
        except Exception as e:
            print(f"Transactions fetch failed: {e}")

    print("\n")
