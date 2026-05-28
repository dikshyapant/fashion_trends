import os
import time
from dotenv import load_dotenv
from db import get_connection
from pytrends.request import TrendReq
from serpapi import GoogleSearch
import logging

logging.basicConfig(
    filename="pipeline.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

load_dotenv()

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


def get_trending_keywords():
    logging.info("Fetching trending keywords from Google Trends...")
    pytrends = TrendReq(hl='en-US', tz=360)
    trending = {}
    all_queries = []

    for seed_group, seeds in TREND_SEEDS.items():
        for seed in seeds:
            try:
                pytrends.build_payload([seed], timeframe='now 7-d', geo='US')
                related = pytrends.related_queries()
                top_df = related.get(seed, {}).get("top", None)
                if top_df is not None and not top_df.empty:
                    queries = top_df["query"].tolist()
                    all_queries.extend(queries)
                    logging.info(f"pytrends [{seed}] -> {queries[:5]}")
                time.sleep(1)
            except Exception as e:
                logging.error(f"pytrends failed for seed '{seed}': {e}")
                continue

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