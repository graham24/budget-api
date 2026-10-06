# Budget API (Backend)

Flask backend for a household budgeting app.  
Provides transaction import, AI-assisted categorization, household/account lookup, and summary endpoints for the Vue frontend.

## What It Does

- Exposes REST endpoints under `/api/*` for:
  - auth/login
  - household lookup
  - account lookup
  - user lookup
  - transaction listing, summary, update, and CSV upload
- Imports CSV exports from multiple banks:
  - Wells Fargo
  - Chase
  - US Bank
  - Apple (Savings and Credit Card formats)
- Deduplicates imported transactions via a DB unique constraint on:
  - `description`
  - `date`
  - `amount`
  - `account_id`
- Uses OpenAI (`gpt-4o-mini`) to classify imported transactions into:
  - `category`
  - `sub_category`
  - `need` (true/false)
- Builds monthly net-income/category summaries for the last 3 completed months.

## Tech Stack

- Python
- Flask + Flask-CORS
- SQLModel / SQLAlchemy
- SQLite
- Pydantic
- OpenAI Python SDK

## Key Files

- `app.py`: Flask app bootstrap + blueprint registration.
- `routes/transactions.py`: transaction list/summary/save/upload endpoints.
- `routes/auth.py`: login endpoint (currently mocked user identity).
- `importers/importer.py`: orchestrates CSV parsing + AI categorization.
- `importers/*.py`: bank-specific CSV parsers.
- `analyze.py`: OpenAI categorization and similar-transaction matching.
- `models/*.py`: SQLModel entities and DB helpers.
- `setup.py`: initializes schema via SQLModel metadata.

## API Endpoints

Base prefix in `app.py`:

- `/api/auth/login/` `POST`
- `/api/household/` `POST`
- `/api/accounts/` `POST`
- `/api/users/` `GET`
- `/api/transactions/` `GET`
- `/api/transactions/summary/` `GET`
- `/api/transactions/save` `PUT`
- `/api/transactions/upload/` `POST`

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure secrets and DB connection in `constants.py`:
  - `open_ai_api_key`
  - `db_username`
  - `db_password`
  - `db_name`
  - `db_url`

4. Initialize DB tables:

```bash
python setup.py
```

5. Start API server:

```bash
python app.py
```

Default Flask dev host/port is typically `http://localhost:5000`.

## Notes

- Timezone policy: DB and local time should be UTC.
- `routes/auth.py` currently uses mocked identity data in code for login flow.
- Current frontend integration expects this API to be available with CORS enabled.

## Known Gaps

- No test suite automation (only ad-hoc scripts under `request_tests/`).
- No production auth/session flow yet (Google token verification imports exist but are not actively used in login route).
- Secrets are currently file-based (`constants.py`) rather than environment-driven.


test for actions