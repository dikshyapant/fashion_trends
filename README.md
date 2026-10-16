**Live App:** [fashiontrendsbydikshyapant.streamlit.app](https://fashiontrendsbydikshyapant.streamlit.app)
# Fashion & Beauty Trend Tracker

A fashion & beauty trend tracker that identifies trending styles 
using Google Trends and fetches real products via SerpAPI Google Shopping.
It runs as a serverless batch ETL pipeline on AWS twice a week.

## Stack
- **Python** — data pipeline (pandas, psycopg2)
- **pytrends** — Google Trends keyword discovery
- **SerpAPI** — Google Shopping product fetching
- **AWS Lambda** — runs the pipeline serverlessly
- **Amazon EventBridge** — schedules runs every Monday & Friday (9:00 UTC)
- **Amazon S3** — raw data landing layer (date-partitioned JSON)
- **PostgreSQL (Supabase)** — cloud database for cleaned data
- **Streamlit** — dashboard UI

## Architecture
```
EventBridge (Mon & Fri, 9:00 UTC)
   → AWS Lambda (ingestion.py)
      → Google Trends (pytrends) → trending keywords per category
      → SerpAPI Google Shopping  → products for each keyword
      → raw API responses saved to S3
      → cleaned products + prices loaded into PostgreSQL (Supabase)
         → Streamlit dashboard reads from PostgreSQL
```

## How it works
1. EventBridge triggers the Lambda function every Monday and Friday
2. pytrends finds trending fashion & beauty keywords from the past 7 days and maps them to categories (Dresses, Tops, Shoes, Accessories, Makeup), with fallback keywords if none match
3. SerpAPI fetches real products from Google Shopping for each keyword
4. Raw API responses are saved to S3 before any cleaning
5. Products are upserted into Supabase, and each price is added to a `price_history` table to track changes over time
6. Streamlit displays them in a live dashboard

## Raw data layer (S3)
Every raw API response is stored as JSON, partitioned by date:
```
raw/google_trends/date=YYYY-MM-DD/HH-MM-SS_<seed>.json
raw/serpapi/date=YYYY-MM-DD/HH-MM-SS_<category>.json
```
This keeps an untouched copy of the source data, so the data can be reprocessed if the cleaning logic changes without calling the APIs again.

## Reliability
- Retries with exponential backoff when Google Trends rate-limits requests (HTTP 429)
- Upserts on `external_id` prevent duplicate products
- If an S3 upload fails, the error is logged and the pipeline still loads to Supabase
- Lambda logs go to Amazon CloudWatch

## Running locally
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 ingestion.py
```
Requires a `.env` file with `DATABASE_URL`, `SERPAPI_KEY`, and `S3_BUCKET`, plus AWS credentials configured with `aws configure`.
