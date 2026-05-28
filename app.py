import streamlit as st
import pandas as pd
from db import get_connection

st.set_page_config(page_title="Fashion & Beauty Trends", page_icon="🛍️", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;1,400&family=DM+Sans:wght@300;400;500&display=swap');

        html, body, [class*="css"] {
            font-family: 'DM Sans', sans-serif;
        }
        .main {
            background-color: #fdf6f0;
        }
        h1, h2, h3 {
            font-family: 'Playfair Display', serif;
        }
        .hero-title {
            font-family: 'Playfair Display', serif;
            font-size: 3rem;
            font-weight: 600;
            color: #2d2d2d;
            margin-bottom: 0.2rem;
        }
        .hero-sub {
            font-family: 'DM Sans', sans-serif;
            font-size: 1rem;
            color: #9e8f88;
            margin-bottom: 2rem;
            font-weight: 300;
            letter-spacing: 0.05em;
        }
        .product-card {
            background: #ffffff;
            border-radius: 16px;
            padding: 1rem;
            margin-bottom: 1.2rem;
            box-shadow: 0 2px 12px rgba(0,0,0,0.05);
            transition: box-shadow 0.2s ease;
        }
        .product-name {
            font-family: 'DM Sans', sans-serif;
            font-size: 0.95rem;
            font-weight: 500;
            color: #2d2d2d;
            margin-bottom: 0.2rem;
        }
        .product-brand {
            font-size: 0.8rem;
            color: #b5a9a3;
            margin-bottom: 0.4rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        .product-price {
            font-size: 1.1rem;
            font-weight: 600;
            color: #2d2d2d;
        }
        .price-up {
            color: #e07b7b;
            font-size: 0.85rem;
            font-weight: 500;
        }
        .price-down {
            color: #7bbfa0;
            font-size: 0.85rem;
            font-weight: 500;
        }
        .view-link a {
            color: #c9a98a;
            font-size: 0.85rem;
            text-decoration: none;
            font-weight: 500;
            letter-spacing: 0.03em;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 2rem;
            border-bottom: 1px solid #ede8e3;
        }
        .stTabs [data-baseweb="tab"] {
            font-family: 'DM Sans', sans-serif;
            font-size: 0.9rem;
            letter-spacing: 0.05em;
            color: #9e8f88;
            padding-bottom: 0.8rem;
        }
        .stTabs [aria-selected="true"] {
            color: #2d2d2d !important;
            border-bottom: 2px solid #c9a98a !important;
        }
        .category-label {
            font-family: 'DM Sans', sans-serif;
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: #c9a98a;
            margin-bottom: 0.8rem;
            font-weight: 500;
        }
        hr {
            border: none;
            border-top: 1px solid #f0ebe6;
            margin: 0.5rem 0 1rem 0;
        }
    </style>
""", unsafe_allow_html=True)


def get_products_by_category(category, limit=4):
    conn = get_connection()
    query = """
        SELECT 
            p.name,
            p.category,
            p.brand,
            p.image_url,
            p.product_url,
            first.price AS first_price,
            latest.price AS latest_price,
            ROUND(((latest.price - first.price) / NULLIF(first.price, 0) * 100)::numeric, 2) AS price_change_pct
        FROM products p
        JOIN price_history first ON first.product_id = p.id
        JOIN price_history latest ON latest.product_id = p.id
        WHERE first.recorded_at = (SELECT MIN(recorded_at) FROM price_history WHERE product_id = p.id)
        AND latest.recorded_at = (SELECT MAX(recorded_at) FROM price_history WHERE product_id = p.id)
        AND p.category = %s
        ORDER BY p.created_at DESC
        LIMIT %s;
    """
    df = pd.read_sql(query, conn, params=(category, limit))
    conn.close()
    return df


def render_product(row):
    col1, col2 = st.columns([1, 2])
    with col1:
        image_url = row['image_url']
        if image_url and not image_url.startswith("https://"):
            image_url = f"https://{image_url}"
        if image_url:
            st.image(image_url, width=130)
    with col2:
        if row['brand']:
            st.markdown(f"<div class='product-brand'>{row['brand']}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='product-name'>{row['name']}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='product-price'>${row['latest_price']}</div>", unsafe_allow_html=True)
        change = row['price_change_pct']
        if change and change > 0:
            st.markdown(f"<div class='price-up'>▲ {change}% since first seen</div>", unsafe_allow_html=True)
        elif change and change < 0:
            st.markdown(f"<div class='price-down'>▼ {abs(change)}% since first seen</div>", unsafe_allow_html=True)
        if row['product_url']:
            st.markdown(f"<div class='view-link'><a href='{row['product_url']}' target='_blank'>View Product →</a></div>", unsafe_allow_html=True)
    st.markdown("<hr>", unsafe_allow_html=True)


# ── Header ──────────────────────────────────────────────
st.markdown("<div class='hero-title'>✦ Trending Now</div>", unsafe_allow_html=True)
st.markdown("<div class='hero-sub'>FASHION & BEAUTY · UPDATED WEEKLY</div>", unsafe_allow_html=True)

# ── Tabs ────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["👗  Dresses & Tops", "👟  Shoes & Accessories", "💄  Makeup"])

with tab1:
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("<div class='category-label'>Dresses</div>", unsafe_allow_html=True)
        dresses = get_products_by_category("Dresses")
        if dresses.empty:
            st.caption("No products found.")
        for _, row in dresses.iterrows():
            render_product(row)
    with col_b:
        st.markdown("<div class='category-label'>Tops</div>", unsafe_allow_html=True)
        tops = get_products_by_category("Tops")
        if tops.empty:
            st.caption("No products found.")
        for _, row in tops.iterrows():
            render_product(row)

with tab2:
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("<div class='category-label'>Shoes</div>", unsafe_allow_html=True)
        shoes = get_products_by_category("Shoes")
        if shoes.empty:
            st.caption("No products found.")
        for _, row in shoes.iterrows():
            render_product(row)
    with col_b:
        st.markdown("<div class='category-label'>Accessories</div>", unsafe_allow_html=True)
        accessories = get_products_by_category("Accessories")
        if accessories.empty:
            st.caption("No products found.")
        for _, row in accessories.iterrows():
            render_product(row)

with tab3:
    st.markdown("<div class='category-label'>Makeup</div>", unsafe_allow_html=True)
    makeup_cols = st.columns(2)
    makeup = get_products_by_category("Makeup")
    if makeup.empty:
        st.caption("No products found.")
    else:
        for i, (_, row) in enumerate(makeup.iterrows()):
            with makeup_cols[i % 2]:
                render_product(row)