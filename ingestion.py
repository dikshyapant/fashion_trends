import os
import time
import json
import re
import random
import logging
from datetime import datetime, timezone

import boto3
from dotenv import load_dotenv
from db import get_connection
from pytrends.request import TrendReq
from serpapi import GoogleSearch

logging.basicConfig(
    filename="pipeline.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

load_dotenv()

# ---------------------------------------------------------------------------
# S3 raw landing layer
# ---------------------------------------------------------------------------
S3_BUCKET = os.getenv("S3_BUCKET")
RUN_TS = datetime.now(timezone.utc)
s3 = boto3.client("s3") if S3_BUCKET else None


def save_raw_to_s3(data, source, name):
    """Save a raw API response to S3 before any cleaning.

    Files land at: raw/<source>/date=YYYY-MM-DD/HH-MM-SS_<name>.json
    If S3 is not configured or the upload fails, the pipeline keeps running.
    """
    if not s3:
        return
    safe_name = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    key = f"raw/{source}/date={RUN_TS:%Y-%m-%d}/{RUN_TS:%H-%M-%S}_{safe_name}.json"
    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=json.dumps(data, default=str),
            ContentType="application/json",
        )
        logging.info(f"Saved raw {source} data to s3://{S3_BUCKET}/{key}")
    except Exception as e:
        logging.error(f"S3 upload failed for {key}: {e}")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TREND_SEEDS = {
    "fashion": ["women's fashion", "dress outfit", "shoes outfit"],
    "makeup":  ["makeup trends", "beauty products"]
}

CATEGORY_KEYWORDS = {
    "Dresses":     ["dress", "skirt", "gown", "sundress", "midi", "maxi", "mini"],
    "Tops":        ["top", "blouse", "shirt", "tee", "crop", "corset", "bodysuit"],
    "Shoes":       ["shoe", "boot", "heel", "flat", "sneaker", "sandal", "loafer", "ballet"],
    "Accessories": ["bag", "hoop", "necklace", "earring", "belt", "scarf", "sunglasses", "jewelry"],
    "Makeup":      ["makeup", "lipstick", "blush", "foundation", "mascara", "liner", "eyeshadow", "concealer", "bronzer", "gloss"]
}

FALLBACK_KEYWORDS = {
    "Dresses":     "maxi dress",
    "Tops":        "top",
    "Shoes":       "ballet flats",
    "Accessories": "jewelry",
    "Makeup":      "makeup"
}


# ---------------------------------------------------------------------------
# Extract: Google Trends
# ---------------------------------------------------------------------------
SEED_PAUSE_SECONDS = 5      # wait between seeds
MAX_RETRIES = 3             # attempts per seed
BASE_BACKOFF_SECONDS = 10   # 10s, then 20s, then 40s


def fetch_related_with_retry(pytrends, seed):
    """Call Google Trends for one seed, retrying with backoff on 429 errors.

    Returns the related_queries() dict, or None if every attempt failed.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            pytrends.build_payload([seed], timeframe='now 7-d', geo='US')
            return pytrends.related_queries()
        except Exception as e:
            rate_limited = "429" in str(e)
            if rate_limited and attempt < MAX_RETRIES:
                wait = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 3)
                logging.warning(
                    f"pytrends 429 for '{seed}' (attempt {attempt}/{MAX_RETRIES}), "
                    f"retrying in {wait:.0f}s"
                )
                time.sleep(wait)
                continue
            logging.error(f"pytrends failed for seed '{seed}' after {attempt} attempt(s): {e}")
            return None
    return None


def get_trending_keywords():
    logging.info("Fetching trending keywords from Google Trends...")
    pytrends = TrendReq(hl='en-US', tz=360)
    trending = {}
    all_queries = []

    for seed_group, seeds in TREND_SEEDS.items():
        for seed in seeds:
            related = fetch_related_with_retry(pytrends, seed)
            if related is None:
                time.sleep(SEED_PAUSE_SECONDS)
                continue

            # Save the raw response (DataFrames -> plain lists for JSON)
            raw = {
                kind: (df.to_dict(orient="records") if df is not None else None)
                for kind, df in (related.get(seed) or {}).items()
            }
            save_raw_to_s3(raw, "google_trends", seed)

            top_df = (related.get(seed) or {}).get("top", None)
            if top_df is not None and not top_df.empty:
                queries = top_df["query"].tolist()
                all_queries.extend(queries)
                logging.info(f"pytrends [{seed}] -> {queries[:5]}")

            # Space out requests so Google is less likely to rate-limit us
            time.sleep(SEED_PAUSE_SECONDS)

    assigned = set()
    for query in all_queries:
        query_lower = query.lower()
        for category, keywords in CATEGORY_KEYWORDS.items():
            if category in assigned:
                continue
            if any(kw in query_lower for kw in keywords):
                trending[category] = query
                assigned.add(category)
                logging.info(f"Mapped '{query}' -> {category}")
                break

    for category, fallback in FALLBACK_KEYWORDS.items():
        if category not in trending:
            trending[category] = fallback
            logging.info(f"Using fallback for {category}: '{fallback}'")

    logging.info(f"Final trending keywords: {trending}")
    return trending


# ---------------------------------------------------------------------------
# Extract: SerpAPI Google Shopping
# ---------------------------------------------------------------------------
def fetch_products(trending_keywords):
    all_products = []

    for category, keyword in trending_keywords.items():
        logging.info(f"Fetching {category} using keyword: '{keyword}'")
        try:
            params = {
                "engine": "google_shopping",
                "q": keyword,
                "api_key": os.getenv("SERPAPI_KEY"),
                "num": "4",
                "gl": "us",
                "hl": "en"
            }
            search = GoogleSearch(params)
            results = search.get_dict()

            # Save the raw response, never storing the API key
            results.get("search_parameters", {}).pop("api_key", None)
            save_raw_to_s3(results, "serpapi", category)

            products = results.get("shopping_results", [])[:4]

            for product in products:
                product["_category_name"] = category
            all_products.extend(products)
            logging.info(f"Got {len(products)} products for {category}")
            time.sleep(1)

        except Exception as e:
            logging.error(f"Failed to fetch {category}: {e}")
            continue

    return all_products


# ---------------------------------------------------------------------------
# Load: Supabase (PostgreSQL)
# ---------------------------------------------------------------------------
def save_products(products):
    conn = get_connection()
    cur = conn.cursor()
    saved = 0

    for product in products:
        try:
            category = product.get("_category_name", "")
            external_id = "SERP_" + str(product.get("product_id", ""))
            name = product.get("title", "")
            image_url = product.get("thumbnail", "")
            price = product.get("extracted_price", 0.0)
            brand = product.get("source", "")
            product_url = product.get("product_link", "")

            if not name or not price:
                continue

            cur.execute("""
                INSERT INTO products (external_id, name, category, image_url, brand, product_url)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (external_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    image_url = EXCLUDED.image_url,
                    brand = EXCLUDED.brand,
                    product_url = EXCLUDED.product_url
            """, (external_id, name, category, image_url, brand, product_url))

            cur.execute("""
                INSERT INTO price_history (product_id, price)
                VALUES (
                    (SELECT id FROM products WHERE external_id = %s),
                    %s
                )
            """, (external_id, price))

            saved += 1

        except Exception as e:
            logging.error(f"Failed to save product: {e}")
            continue

    conn.commit()
    cur.close()
    conn.close()
    print(f"Saved {saved} products successfully!")
    logging.info(f"Saved {saved} products successfully")


if __name__ == "__main__":
    trending_keywords = get_trending_keywords()
    print(f"Trending this week: {trending_keywords}")

    products = fetch_products(trending_keywords)
    save_products(products)
