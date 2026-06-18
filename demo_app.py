"""TDG Demo — Tailored Data Generation: LLM → PostgreSQL → DuckDB."""

from __future__ import annotations

import io
import json
import math
import os
import pathlib
import re
import zipfile

import psycopg2
import psycopg2.extras
import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, field_validator

from data_layer import DataLayer

# ── LLM backend ───────────────────────────────────────────────────────────────
_MOCK_MODE = os.getenv("DEMO_MOCK", "0") == "1"

_BACKEND: str | None = None
if not _MOCK_MODE:
    try:
        import litellm as _llm
        _BACKEND = "litellm"
    except ImportError:
        try:
            import anthropic as _anth
            _BACKEND = "anthropic"
        except ImportError:
            try:
                import openai as _oai
                _BACKEND = "openai"
            except ImportError:
                pass

# ── SDV (CTGAN) ──────────────────────────────────────────────────────────────
_SDV_AVAILABLE = False
_SdvSTMeta = None
_CTGAN = None
try:
    from sdv.metadata import SingleTableMetadata as _SdvSTMeta
    from sdv.single_table import CTGANSynthesizer as _CTGAN
    _SDV_AVAILABLE = True
except ImportError:
    pass

# ── PostgreSQL config ─────────────────────────────────────────────────────────
_PG = dict(
    host=os.getenv("DEMO_PG_HOST", "localhost"),
    port=int(os.getenv("DEMO_PG_PORT", "5432")),
    dbname=os.getenv("DEMO_PG_DB", "aida_demo"),
    user=os.getenv("DEMO_PG_USER", "postgres"),
    password=os.getenv("DEMO_PG_PASSWORD", "postgres"),
)
_PG_SCHEMA = "demo"
_DSN = "host={host} port={port} dbname={dbname} user={user} password={password}".format(**_PG)

# ── Constants ─────────────────────────────────────────────────────────────────
MODELS = {
    "claude-sonnet-4-6":         "Claude Sonnet 4.6",
    "claude-haiku-4-5-20251001": "Claude Haiku 4.5",
    "gpt-4o":                    "GPT-4o",
    "gpt-4o-mini":               "GPT-4o Mini",
}
FILE_FORMATS = ["csv", "json", "parquet", "txt", "xlsx"]
INDUSTRIES = {
    "financial":      "Financial Services & Insurance",
    "energy":         "Energy & Oil and Gas",
    "healthcare":     "Healthcare & Pharmaceuticals",
    "technology":     "Technology / IT & Software",
    "construction":   "Construction & Real Estate",
    "agriculture":    "Agriculture & Food Production",
    "manufacturing":  "Manufacturing",
    "retail":         "Retail & E-Commerce",
    "transportation": "Transportation & Logistics",
    "media":          "Media, Entertainment & Tourism",
}

# Simulated file-source format per table (shown as badges in the UI)
_MOCK_SOURCES = {
    "financial":      {"customers": "JSON",  "products": "CSV",        "accounts": "Parquet",       "transactions": "JSON"},
    "energy":         {"plants": "CSV",      "meters": "JSON",         "consumption_records": "Parquet", "maintenance_logs": "CSV"},
    "healthcare":     {"doctors": "CSV",     "patients": "JSON",       "appointments": "Parquet",   "prescriptions": "CSV"},
    "technology":     {"employees": "JSON",  "projects": "CSV",        "bugs": "JSON",              "deployments": "Parquet"},
    "construction":   {"properties": "CSV",  "agents": "JSON",         "listings": "Parquet",       "transactions": "CSV"},
    "agriculture":    {"farms": "CSV",       "crops": "JSON",          "harvests": "Parquet",       "distributors": "CSV"},
    "manufacturing":  {"facilities": "CSV",  "equipment": "JSON",      "production_runs": "Parquet","quality_checks": "CSV"},
    "retail":         {"products": "CSV",    "customers": "JSON",      "orders": "Parquet",         "order_items": "CSV"},
    "transportation": {"vehicles": "JSON",   "drivers": "CSV",         "routes": "Parquet",         "shipments": "JSON"},
    "media":          {"hotels": "CSV",      "rooms": "JSON",          "guests": "Parquet",         "reservations": "CSV"},
}

# ── LLM call ─────────────────────────────────────────────────────────────────
def _call_llm(model: str, system: str, user: str) -> str:
    if _BACKEND == "litellm":
        r = _llm.completion(
            model=model, temperature=0.7,
            messages=[{"role": "system", "content": system},
                      {"role": "user",   "content": user}],
        )
        return r.choices[0].message.content
    if _BACKEND == "anthropic":
        r = _anth.Anthropic().messages.create(
            model=model, max_tokens=4096, system=system,
            messages=[{"role": "user", "content": user}],
        )
        return r.content[0].text
    if _BACKEND == "openai":
        r = _oai.OpenAI().chat.completions.create(
            model=model, temperature=0.7,
            messages=[{"role": "system", "content": system},
                      {"role": "user",   "content": user}],
        )
        return r.choices[0].message.content
    raise RuntimeError("No LLM backend found. Run: pip install litellm")

# ── LLM data generation ───────────────────────────────────────────────────────
_GEN_SYSTEM_MESSY_BASE = """You are a synthetic data generator. Return ONLY raw valid JSON.

Output schema:
{
  "tables": [
    {
      "name": "<snake_case_table_name>",
      "columns": [{"name": "<column_name>", "type": "TEXT|INTEGER|DECIMAL|DATE|BOOLEAN"}],
      "rows": [[value, ...], ...]
    }
  ]
}

Use MESSY column names: mix spaces, special chars, inconsistent casing, abbreviations.
Examples: "Doctor ID", "First Name", "SPECIALTY", "Yrs. Experience", "E-Mail", "Date-of-Birth".
Rules: IDs sequential from 1. FK values reference real parent IDs. Parent tables first.
Dates: "YYYY-MM-DD". Numbers: JSON numbers."""

_GEN_SYSTEM_CLEAN_BASE = """You are a synthetic data generator. Return ONLY raw valid JSON.

Output schema:
{
  "tables": [
    {
      "name": "<snake_case_table_name>",
      "columns": [{"name": "<column_name>", "type": "TEXT|INTEGER|DECIMAL|DATE|BOOLEAN"}],
      "rows": [[value, ...], ...]
    }
  ]
}

Use clean snake_case column names only: e.g. doctor_id, first_name, specialty, email.
Rules: IDs sequential from 1. FK values reference real parent IDs. Parent tables first.
Dates: "YYYY-MM-DD". Numbers: JSON numbers."""

_PROMPTS = {
    "financial": (
        "Generate a financial services & insurance database with 4 tables "
        "(customers, products, accounts, transactions). "
        "Make the tables relational with proper foreign key references."
    ),
    "energy": (
        "Generate an energy & oil/gas database with 4 tables "
        "(plants, meters, consumption_records, maintenance_logs). "
        "Make the tables relational with proper foreign key references."
    ),
    "healthcare": (
        "Generate a healthcare & pharmaceuticals database with 4 tables "
        "(doctors, patients, appointments, prescriptions). "
        "Make the tables relational with proper foreign key references."
    ),
    "technology": (
        "Generate a technology/IT & software company database with 4 tables "
        "(employees, projects, bugs, deployments). "
        "Make the tables relational with proper foreign key references."
    ),
    "construction": (
        "Generate a construction & real estate database with 4 tables "
        "(properties, agents, listings, transactions). "
        "Make the tables relational with proper foreign key references."
    ),
    "agriculture": (
        "Generate an agriculture & food production database with 4 tables "
        "(farms, crops, harvests, distributors). "
        "Make the tables relational with proper foreign key references."
    ),
    "manufacturing": (
        "Generate a manufacturing operations database with 4 tables "
        "(facilities, equipment, production_runs, quality_checks). "
        "Make the tables relational with proper foreign key references."
    ),
    "retail": (
        "Generate a retail & e-commerce database with 4 tables "
        "(products, customers, orders, order_items). "
        "Make the tables relational with proper foreign key references."
    ),
    "transportation": (
        "Generate a transportation & logistics database with 4 tables "
        "(vehicles, drivers, routes, shipments). "
        "Make the tables relational with proper foreign key references."
    ),
    "media": (
        "Generate a media, entertainment & tourism database with 4 tables "
        "(hotels, rooms, guests, reservations). "
        "Make the tables relational with proper foreign key references."
    ),
}


def _extract_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    text = text.strip()
    start = text.find("{")
    if start > 0:
        text = text[start:]
    end = text.rfind("}")
    if end >= 0:
        text = text[: end + 1]
    return text


def _slice_data(data: dict, num_rows: int | None, num_cols: int | None,
                custom_columns: list[str] | None = None) -> dict:
    import copy
    result = copy.deepcopy(data)
    for tbl in result["tables"]:
        # Determine target column count
        if custom_columns is not None:
            target_cols = len(custom_columns)
        elif num_cols is not None:
            target_cols = num_cols
        else:
            target_cols = len(tbl["columns"])

        actual_n = min(target_cols, len(tbl["columns"]))
        tbl["columns"] = tbl["columns"][:actual_n]
        base = [row[:actual_n] for row in tbl["rows"]]
        base_n = len(base)

        if base_n == 0:
            tbl["rows"] = []
        else:
            target_rows = num_rows if num_rows is not None else base_n
            extended = list(base)
            cycle = 0
            while len(extended) < target_rows:
                cycle += 1
                for row in base:
                    if len(extended) >= target_rows:
                        break
                    new_row = []
                    for val in row:
                        if isinstance(val, int):
                            new_row.append(val + base_n * cycle)
                        elif isinstance(val, float):
                            new_row.append(round(val * (1 + 0.07 * cycle), 2))
                        else:
                            new_row.append(val)
                    extended.append(new_row)
            tbl["rows"] = extended[:target_rows]

        # Apply custom column names, padding rows for any extra columns
        if custom_columns is not None:
            for i, row in enumerate(tbl["rows"]):
                tbl["rows"][i] = row + [None] * max(0, target_cols - actual_n)
            tbl["columns"] = [
                {"name": custom_columns[i],
                 "type": tbl["columns"][i]["type"] if i < actual_n else "TEXT"}
                for i in range(target_cols)
            ]

    return result


# Product profiles — each entry is (item_name, category, unit_price).
# All lists have 11 entries (coprime with default 10 rows).
# Columns in the same row share the same profile index so they stay logically consistent.
_FOOD_PRODUCT_PROFILES = [
    ("Italian B.M.T.",    "Sandwiches", 8.99),
    ("Turkey Breast",     "Sandwiches", 7.99),
    ("Fountain Drink",    "Drinks",     1.99),
    ("Tuna",              "Sandwiches", 7.49),
    ("Meatball Marinara", "Sandwiches", 8.49),
    ("Chips",             "Snacks",     1.49),
    ("Chicken Teriyaki",  "Sandwiches", 9.49),
    ("Cookie",            "Desserts",   1.99),
    ("Veggie Delite",     "Sandwiches", 6.99),
    ("Coffee",            "Drinks",     2.49),
    ("Steak & Cheese",    "Sandwiches", 10.49),
]

_RETAIL_PRODUCT_PROFILES = [
    ("Wireless Headphones", "Electronics",  79.99),
    ("Running Shoes",       "Footwear",     89.99),
    ("Cotton T-Shirt",      "Apparel",      24.99),
    ("Coffee Maker",        "Appliances",   49.99),
    ("Yoga Mat",            "Sports",       34.99),
    ("Backpack",            "Bags",         54.99),
    ("Sunglasses",          "Accessories",  39.99),
    ("Desk Lamp",           "Home",         29.99),
    ("Water Bottle",        "Outdoors",     19.99),
    ("Notebook Set",        "Stationery",   14.99),
    ("Phone Case",          "Electronics",  16.99),
]


def _make_row_ctx(variety_idx: int, company_name: str) -> dict:
    """Return a row-level context dict so related columns (name, category, price) stay consistent."""
    co = company_name.lower()
    is_food = any(k in co for k in (
        "subway", "sandwich", "deli", "restaurant", "cafe", "coffee", "pizza",
        "burger", "taco", "bakery", "kitchen", "bistro", "grill", "eatery", "dining",
        "buffet", "fast food", "food", "sub "
    ))
    profiles = _FOOD_PRODUCT_PROFILES if is_food else _RETAIL_PRODUCT_PROFILES
    name, category, price = profiles[variety_idx % 11]
    return {"item_name": name, "item_category": category, "item_price": price}


def _make_mock_cell(col: str, row_num: int, variety_idx: int, company_name: str = "",
                    row_ctx: dict | None = None) -> object:
    """Return a plausible mock value for a column based on its name.

    row_num    — 1-based sequential position within the table (used for IDs)
    variety_idx — offset that differs per table so rows across tables aren't identical
    row_ctx    — shared per-row profile so product name, category, and price stay consistent
    All value lists have 11 entries so vi%11 never aligns with the default 10-row boundary.
    """
    n   = re.sub(r'[^a-z0-9]+', '_', col.lower().strip()).strip('_')
    co  = company_name.lower()
    vi  = variety_idx
    toks = set(n.split('_'))

    def tok(*words):
        return any(w in toks for w in words)

    is_food = any(k in co for k in (
        "subway", "sandwich", "deli", "restaurant", "cafe", "coffee", "pizza",
        "burger", "taco", "bakery", "kitchen", "bistro", "grill", "eatery", "dining",
        "buffet", "fast food", "food", "sub "
    ))
    is_subway = "subway" in co or "sub" in co.split()

    # Reusable lists (all length-11)
    FIRST   = ["John", "Jane", "Mike", "Sarah", "Alex", "Emily", "Chris", "Anna", "David", "Lisa", "Robert"]
    LAST    = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis", "Wilson", "Moore", "Taylor", "Anderson"]
    CITIES  = ["New York, NY", "Los Angeles, CA", "Chicago, IL", "Houston, TX",
               "Phoenix, AZ", "Philadelphia, PA", "San Antonio, TX", "San Diego, CA",
               "Dallas, TX", "San Jose, CA", "Austin, TX"]
    STREETS = ["123 Main St", "456 Oak Ave", "789 Pine Rd", "321 Elm St", "654 Maple Dr",
               "987 Cedar Blvd", "147 Birch Ln", "258 Walnut St", "369 Spruce Ave",
               "741 Willow Way", "852 Maple Ave"]
    SUBS    = (["Italian B.M.T.", "Turkey Breast", "Tuna", "Meatball Marinara", "Chicken Teriyaki",
                "Veggie Delite", "BLT", "Roast Beef", "Club", "Steak & Cheese", "Spicy Italian"]
               if is_food else
               ["Burger", "Salad", "Wrap", "Sandwich", "Pasta",
                "Pizza", "Soup", "Tacos", "Bowl", "Platter", "Burrito"])

    # ── 1. IDs ───────────────────────────────────────────────────────────────────
    if n == "id" or n.endswith("_id"):
        return row_num
    # Sequential number columns: order_number, table_no, item_num — but NOT phone/promo/loyalty
    if tok("number", "num", "no", "#") and not tok("phone", "mobile", "tel", "fax", "promo", "coupon", "loyalty", "card", "account"):
        return row_num

    # ── 2. Dates ─────────────────────────────────────────────────────────────────
    DATE_TOKS = {"date", "dt", "since", "opened", "open", "created", "hired",
                 "joined", "start", "end", "expiry", "expiration", "timestamp", "when"}
    if toks & DATE_TOKS or n.endswith("_at") or n.endswith("_dt"):
        from datetime import date as _d, timedelta as _td
        base  = _d(2020, 1, 1) if tok("since", "open", "created", "hired", "joined", "start") else _d(2025, 1, 1)
        delta = 45 if tok("since", "open", "hired", "joined", "start") else 3
        return str(base + _td(days=vi * delta))

    # ── 3. Booleans ───────────────────────────────────────────────────────────────
    if n.startswith("is_") or n.startswith("has_"):
        return vi % 4 != 0
    BOOL_EXACT = {"active", "available", "enabled", "valid", "approved", "verified",
                  "completed", "archived", "deleted", "visible", "featured", "open", "closed"}
    if n in BOOL_EXACT:
        return vi % 4 != 0

    # ── 4. Money ─────────────────────────────────────────────────────────────────
    # Tax / discount / tip checked before the general money bucket
    if tok("tax") and not tok("status", "syntax", "title"):
        return round([0.45, 0.76, 1.17, 1.42, 2.03, 3.15, 0.52, 0.56, 1.08, 1.67, 0.88][vi % 11], 2)
    if tok("discount", "savings", "markdown"):
        return round([0.50, 1.00, 2.00, 0.75, 1.50, 0.00, 2.50, 1.25, 0.00, 0.99, 3.00][vi % 11], 2)
    if tok("tip", "gratuity"):
        return round([0.50, 1.00, 0.75, 1.50, 0.00, 2.00, 1.25, 0.00, 1.75, 0.50, 2.50][vi % 11], 2)
    MONEY_TOKS = {"price", "cost", "total", "amount", "fee", "charge", "revenue",
                  "subtotal", "balance", "earning", "wage", "wages"}
    if toks & MONEY_TOKS:
        # Use profile price for per-item price columns so it matches the product name/category
        if row_ctx and "item_price" in row_ctx and not tok("total", "subtotal", "revenue", "fee", "charge", "balance", "earning"):
            return row_ctx["item_price"]
        return round([4.99, 8.50, 12.99, 15.75, 22.50, 35.00, 5.75, 6.25, 11.99, 18.50, 9.75][vi % 11], 2)
    if tok("hourly") or (tok("wage") and not tok("rate")):
        return round([12.50, 15.00, 18.50, 13.75, 12.50, 16.00, 14.25, 12.50, 17.00, 13.00, 15.50][vi % 11], 2)
    if tok("salary", "annual") and not tok("anniversary"):
        return [32000, 45000, 52000, 38000, 61000, 29000, 48000, 55000, 42000, 67000, 51000][vi % 11]
    if tok("rate") and tok("interest", "commission"):
        return round([2.5, 3.0, 1.5, 4.0, 2.0, 3.5, 1.0, 4.5, 2.5, 3.0, 3.8][vi % 11], 2)
    if tok("percent", "pct", "percentage"):
        return round([15.5, 8.2, 22.0, 5.0, 18.5, 12.3, 30.0, 6.7, 25.0, 9.1, 11.5][vi % 11], 1)

    # ── 5. Counts / Quantities ────────────────────────────────────────────────────
    if "calori" in n or (tok("cal") and tok("kcal", "intake", "burn")):
        return [280, 360, 440, 520, 380, 320, 480, 560, 290, 410, 350][vi % 11]
    if tok("point", "points") and not tok("price", "cost", "total"):
        return [150, 320, 80, 450, 220, 380, 90, 510, 175, 295, 230][vi % 11]
    if tok("loyalty") and not tok("name", "card", "program"):
        return [150, 320, 80, 450, 220, 380, 90, 510, 175, 295, 230][vi % 11]
    if tok("seat", "seating", "seats") or (tok("capacity") and not tok("storage", "memory", "production")):
        return [24, 36, 18, 48, 30, 42, 20, 55, 28, 40, 33][vi % 11]
    QTY_TOKS = {"qty", "quantity", "count", "units", "stock", "inventory", "threshold",
                "level", "limit", "reorder", "remaining", "onhand", "on_hand"}
    if toks & QTY_TOKS:
        return [100, 250, 40, 500, 75, 320, 180, 60, 420, 90, 155][vi % 11]
    if tok("duration", "minutes", "mins", "hours", "hrs", "seconds", "secs"):
        return [5, 10, 15, 20, 8, 12, 30, 7, 25, 18, 45][vi % 11]
    if tok("weight", "grams", "gram", "kg", "lbs", "oz", "ounce"):
        return [150, 230, 180, 95, 320, 270, 120, 200, 310, 85, 165][vi % 11]

    # ── 6. Contact ────────────────────────────────────────────────────────────────
    if tok("email") or (tok("mail") and not tok("direct", "postal")):
        first_lower = ["john", "jane", "mike", "sarah", "alex", "emily", "chris", "anna", "david", "lisa", "robert"]
        return f"{first_lower[vi % 11]}.{row_num}@example.com"
    PHONE_TOKS = {"phone", "mobile", "tel", "telephone", "cell", "fax"}
    if toks & PHONE_TOKS:
        area = [212, 310, 312, 713, 602, 215, 210, 619, 214, 408, 512]
        return f"({area[vi % 11]}) {500 + vi}-{1000 + vi * 7}"
    if tok("zip", "postal", "zipcode", "postcode"):
        return ["10001", "90001", "60601", "77001", "85001", "19101", "78201", "92101", "75201", "95101", "73301"][vi % 11]

    # ── 7. Promo / reference codes ────────────────────────────────────────────────
    CODE_TOKS = {"promo", "coupon", "voucher", "sku", "barcode", "upc", "ref"}
    if toks & CODE_TOKS:
        return ["SAVE10", "LOYAL25", "SUB5OFF", "NEWCUST", "MEMBER15",
                "HOLIDAY20", "NONE", "VIP30", "COMBO5", "BDAY10", "SUMMER15"][vi % 11]
    if tok("code") and not tok("zip", "postal", "area", "country", "state", "language", "currency"):
        return ["A1001", "B2045", "C3072", "D1198", "E4023",
                "F5066", "G2031", "H3087", "I1044", "J6012", "K7099"][vi % 11]

    # ── 8. Names (person) ────────────────────────────────────────────────────────
    if n in ("first_name", "firstname") or (tok("first", "given") and tok("name")):
        return FIRST[vi % 11]
    if n in ("last_name", "lastname", "surname") or (tok("last", "family", "sur") and tok("name")):
        return LAST[vi % 11]

    # Person-role + tier/type → classification, not a name
    PERSON_TOKS = {"customer", "client", "user", "person", "guest", "member",
                   "employee", "staff", "worker", "cashier", "server", "manager",
                   "supervisor", "operator", "associate", "rep", "driver",
                   "attendant", "agent", "contact", "recipient"}
    TYPE_LIKE   = {"type", "kind", "tier", "level", "class", "group", "segment", "rank", "category"}
    if (toks & PERSON_TOKS) and (toks & TYPE_LIKE):
        return ["Regular", "VIP", "Premium", "New", "Returning", "Member",
                "Gold", "Silver", "Bronze", "Platinum", "Loyal"][vi % 11]

    # Vendor/supplier → company, not a person
    if tok("vendor", "supplier", "provider", "distributor", "wholesaler"):
        return ["Fresh Foods Co.", "National Produce", "Sysco Distribution", "US Foods", "Fresh Direct",
                "Farm to Table LLC", "Quality Meats Inc.", "Dairy Distributors", "Peak Supply Co.",
                "US Foods", "Prime Distributors"][vi % 11]

    # Person-role columns → full name
    if toks & PERSON_TOKS:
        return f"{FIRST[vi % 11]} {LAST[vi % 11]}"

    # ── 9. Locations ──────────────────────────────────────────────────────────────
    if tok("address"):
        return f"{STREETS[vi % 11]}, {CITIES[vi % 11]}"
    if n == "city" or n.endswith("_city") or n.startswith("city_"):
        return CITIES[vi % 11].split(",")[0].strip()
    STATE_TOKS = {"state", "province", "region"}
    if (toks & STATE_TOKS) and not tok("status", "statement", "estate", "interest"):
        return ["NY", "CA", "IL", "TX", "AZ", "PA", "TX", "CA", "TX", "CA", "TX"][vi % 11]
    if tok("country", "nation"):
        return ["USA", "USA", "USA", "USA", "USA", "Canada", "USA", "USA", "USA", "Mexico", "USA"][vi % 11]
    LOCATION_TOKS = {"store", "location", "branch", "outlet", "site", "venue", "place", "shop", "restaurant"}
    if toks & LOCATION_TOKS:
        if is_subway:
            return f"Subway #{1000 + vi} - {CITIES[vi % 11]}"
        if is_food:
            nm = company_name.split()[0] if company_name else "Location"
            return f"{nm} #{1000 + vi} - {CITIES[vi % 11]}"
        return CITIES[vi % 11]

    # ── 10. Status / payment / order channel ─────────────────────────────────────
    SHIP_TOKS = {"ship", "shipping", "carrier", "fulfillment", "courier", "dispatch"}
    if toks & SHIP_TOKS:
        if is_food:
            return ["Dine-In", "Takeout", "Delivery", "Mobile Order", "Curbside Pickup",
                    "Drive-Thru", "Dine-In", "Takeout", "Delivery", "Mobile Order", "Takeout"][vi % 11]
        return ["Standard Shipping", "Express Delivery", "Local Pickup", "Same-Day Delivery",
                "Free Shipping", "Overnight", "2-Day Shipping", "Economy", "Priority",
                "Scheduled Delivery", "Curbside Pickup"][vi % 11]
    if tok("status") and not tok("marital", "relationship"):
        return ["Active", "Completed", "Pending", "Active", "Cancelled",
                "Active", "Completed", "Active", "Pending", "Active", "On Hold"][vi % 11]
    PAYMENT_TOKS = {"payment", "pay_method"}
    if toks & PAYMENT_TOKS or (tok("payment") and tok("method", "type", "way", "option")):
        return ["Credit Card", "Cash", "Debit Card", "Mobile Pay", "Gift Card",
                "Credit Card", "Cash", "Mobile Pay", "Credit Card", "Debit Card", "Apple Pay"][vi % 11]
    if tok("order") and tok("type", "kind", "channel", "method"):
        return ["Dine-In", "Takeout", "Delivery", "Dine-In", "Takeout",
                "Mobile Order", "Dine-In", "Takeout", "Delivery", "Dine-In", "Curbside"][vi % 11]
    RATING_TOKS = {"rating", "score", "grade", "rank", "star", "stars", "review"}
    if toks & RATING_TOKS:
        return [4.5, 3.8, 4.9, 4.2, 3.5, 4.7, 4.1, 4.8, 3.9, 4.6, 4.3][vi % 11]

    # ── 11. Job / role ────────────────────────────────────────────────────────────
    JOB_TOKS = {"role", "title", "position", "job", "occupation", "designation"}
    if toks & JOB_TOKS:
        if is_food:
            return ["Sandwich Artist", "Shift Supervisor", "Store Manager", "Sandwich Artist",
                    "Assistant Manager", "Sandwich Artist", "Shift Supervisor", "Sandwich Artist",
                    "Team Lead", "Sandwich Artist", "Crew Member"][vi % 11]
        return ["Manager", "Associate", "Supervisor", "Coordinator", "Analyst",
                "Specialist", "Director", "Lead", "Senior Associate", "Manager", "Coordinator"][vi % 11]

    # ── 12. Food — specific sub-categories first ──────────────────────────────────
    BREAD_TOKS = {"bread", "bun", "roll", "loaf", "flatbread", "toast", "sub_roll"}
    if toks & BREAD_TOKS or (tok("wrap") and not tok("gift", "shipping", "package")):
        return ["Italian", "Wheat", "Herb & Cheese", "Flatbread", "9-Grain Wheat",
                "Italian White", "Sourdough", "Multigrain", "Wrap", "Gluten-Free", "Rye"][vi % 11]

    TOPPING_TOKS = {"topping", "toppings", "extra", "extras", "addon", "add_on", "garnish", "add"}
    if toks & TOPPING_TOKS:
        return ["Lettuce", "Tomato", "Onion", "Cheese", "Mayo",
                "Mustard", "Pickles", "Peppers", "Olives", "Spinach", "Avocado"][vi % 11]

    SAUCE_TOKS = {"sauce", "sauces", "dressing", "condiment", "spread", "aioli"}
    if toks & SAUCE_TOKS:
        return ["Ranch", "Honey Mustard", "Sweet Onion", "Chipotle SW", "Marinara",
                "Buffalo", "BBQ", "Caesar", "Balsamic", "Sriracha", "Pesto"][vi % 11]

    DRINK_TOKS = {"drink", "drinks", "beverage", "beverages", "soda", "juice", "coffee", "tea", "water"}
    if toks & DRINK_TOKS:
        return ["Fountain Soda", "Iced Tea", "Coffee", "Orange Juice", "Water",
                "Lemonade", "Milk", "Sports Drink", "Energy Drink", "Green Tea", "Apple Juice"][vi % 11]

    if tok("size", "portion", "serving") and not tok("font", "image", "file", "screen", "display"):
        if is_food:
            return ["6-inch", "Footlong", "6-inch", "Footlong", "6-inch",
                    "Kids Meal", "6-inch", "Footlong", "6-inch", "Footlong", "6-inch"][vi % 11]
        return ["Small", "Medium", "Large", "Small", "Medium",
                "Large", "Small", "Medium", "Large", "Small", "Medium"][vi % 11]

    if tok("ingredient", "ingredients"):
        return ["Lettuce", "Tomato", "Onion", "Cheese", "Mayo",
                "Mustard", "Pickles", "Peppers", "Olives", "Spinach", "Avocado"][vi % 11]

    if tok("unit", "units") and not tok("unique", "monetary", "business"):
        return ["kg", "lbs", "units", "cases", "kg", "lbs", "units", "kg", "cases", "lbs", "oz"][vi % 11]

    FRANCHISE_TOKS = {"franchise", "franchisee", "franchisor"}
    if toks & FRANCHISE_TOKS:
        return ["Metro Foods LLC", "City Eats Inc.", "Quick Serve Group", "Urban Dining Co.",
                "Fast Food Partners", "Local Bites LLC", "Prime Food Service", "Eagle Eats Corp.",
                "Star Dining Inc.", "Peak Foods LLC", "Summit Foods LLC"][vi % 11]

    # ── 13. Descriptions / notes (before broad food-item catch) ───────────────────
    DESC_TOKS = {"description", "desc", "detail", "details", "info", "information",
                 "note", "notes", "comment", "comments", "remark", "remarks",
                 "instruction", "instructions", "request", "requests", "special",
                 "feedback", "message", "text", "summary", "memo", "label"}
    if toks & DESC_TOKS:
        if is_food:
            return ["No onions", "Extra cheese", "Light sauce", "No tomatoes", "Extra meat",
                    "Toasted please", "Not toasted", "Cut in half", "Extra lettuce",
                    "No pickles", "Extra pickles"][vi % 11]
        return [f"Ref-{row_num:03d}", "See attached", "N/A", f"#{vi+1:04d}",
                "Standard", "Priority", "Verified", "See invoice",
                "Standard terms", "Per contract", f"Batch {vi+1}"][vi % 11]

    # ── 14. Broad food-item catch ─────────────────────────────────────────────────
    FOOD_TOKS = {"sandwich", "sub", "item", "items", "meal", "meals", "menu",
                 "food", "dish", "dishes", "entree", "combo", "deal",
                 "product", "products", "offering", "selection", "ordered"}
    if toks & FOOD_TOKS:
        if row_ctx and "item_name" in row_ctx:
            return row_ctx["item_name"]
        return SUBS[vi % 11]

    # ── 15. Category / type catch-all ─────────────────────────────────────────────
    if tok("name"):
        # Any remaining "_name" column (ingredient_name handled above, store covered, etc.)
        return f"{FIRST[vi % 11]} {LAST[vi % 11]}"

    CAT_TOKS = {"category", "categories", "type", "kind", "class", "group",
                "segment", "genre", "classification", "tier", "division", "section"}
    if toks & CAT_TOKS:
        if row_ctx and "item_category" in row_ctx:
            return row_ctx["item_category"]
        if is_food:
            return ["Sandwiches", "Wraps", "Salads", "Sides", "Drinks",
                    "Desserts", "Kids Meals", "Combos", "Breakfast", "Snacks", "Beverages"][vi % 11]
        return ["Category A", "Category B", "Category C", "Category A", "Category D",
                "Category B", "Category C", "Category A", "Category E", "Category B", "Category D"][vi % 11]

    # ── 16. Generic fallback — uses vi+1 so values differ across tables ───────────
    return f"{col.replace('_', ' ').replace('-', ' ').title()} {vi + 1}"


def _infer_col_type(col: str) -> str:
    n = re.sub(r'[^a-z0-9]+', '_', col.lower().strip()).strip('_')
    if n == "id" or n.endswith("_id"):
        return "INTEGER"
    if any(k in n for k in ("qty", "quantity", "count", "units", "stock", "points",
                             "seats", "capacity", "calori", "salary")):
        return "INTEGER"
    if any(k in n for k in ("price", "amount", "total", "cost", "revenue", "wage",
                             "fee", "charge", "rate", "rating", "score", "hourly")):
        return "DECIMAL"
    if any(k in n for k in ("date", "_dt", "_at", "since", "opened", "created", "hired", "joined")):
        return "DATE"
    if n.startswith("is_") or n.startswith("has_") or n in ("active", "available", "enabled"):
        return "BOOLEAN"
    return "TEXT"


def _generate_mock_from_columns(table_names: list[str], columns: list[str],
                                 num_rows: int, company_name: str = "",
                                 call_offset: int = 0) -> dict:
    """Generate a fresh dataset whose values match the given column names semantically.

    call_offset shifts all variety indices so repeated calls yield different values.
    Each table also gets its own tbl_idx offset so tables differ from each other.
    """
    tables = []
    for tbl_idx, tname in enumerate(table_names):
        rows = []
        for i in range(num_rows):
            vi = call_offset + tbl_idx * num_rows + i
            row_ctx = _make_row_ctx(vi, company_name)
            rows.append([_make_mock_cell(c, i + 1, vi, company_name, row_ctx) for c in columns])
        tables.append({
            "name": tname,
            "columns": [{"name": c, "type": _infer_col_type(c)} for c in columns],
            "rows": rows,
        })
    return {"tables": tables}


# Incremented on every generate_data call so each button press yields different values.
_gen_call_count: int = 0


def generate_data(industry: str, model: str, messy: bool,
                  company_name: str = "", company_context: str = "",
                  num_rows: int | None = None, num_cols: int | None = None,
                  custom_columns: list[str] | None = None) -> dict:
    global _gen_call_count
    if _MOCK_MODE:
        _gen_call_count += 1
        # 37 is coprime with 11 (list size) so every call shifts to a different
        # position in each value list.  Mod 1000 keeps the number manageable.
        call_offset = (_gen_call_count * 37) % 1000

        raw = _MOCK_DATA_MESSY[industry] if messy else _MOCK_DATA_CLEAN[industry]
        target_rows = num_rows if num_rows is not None else 10

        if custom_columns:
            table_names = [t["name"] for t in raw["tables"]]
            return _generate_mock_from_columns(
                table_names, custom_columns, target_rows, company_name, call_offset
            )

        # No custom columns — regenerate every table fresh from its own column names.
        # This makes values company-specific and different on every button press.
        result_tables = []
        for tbl_idx, tbl in enumerate(raw["tables"]):
            cols = tbl["columns"]
            if num_cols is not None:
                cols = cols[:num_cols]
            col_names = [c["name"] for c in cols]
            rows = []
            for i in range(target_rows):
                vi = call_offset + tbl_idx * target_rows + i
                row_ctx = _make_row_ctx(vi, company_name)
                rows.append([_make_mock_cell(c, i + 1, vi, company_name, row_ctx) for c in col_names])
            result_tables.append({"name": tbl["name"], "columns": cols, "rows": rows})
        return {"tables": result_tables}

    # Build system prompt with dynamic constraints
    constraints: list[str] = []
    if num_rows is not None:
        constraints.append(f"Generate exactly {num_rows} rows per table.")
    if custom_columns:
        col_list = ", ".join(f'"{c}"' for c in custom_columns)
        constraints.append(
            f"Every table MUST use exactly these column names (distributed sensibly across tables): {col_list}. "
            f"Generate realistic data values that match each column name's meaning."
        )
    elif num_cols is not None:
        constraints.append(f"Generate exactly {num_cols} columns per table.")
    base   = _GEN_SYSTEM_MESSY_BASE if messy else _GEN_SYSTEM_CLEAN_BASE
    system = base + ("\n" + "\n".join(constraints) if constraints else "")

    prompt = _PROMPTS[industry]
    if company_name or company_context:
        intro = f"This database is for {company_name}" if company_name else "This database is for a company"
        if company_context:
            intro += f", which {company_context.strip().rstrip('.')}"
        prompt = (f"{intro}. {prompt}\n"
                  "Tailor all values, names, amounts, and dates to be realistic for this specific company.")
    raw = _call_llm(model, system, prompt)
    return json.loads(_extract_json(raw))


# ── Mock data — MESSY column names ────────────────────────────────────────────
_MOCK_DATA_MESSY: dict[str, dict] = {
    "healthcare": {"tables": [
        {"name": "doctors", "columns": [
            {"name": "Doctor ID",       "type": "INTEGER"},
            {"name": "First Name",      "type": "TEXT"},
            {"name": "Last Name",       "type": "TEXT"},
            {"name": "SPECIALTY",       "type": "TEXT"},
            {"name": "Yrs. Experience", "type": "INTEGER"},
            {"name": "E-Mail",          "type": "TEXT"}],
         "rows": [
            [1,  "Sarah",   "Chen",     "Cardiology",    18, "s.chen@hospital.org"],
            [2,  "Marcus",  "Webb",     "Neurology",     12, "m.webb@hospital.org"],
            [3,  "Elena",   "Rossi",    "Pediatrics",     9, "e.rossi@hospital.org"],
            [4,  "James",   "Okafor",   "Orthopedics",   22, "j.okafor@hospital.org"],
            [5,  "Priya",   "Sharma",   "Oncology",      15, "p.sharma@hospital.org"],
            [6,  "Daniel",  "Park",     "Dermatology",    7, "d.park@hospital.org"],
            [7,  "Amara",   "Diallo",   "Psychiatry",    11, "a.diallo@hospital.org"],
            [8,  "Thomas",  "Mueller",  "Radiology",     20, "t.mueller@hospital.org"],
            [9,  "Sofia",   "Torres",   "Endocrinology", 14, "s.torres@hospital.org"],
            [10, "William", "Nakamura", "Emergency Med",  6, "w.nakamura@hospital.org"]]},
        {"name": "patients", "columns": [
            {"name": "Patient ID",        "type": "INTEGER"},
            {"name": "First Name",        "type": "TEXT"},
            {"name": "Last Name",         "type": "TEXT"},
            {"name": "Date-of-Birth",     "type": "DATE"},
            {"name": "GENDER",            "type": "TEXT"},
            {"name": "Blood Type",        "type": "TEXT"},
            {"name": "Primary Doctor ID", "type": "INTEGER"}],
         "rows": [
            [1,  "Olivia",  "Hart",    "1985-03-12", "F", "A+",  1],
            [2,  "Ethan",   "Brooks",  "1972-07-28", "M", "O-",  2],
            [3,  "Mia",     "Gonzalez","1990-11-05", "F", "B+",  3],
            [4,  "Noah",    "Kim",     "1965-01-19", "M", "AB+", 4],
            [5,  "Zara",    "Ali",     "1998-06-30", "F", "O+",  1],
            [6,  "Liam",    "Fischer", "1958-09-14", "M", "A-",  5],
            [7,  "Chloe",   "Petit",   "2002-04-22", "F", "B-",  3],
            [8,  "Elijah",  "Brown",   "1980-12-03", "M", "O+",  6],
            [9,  "Amelia",  "Ivanova", "1975-08-17", "F", "A+",  7],
            [10, "Lucas",   "Nguyen",  "1993-02-09", "M", "AB-", 2]]},
        {"name": "appointments", "columns": [
            {"name": "Appt. ID",       "type": "INTEGER"},
            {"name": "Patient ID",     "type": "INTEGER"},
            {"name": "Doctor ID",      "type": "INTEGER"},
            {"name": "Appt. Date",     "type": "DATE"},
            {"name": "STATUS",         "type": "TEXT"},
            {"name": "Chief Complaint","type": "TEXT"}],
         "rows": [
            [1,  1,  1,  "2025-01-08", "Completed",  "Chest pain and shortness of breath"],
            [2,  2,  2,  "2025-01-10", "Completed",  "Persistent headaches"],
            [3,  3,  3,  "2025-01-14", "Scheduled",  "Annual wellness check"],
            [4,  4,  4,  "2025-01-15", "Completed",  "Right knee pain"],
            [5,  5,  1,  "2025-01-17", "Cancelled",  "Palpitations follow-up"],
            [6,  6,  5,  "2025-01-20", "Scheduled",  "Fatigue and weight loss"],
            [7,  7,  3,  "2025-01-21", "Completed",  "Rash on forearm"],
            [8,  8,  6,  "2025-01-22", "Completed",  "Anxiety and sleep issues"],
            [9,  9,  7,  "2025-01-24", "Scheduled",  "Mood swings evaluation"],
            [10, 10, 2,  "2025-01-27", "Completed",  "Dizziness and nausea"]]},
        {"name": "prescriptions", "columns": [
            {"name": "Rx ID",             "type": "INTEGER"},
            {"name": "Patient ID",        "type": "INTEGER"},
            {"name": "Doctor ID",         "type": "INTEGER"},
            {"name": "Medication",        "type": "TEXT"},
            {"name": "Dosage/Freq.",      "type": "TEXT"},
            {"name": "Date Prescribed",   "type": "DATE"},
            {"name": "Refills Remaining", "type": "INTEGER"}],
         "rows": [
            [1,  1,  1,  "Metoprolol",    "50mg once daily",   "2025-01-08", 3],
            [2,  2,  2,  "Sumatriptan",   "100mg as needed",   "2025-01-10", 5],
            [3,  4,  4,  "Ibuprofen",     "400mg 3x daily",    "2025-01-15", 2],
            [4,  6,  5,  "Levothyroxine", "75mcg once daily",  "2025-01-20", 11],
            [5,  8,  6,  "Sertraline",    "50mg once daily",   "2025-01-22", 6],
            [6,  9,  7,  "Escitalopram",  "10mg once daily",   "2025-01-24", 5],
            [7,  10, 2,  "Meclizine",     "25mg as needed",    "2025-01-27", 3],
            [8,  3,  3,  "Amoxicillin",   "500mg 3x daily",    "2025-01-14", 0],
            [9,  5,  1,  "Atenolol",      "25mg once daily",   "2025-01-17", 4],
            [10, 7,  3,  "Hydrocortisone","1% cream 2x daily", "2025-01-21", 2]]}
    ]},
    "financial": {"tables": [
        {"name": "customers", "columns": [
            {"name": "CUSTOMER_ID",  "type": "INTEGER"},
            {"name": "First Name",   "type": "TEXT"},
            {"name": "Last Name",    "type": "TEXT"},
            {"name": "E-Mail",       "type": "TEXT"},
            {"name": "Credit Score", "type": "INTEGER"},
            {"name": "Member Since", "type": "DATE"}],
         "rows": [
            [1,  "Rachel",  "Monroe",    "r.monroe@email.com",   780, "2018-03-15"],
            [2,  "Derek",   "Sandoval",  "d.sandoval@email.com", 650, "2020-07-22"],
            [3,  "Ingrid",  "Svensson",  "i.svensson@email.com", 820, "2016-01-08"],
            [4,  "Carlos",  "Reyes",     "c.reyes@email.com",    590, "2022-11-30"],
            [5,  "Fatima",  "Al-Rashid", "f.alrashid@email.com", 740, "2019-05-17"],
            [6,  "George",  "Papadakis", "g.papadakis@email.com",670, "2021-09-04"],
            [7,  "Mei",     "Huang",     "m.huang@email.com",    800, "2017-06-20"],
            [8,  "Aaron",   "Mitchell",  "a.mitchell@email.com", 720, "2020-02-14"],
            [9,  "Natasha", "Petrov",    "n.petrov@email.com",   610, "2023-04-01"],
            [10, "Oliver",  "Adeyemi",   "o.adeyemi@email.com",  755, "2018-12-19"]]},
        {"name": "products", "columns": [
            {"name": "Product ID",      "type": "INTEGER"},
            {"name": "Product Name",    "type": "TEXT"},
            {"name": "CATEGORY",        "type": "TEXT"},
            {"name": "Interest Rate %", "type": "DECIMAL"},
            {"name": "Min. Balance",    "type": "DECIMAL"}],
         "rows": [
            [1,  "Premium Checking",     "Checking",      0.01,    500.00],
            [2,  "High-Yield Savings",   "Savings",       4.50,   1000.00],
            [3,  "Standard Checking",    "Checking",      0.00,      0.00],
            [4,  "Money Market Account", "Savings",       4.10,   5000.00],
            [5,  "Platinum Credit Card", "Credit Card",  18.99,      0.00],
            [6,  "Cash-Back Card",       "Credit Card",  21.49,      0.00],
            [7,  "Auto Loan",            "Personal Loan",  6.75,    0.00],
            [8,  "Personal Loan",        "Personal Loan", 11.25,    0.00],
            [9,  "Student Savings",      "Savings",        3.80,  250.00],
            [10, "Business Checking",    "Checking",       0.02, 2500.00]]},
        {"name": "accounts", "columns": [
            {"name": "Account ID",  "type": "INTEGER"},
            {"name": "CUSTOMER_ID", "type": "INTEGER"},
            {"name": "Product ID",  "type": "INTEGER"},
            {"name": "BALANCE ($)", "type": "DECIMAL"},
            {"name": "Currency",    "type": "TEXT"},
            {"name": "Date Opened", "type": "DATE"}],
         "rows": [
            [1,  1,  1,  12450.00, "USD", "2018-03-20"],
            [2,  1,  2,  45200.75, "USD", "2019-06-01"],
            [3,  2,  3,   3820.50, "USD", "2020-07-25"],
            [4,  3,  4,  98100.00, "USD", "2016-02-14"],
            [5,  3,  5,      0.00, "USD", "2018-08-30"],
            [6,  4,  3,   1205.30, "USD", "2022-12-05"],
            [7,  5,  2,  27650.00, "USD", "2019-05-22"],
            [8,  6,  6,      0.00, "USD", "2021-09-10"],
            [9,  7,  4, 115000.00, "USD", "2017-07-01"],
            [10, 8,  1,   8730.20, "USD", "2020-03-01"]]},
        {"name": "transactions", "columns": [
            {"name": "Txn ID",        "type": "INTEGER"},
            {"name": "Account ID",    "type": "INTEGER"},
            {"name": "Txn Date",      "type": "DATE"},
            {"name": "AMOUNT",        "type": "DECIMAL"},
            {"name": "Txn Type",      "type": "TEXT"},
            {"name": "Description",   "type": "TEXT"},
            {"name": "Merchant Name", "type": "TEXT"}],
         "rows": [
            [1,  1,  "2025-01-05",   52.30, "Debit",  "Grocery shopping",        "Whole Foods"],
            [2,  1,  "2025-01-07", 1200.00, "Debit",  "Rent payment",            "Property Mgmt"],
            [3,  2,  "2025-01-08",  500.00, "Credit", "Interest earned",         "Bank"],
            [4,  3,  "2025-01-09",   87.45, "Debit",  "Restaurant dinner",       "The Oak Bistro"],
            [5,  5,  "2025-01-10",  340.00, "Debit",  "Online purchase",         "Amazon"],
            [6,  7,  "2025-01-12",  200.00, "Credit", "Payroll deposit",         "Employer"],
            [7,  4,  "2025-01-14", 2500.00, "Debit",  "Wire transfer",           "Escrow Co."],
            [8,  6,  "2025-01-15",   65.00, "Debit",  "Streaming subscriptions", "Netflix"],
            [9,  9,  "2025-01-18", 4200.00, "Credit", "Investment withdrawal",   "Vanguard"],
            [10, 10, "2025-01-20",  450.50, "Debit",  "Office supplies",         "Staples"]]}
    ]},
    "technology": {"tables": [
        {"name": "employees", "columns": [
            {"name": "Emp. ID",    "type": "INTEGER"},
            {"name": "First Name", "type": "TEXT"},
            {"name": "Last Name",  "type": "TEXT"},
            {"name": "Job Title",  "type": "TEXT"},
            {"name": "Team/Dept.", "type": "TEXT"},
            {"name": "YoE (Yrs)", "type": "INTEGER"},
            {"name": "E-Mail",    "type": "TEXT"}],
         "rows": [
            [1,  "Lena",   "Okafor",   "Senior Engineer",     "Backend", 8,  "l.okafor@techcorp.io"],
            [2,  "Raj",    "Mehta",    "Product Manager",     "Product", 10, "r.mehta@techcorp.io"],
            [3,  "Sofia",  "Bauer",    "UX Designer",         "Design",  5,  "s.bauer@techcorp.io"],
            [4,  "Marcus", "Lee",      "Junior Engineer",     "Frontend",2,  "m.lee@techcorp.io"],
            [5,  "Yuki",   "Tanaka",   "Data Engineer",       "Data",    6,  "y.tanaka@techcorp.io"],
            [6,  "Aisha",  "Rahman",   "DevOps Engineer",     "Infra",   7,  "a.rahman@techcorp.io"],
            [7,  "Carlos", "Vega",     "QA Engineer",         "QA",      4,  "c.vega@techcorp.io"],
            [8,  "Emily",  "Brooks",   "Senior Engineer",     "Frontend",9,  "e.brooks@techcorp.io"],
            [9,  "Dmitri", "Popov",    "ML Engineer",         "Data",    5,  "d.popov@techcorp.io"],
            [10, "Nia",    "Asante",   "Engineering Manager", "Backend", 12, "n.asante@techcorp.io"]]},
        {"name": "projects", "columns": [
            {"name": "Project ID",   "type": "INTEGER"},
            {"name": "Project Name", "type": "TEXT"},
            {"name": "Lead Emp. ID", "type": "INTEGER"},
            {"name": "Start Dt.",    "type": "DATE"},
            {"name": "Due Dt.",      "type": "DATE"},
            {"name": "STATUS",       "type": "TEXT"},
            {"name": "Budget ($)",   "type": "DECIMAL"}],
         "rows": [
            [1,  "AIDA Platform v2",          10, "2024-07-01", "2025-03-31", "Active",    420000.00],
            [2,  "Mobile App Redesign",        2,  "2024-09-01", "2025-02-28", "Completed", 185000.00],
            [3,  "Data Pipeline Upgrade",      5,  "2024-10-15", "2025-05-30", "Active",    95000.00],
            [4,  "Security Hardening",         6,  "2024-11-01", "2025-01-31", "Completed", 60000.00],
            [5,  "Customer Portal",            2,  "2025-01-10", "2025-06-30", "Active",    230000.00],
            [6,  "Analytics Dashboard",        9,  "2024-12-01", "2025-04-15", "Active",    140000.00],
            [7,  "CI/CD Overhaul",             6,  "2025-01-15", "2025-03-15", "Active",    45000.00],
            [8,  "API Rate Limiting",          1,  "2025-02-01", "2025-03-01", "Completed", 22000.00],
            [9,  "ML Recommendation Engine",   9,  "2025-02-10", "2025-07-31", "Active",    310000.00],
            [10, "Accessibility Audit",        3,  "2025-01-05", "2025-02-28", "Completed", 18000.00]]},
        {"name": "bugs", "columns": [
            {"name": "Bug ID",        "type": "INTEGER"},
            {"name": "Project ID",    "type": "INTEGER"},
            {"name": "Reporter ID",   "type": "INTEGER"},
            {"name": "Title/Summary", "type": "TEXT"},
            {"name": "SEVERITY",      "type": "TEXT"},
            {"name": "Reported Dt.",  "type": "DATE"},
            {"name": "STATUS",        "type": "TEXT"}],
         "rows": [
            [1,  1, 4,  "Login timeout not handled",      "High",     "2025-01-08", "Open"],
            [2,  2, 7,  "Image upload fails on iOS",      "Medium",   "2025-01-10", "Closed"],
            [3,  3, 5,  "Null pointer in ETL job",        "Critical", "2025-01-12", "Open"],
            [4,  4, 6,  "TLS handshake error on load",    "High",     "2025-01-14", "Closed"],
            [5,  5, 3,  "Button misaligned on Safari",    "Low",      "2025-01-16", "Open"],
            [6,  6, 9,  "Chart renders NaN values",       "Medium",   "2025-01-18", "In Progress"],
            [7,  1, 1,  "Session token not refreshed",    "Critical", "2025-01-20", "In Progress"],
            [8,  7, 6,  "Pipeline fails on ARM arch",     "High",     "2025-01-22", "Open"],
            [9,  9, 9,  "Model returns empty array",      "Medium",   "2025-01-24", "Open"],
            [10, 5, 4,  "Form validation bypassed",       "High",     "2025-01-26", "In Progress"]]},
        {"name": "deployments", "columns": [
            {"name": "Deploy ID",   "type": "INTEGER"},
            {"name": "Project ID",  "type": "INTEGER"},
            {"name": "Deploy Dt.",  "type": "DATE"},
            {"name": "Env.",        "type": "TEXT"},
            {"name": "Version #",   "type": "TEXT"},
            {"name": "Deployed By", "type": "INTEGER"},
            {"name": "Success?",    "type": "BOOLEAN"}],
         "rows": [
            [1,  4, "2025-01-08", "Production", "v1.4.2",       6,  True],
            [2,  2, "2025-01-10", "Staging",    "v2.1.0-rc1",   8,  True],
            [3,  8, "2025-01-14", "Production", "v3.0.1",       1,  True],
            [4,  2, "2025-01-18", "Production", "v2.1.0",       8,  True],
            [5,  4, "2025-01-20", "Production", "v1.4.3",       6,  False],
            [6,  1, "2025-01-22", "Staging",    "v2.0.0-beta",  10, True],
            [7,  7, "2025-01-25", "Dev",        "v0.9.0",       6,  True],
            [8,  3, "2025-01-27", "Staging",    "v4.2.0-alpha", 5,  True],
            [9,  6, "2025-01-29", "Production", "v1.0.0",       9,  True],
            [10, 5, "2025-02-01", "Dev",        "v0.3.0",       8,  True]]}
    ]},
    "retail": {"tables": [
        {"name": "products", "columns": [
            {"name": "Prod. ID",       "type": "INTEGER"},
            {"name": "Product Name",   "type": "TEXT"},
            {"name": "Category/Dept",  "type": "TEXT"},
            {"name": "Unit Price ($)", "type": "DECIMAL"},
            {"name": "Stock Qty.",     "type": "INTEGER"},
            {"name": "SKU#",           "type": "TEXT"}],
         "rows": [
            [1,  "Wireless Headphones",          "Electronics",      79.99,  340,  "SKU-WH-001"],
            [2,  "Yoga Mat",                     "Sports & Fitness", 34.99,  520,  "SKU-YM-002"],
            [3,  "Stainless Steel Water Bottle", "Kitchen",          24.99,  810,  "SKU-WB-003"],
            [4,  "Running Shoes (Size 10)",      "Footwear",        119.99,  145,  "SKU-RS-004"],
            [5,  "Organic Coffee Beans 1lb",     "Grocery",          18.99, 1200,  "SKU-CB-005"],
            [6,  "Laptop Stand",                 "Office",           49.99,  420,  "SKU-LS-006"],
            [7,  "Resistance Band Set",          "Sports & Fitness", 22.99,  670,  "SKU-RB-007"],
            [8,  "Ceramic Cookware Set",         "Kitchen",         149.99,   88,  "SKU-CS-008"],
            [9,  "Bluetooth Speaker",            "Electronics",      59.99,  295,  "SKU-BS-009"],
            [10, "Bamboo Cutting Board",         "Kitchen",          29.99,  430,  "SKU-CB-010"]]},
        {"name": "customers", "columns": [
            {"name": "Cust. ID",    "type": "INTEGER"},
            {"name": "First Name",  "type": "TEXT"},
            {"name": "Last Name",   "type": "TEXT"},
            {"name": "E-Mail",      "type": "TEXT"},
            {"name": "Member Tier", "type": "TEXT"},
            {"name": "Join Date",   "type": "DATE"}],
         "rows": [
            [1,  "Hannah",  "Zhou",     "h.zhou@email.com",    "Gold",     "2022-03-14"],
            [2,  "James",   "Carter",   "j.carter@email.com",  "Silver",   "2023-07-01"],
            [3,  "Fatima",  "Hassan",   "f.hassan@email.com",  "Platinum", "2020-11-22"],
            [4,  "Luca",    "Ferrari",  "l.ferrari@email.com", "Bronze",   "2024-01-09"],
            [5,  "Sophie",  "Martin",   "s.martin@email.com",  "Gold",     "2021-05-30"],
            [6,  "David",   "Osei",     "d.osei@email.com",    "Silver",   "2023-02-17"],
            [7,  "Maria",   "Santos",   "m.santos@email.com",  "Platinum", "2019-08-05"],
            [8,  "Alex",    "Kim",      "a.kim@email.com",     "Bronze",   "2024-03-28"],
            [9,  "Priya",   "Kapoor",   "p.kapoor@email.com",  "Gold",     "2022-10-11"],
            [10, "Ryan",    "Walsh",    "r.walsh@email.com",   "Silver",   "2023-06-04"]]},
        {"name": "orders", "columns": [
            {"name": "Order ID",    "type": "INTEGER"},
            {"name": "Cust. ID",    "type": "INTEGER"},
            {"name": "Order Dt.",   "type": "DATE"},
            {"name": "TOTAL ($)",   "type": "DECIMAL"},
            {"name": "STATUS",      "type": "TEXT"},
            {"name": "Ship Method", "type": "TEXT"}],
         "rows": [
            [1,  3, "2025-01-05", 229.97, "Shipped",    "Express"],
            [2,  1, "2025-01-07", 104.98, "Delivered",  "Standard"],
            [3,  5, "2025-01-09",  34.99, "Delivered",  "Standard"],
            [4,  7, "2025-01-11", 199.98, "Shipped",    "Express"],
            [5,  2, "2025-01-13",  79.99, "Processing", "Standard"],
            [6,  9, "2025-01-15",  67.98, "Delivered",  "Standard"],
            [7,  3, "2025-01-17", 149.99, "Shipped",    "Express"],
            [8,  6, "2025-01-19",  52.98, "Delivered",  "Economy"],
            [9,  4, "2025-01-21", 119.99, "Processing", "Express"],
            [10, 7, "2025-01-23",  94.97, "Delivered",  "Standard"]]},
        {"name": "order_items", "columns": [
            {"name": "Item ID",       "type": "INTEGER"},
            {"name": "Order ID",      "type": "INTEGER"},
            {"name": "Prod. ID",      "type": "INTEGER"},
            {"name": "Qty.",          "type": "INTEGER"},
            {"name": "Unit Price ($)","type": "DECIMAL"},
            {"name": "Discount %",    "type": "DECIMAL"}],
         "rows": [
            [1,  1,  1,  1,  79.99, 0.00],
            [2,  1,  8,  1, 149.99, 0.00],
            [3,  2,  6,  2,  49.99, 0.00],
            [4,  2,  2,  1,  34.99, 10.00],
            [5,  3,  2,  1,  34.99, 0.00],
            [6,  4,  4,  1, 119.99, 0.00],
            [7,  4,  9,  1,  59.99, 10.00],
            [8,  5,  1,  1,  79.99, 0.00],
            [9,  6,  7,  2,  22.99, 0.00],
            [10, 6,  3,  1,  24.99, 5.00]]}
    ]},
    "manufacturing": {"tables": [
        {"name": "facilities", "columns": [
            {"name": "Facility ID",          "type": "INTEGER"},
            {"name": "Facility Name",        "type": "TEXT"},
            {"name": "LOCATION",             "type": "TEXT"},
            {"name": "Capacity (Units/Day)", "type": "INTEGER"},
            {"name": "Year Built",           "type": "INTEGER"},
            {"name": "Active?",              "type": "BOOLEAN"}],
         "rows": [
            [1,  "Northgate Plant",    "Detroit, MI",       2400, 1998, True],
            [2,  "Riverside Works",    "Louisville, KY",    1800, 2005, True],
            [3,  "Southfield Factory", "Nashville, TN",     3200, 2011, True],
            [4,  "Eastbrook Hub",      "Cleveland, OH",     1500, 1995, False],
            [5,  "Pacific Assembly",   "Portland, OR",      2100, 2018, True],
            [6,  "Central Forge",      "Indianapolis, IN",  2800, 2002, True],
            [7,  "Gulf Coast Plant",   "Houston, TX",       3500, 2015, True],
            [8,  "Northern Press",     "Minneapolis, MN",   1900, 2008, True],
            [9,  "Mountain Works",     "Denver, CO",        2200, 2020, True],
            [10, "Atlantic Fab",       "Baltimore, MD",     2000, 2000, True]]},
        {"name": "equipment", "columns": [
            {"name": "Equip. ID",       "type": "INTEGER"},
            {"name": "Facility ID",     "type": "INTEGER"},
            {"name": "Equip. Name",     "type": "TEXT"},
            {"name": "MANUFACTURER",    "type": "TEXT"},
            {"name": "Mfg. Year",       "type": "INTEGER"},
            {"name": "Last Maint. Dt.", "type": "DATE"}],
         "rows": [
            [1,  1,  "CNC Milling Machine",      "Haas Automation",  2010, "2025-01-03"],
            [2,  1,  "Industrial Press",          "Schuler AG",       2008, "2024-12-15"],
            [3,  2,  "Welding Robot",             "FANUC",            2015, "2025-01-10"],
            [4,  3,  "Assembly Line Conveyor",    "Bosch Rexroth",    2012, "2025-01-08"],
            [5,  3,  "Paint Booth",               "Eisenmann",        2014, "2024-11-20"],
            [6,  5,  "Laser Cutter",              "Trumpf",           2019, "2025-01-05"],
            [7,  6,  "Hydraulic Stamping Press",  "Schuler AG",       2003, "2024-10-30"],
            [8,  7,  "Extrusion Machine",         "Krauss-Maffei",    2016, "2025-01-12"],
            [9,  9,  "3D Metal Printer",          "EOS",              2021, "2025-01-15"],
            [10, 10, "Quality Vision System",     "Keyence",          2018, "2025-01-07"]]},
        {"name": "production_runs", "columns": [
            {"name": "Run ID",         "type": "INTEGER"},
            {"name": "Facility ID",    "type": "INTEGER"},
            {"name": "Product Line",   "type": "TEXT"},
            {"name": "Start Dt.",      "type": "DATE"},
            {"name": "End Dt.",        "type": "DATE"},
            {"name": "Units Produced", "type": "INTEGER"},
            {"name": "SHIFT",          "type": "TEXT"}],
         "rows": [
            [1,  1,  "Automotive Parts",               "2025-01-06", "2025-01-10", 12400, "Day"],
            [2,  2,  "HVAC Components",                "2025-01-07", "2025-01-09",  5600, "Day"],
            [3,  3,  "Consumer Electronics Housing",   "2025-01-08", "2025-01-15", 22800, "Night"],
            [4,  5,  "Precision Brackets",             "2025-01-06", "2025-01-08",  8400, "Day"],
            [5,  6,  "Heavy Machinery Frames",         "2025-01-09", "2025-01-14",  6200, "Day"],
            [6,  7,  "Plastic Extrusions",             "2025-01-10", "2025-01-20", 45000, "Night"],
            [7,  9,  "Aerospace Prototypes",           "2025-01-13", "2025-01-17",   520, "Day"],
            [8,  1,  "Automotive Parts",               "2025-01-13", "2025-01-17", 13200, "Night"],
            [9,  3,  "Medical Device Casings",         "2025-01-16", "2025-01-22", 18600, "Day"],
            [10, 10, "Structural Steel Components",    "2025-01-14", "2025-01-19",  9800, "Day"]]},
        {"name": "quality_checks", "columns": [
            {"name": "Check ID",      "type": "INTEGER"},
            {"name": "Run ID",        "type": "INTEGER"},
            {"name": "Equip. ID",     "type": "INTEGER"},
            {"name": "Defect Rate %", "type": "DECIMAL"},
            {"name": "Check Dt.",     "type": "DATE"},
            {"name": "RESULT",        "type": "TEXT"},
            {"name": "Inspector ID",  "type": "INTEGER"}],
         "rows": [
            [1,  1,  1,  0.8, "2025-01-11", "Pass", 3],
            [2,  2,  3,  1.2, "2025-01-10", "Pass", 5],
            [3,  3,  4,  2.1, "2025-01-16", "Fail", 7],
            [4,  4,  6,  0.5, "2025-01-09", "Pass", 2],
            [5,  5,  7,  3.4, "2025-01-15", "Fail", 4],
            [6,  6,  8,  0.9, "2025-01-21", "Pass", 6],
            [7,  7,  9,  0.3, "2025-01-18", "Pass", 1],
            [8,  8,  1,  1.5, "2025-01-18", "Pass", 3],
            [9,  9,  4,  0.7, "2025-01-23", "Pass", 7],
            [10, 10, 10, 1.1, "2025-01-20", "Pass", 2]]}
    ]},
    "energy": {"tables": [
        {"name": "plants", "columns": [
            {"name": "Plant ID",        "type": "INTEGER"},
            {"name": "Plant Name",      "type": "TEXT"},
            {"name": "Energy Type",     "type": "TEXT"},
            {"name": "Capacity (MW)",   "type": "DECIMAL"},
            {"name": "Online Date",     "type": "DATE"},
            {"name": "STATE",           "type": "TEXT"}],
         "rows": [
            [1,  "Sunridge Solar Farm",    "Solar",         250.0, "2021-06-15", "AZ"],
            [2,  "Lakeside Wind Array",    "Wind",          180.0, "2019-03-22", "TX"],
            [3,  "Rivergate Hydro",        "Hydroelectric", 400.0, "2005-09-01", "WA"],
            [4,  "Westfield Gas Turbine",  "Natural Gas",   620.0, "2010-04-17", "TX"],
            [5,  "Desert Peak Solar",      "Solar",         315.0, "2023-01-10", "NV"],
            [6,  "Highland Wind Farm",     "Wind",          220.0, "2018-11-05", "IA"],
            [7,  "Coastal Nuclear Sta.",   "Nuclear",      1100.0, "1988-07-30", "SC"],
            [8,  "Clearwater Coal Plant",  "Coal",          750.0, "1995-02-14", "WV"],
            [9,  "Northbay Biomass",       "Biomass",        85.0, "2017-08-19", "ME"],
            [10, "Summit Geothermal",      "Geothermal",     45.0, "2020-05-28", "NV"]]},
        {"name": "meters", "columns": [
            {"name": "Meter ID",               "type": "INTEGER"},
            {"name": "Plant ID",               "type": "INTEGER"},
            {"name": "Meter Type",             "type": "TEXT"},
            {"name": "Install Dt.",            "type": "DATE"},
            {"name": "Last Reading (kWh)",     "type": "DECIMAL"},
            {"name": "Status",                 "type": "TEXT"}],
         "rows": [
            [1,  1, "Generation",   "2021-06-15",  1842500.00, "Active"],
            [2,  1, "Distribution", "2021-06-15",  1798000.00, "Active"],
            [3,  2, "Generation",   "2019-03-22",  2310000.00, "Active"],
            [4,  3, "Generation",   "2005-09-01",  8940000.00, "Active"],
            [5,  4, "Generation",   "2010-04-17", 12450000.00, "Active"],
            [6,  4, "Backup",       "2015-06-01",   340000.00, "Standby"],
            [7,  5, "Generation",   "2023-01-10",   620000.00, "Active"],
            [8,  7, "Generation",   "1988-07-30", 45600000.00, "Active"],
            [9,  8, "Generation",   "1995-02-14", 38200000.00, "Active"],
            [10, 9, "Generation",   "2017-08-19",  1840000.00, "Active"]]},
        {"name": "consumption_records", "columns": [
            {"name": "Record ID",         "type": "INTEGER"},
            {"name": "Meter ID",          "type": "INTEGER"},
            {"name": "Record Dt.",        "type": "DATE"},
            {"name": "kWh Consumed",      "type": "DECIMAL"},
            {"name": "Peak Demand (kW)",  "type": "DECIMAL"},
            {"name": "Cost/kWh ($)",      "type": "DECIMAL"}],
         "rows": [
            [1,  1,  "2025-01-01",  6850.00,  320.5, 0.04],
            [2,  3,  "2025-01-01", 18400.00,  890.0, 0.03],
            [3,  5,  "2025-01-01", 14200.00,  680.0, 0.05],
            [4,  8,  "2025-01-01", 48600.00, 1250.0, 0.06],
            [5,  1,  "2025-01-08",  7200.00,  340.0, 0.04],
            [6,  3,  "2025-01-08", 19100.00,  915.0, 0.03],
            [7,  5,  "2025-01-08", 13800.00,  660.0, 0.05],
            [8,  4,  "2025-01-08", 42300.00,  980.0, 0.06],
            [9,  7,  "2025-01-08", 88500.00, 2100.0, 0.02],
            [10, 10, "2025-01-08",  5100.00,  180.0, 0.07]]},
        {"name": "maintenance_logs", "columns": [
            {"name": "Log ID",        "type": "INTEGER"},
            {"name": "Plant ID",      "type": "INTEGER"},
            {"name": "Maint. Type",   "type": "TEXT"},
            {"name": "Scheduled Dt.", "type": "DATE"},
            {"name": "Completed Dt.", "type": "DATE"},
            {"name": "Cost ($)",      "type": "DECIMAL"},
            {"name": "Technician ID", "type": "INTEGER"}],
         "rows": [
            [1,  1, "Scheduled Inspection", "2025-01-05", "2025-01-05",  4200.00, 7],
            [2,  3, "Turbine Overhaul",     "2025-01-10", "2025-01-14", 28000.00, 3],
            [3,  4, "Filter Replacement",   "2025-01-08", "2025-01-08",  1800.00, 5],
            [4,  2, "Blade Inspection",     "2025-01-12", "2025-01-13",  9500.00, 4],
            [5,  7, "Annual Safety Audit",  "2025-01-15", "2025-01-20", 85000.00, 1],
            [6,  5, "Panel Cleaning",       "2025-01-06", "2025-01-06",  2200.00, 8],
            [7,  8, "Boiler Maintenance",   "2025-01-09", "2025-01-11", 15000.00, 6],
            [8,  9, "Biomass Feeder Svc",   "2025-01-14", "2025-01-15",  6800.00, 2],
            [9,  6, "Gearbox Inspection",   "2025-01-17", "2025-01-18", 12000.00, 4],
            [10, 10,"Heat Exchanger Clean", "2025-01-20", "2025-01-20",  5500.00, 9]]}
    ]},
    "construction": {"tables": [
        {"name": "properties", "columns": [
            {"name": "Prop. ID",    "type": "INTEGER"},
            {"name": "Address",     "type": "TEXT"},
            {"name": "City",        "type": "TEXT"},
            {"name": "# Bedrooms",  "type": "INTEGER"},
            {"name": "# Bathrooms", "type": "DECIMAL"},
            {"name": "Sq. Ft.",     "type": "INTEGER"},
            {"name": "Year Built",  "type": "INTEGER"}],
         "rows": [
            [1,  "412 Maple St",      "Austin, TX",      3, 2.0, 1850, 1998],
            [2,  "77 Lakeview Dr",    "Denver, CO",      4, 2.5, 2400, 2005],
            [3,  "1902 Birch Ave",    "Seattle, WA",     2, 1.0,  980, 1985],
            [4,  "38 Harbor Blvd",   "Miami, FL",       5, 3.5, 3800, 2018],
            [5,  "514 Oak Ln",        "Nashville, TN",   3, 2.0, 1640, 2001],
            [6,  "91 Crestwood Cir", "Phoenix, AZ",     4, 3.0, 2950, 2015],
            [7,  "203 Elm St",        "Portland, OR",    2, 1.5, 1120, 1972],
            [8,  "650 Ridgeline Rd",  "Scottsdale, AZ",  6, 4.0, 4600, 2010],
            [9,  "15 Pinecrest Way",  "Boulder, CO",     3, 2.0, 1760, 2008],
            [10, "744 Riverside Dr",  "Chicago, IL",     2, 2.0, 1350, 1994]]},
        {"name": "agents", "columns": [
            {"name": "Agent ID",   "type": "INTEGER"},
            {"name": "First Name", "type": "TEXT"},
            {"name": "Last Name",  "type": "TEXT"},
            {"name": "License #",  "type": "TEXT"},
            {"name": "Agency",     "type": "TEXT"},
            {"name": "Yrs. Active","type": "INTEGER"}],
         "rows": [
            [1,  "Sandra", "Flores",    "TX-RE-48201", "Lone Star Realty",        12],
            [2,  "Kevin",  "Park",      "CO-RE-39504", "Rocky Mountain Homes",     8],
            [3,  "Tania",  "Okonkwo",   "WA-RE-71209", "Pacific Edge Properties", 15],
            [4,  "Marco",  "DiSilva",   "FL-RE-55604", "SunCoast Group",           6],
            [5,  "Laura",  "Jensen",    "TN-RE-62811", "Nashville Homefinders",   10],
            [6,  "Aaron",  "Whitfield", "AZ-RE-44903", "Desert Sky Realty",        9],
            [7,  "Priya",  "Nair",      "OR-RE-38017", "Green City Properties",    7],
            [8,  "James",  "Holloway",  "AZ-RE-47220", "Pinnacle Luxury Homes",   18],
            [9,  "Beth",   "Sievert",   "CO-RE-40118", "Summit Real Estate",       5],
            [10, "Victor", "Cheng",     "IL-RE-52909", "Lakefront Realty",        11]]},
        {"name": "listings", "columns": [
            {"name": "Listing ID",    "type": "INTEGER"},
            {"name": "Prop. ID",      "type": "INTEGER"},
            {"name": "Agent ID",      "type": "INTEGER"},
            {"name": "List Price ($)","type": "DECIMAL"},
            {"name": "List Date",     "type": "DATE"},
            {"name": "STATUS",        "type": "TEXT"},
            {"name": "Days on Mkt.",  "type": "INTEGER"}],
         "rows": [
            [1,  1,  1,   485000.00, "2025-01-02", "Active",         13],
            [2,  2,  2,   720000.00, "2025-01-04", "Under Contract",  9],
            [3,  3,  3,   399000.00, "2024-12-20", "Sold",           28],
            [4,  4,  4,  1250000.00, "2025-01-06", "Active",          9],
            [5,  5,  5,   410000.00, "2025-01-03", "Active",         12],
            [6,  6,  6,   680000.00, "2024-12-28", "Under Contract", 16],
            [7,  7,  7,   325000.00, "2025-01-08", "Active",          7],
            [8,  8,  8,  1895000.00, "2024-12-15", "Sold",           34],
            [9,  9,  9,   545000.00, "2025-01-05", "Active",         10],
            [10, 10, 10,  380000.00, "2025-01-01", "Under Contract", 14]]},
        {"name": "transactions", "columns": [
            {"name": "Txn ID",          "type": "INTEGER"},
            {"name": "Listing ID",      "type": "INTEGER"},
            {"name": "Sale Price ($)",  "type": "DECIMAL"},
            {"name": "Close Date",      "type": "DATE"},
            {"name": "Buyer Agent ID",  "type": "INTEGER"},
            {"name": "Commission %",    "type": "DECIMAL"}],
         "rows": [
            [1,  3,   385000.00, "2025-01-17", 2,  2.5],
            [2,  8,  1850000.00, "2025-01-18", 5,  2.5],
            [3,  6,   665000.00, "2025-01-13", 9,  2.5],
            [4,  2,   710000.00, "2025-01-13", 7,  2.5],
            [5,  10,  372000.00, "2025-01-15", 3,  2.5],
            [6,  1,   480000.00, "2025-01-15", 6,  2.5],
            [7,  4,  1230000.00, "2025-01-15", 1,  2.5],
            [8,  5,   405000.00, "2025-01-15", 4,  2.5],
            [9,  7,   320000.00, "2025-01-15", 10, 2.5],
            [10, 9,   535000.00, "2025-01-15", 2,  2.5]]}
    ]},
    "transportation": {"tables": [
        {"name": "vehicles", "columns": [
            {"name": "Vehicle ID",       "type": "INTEGER"},
            {"name": "Make/Model",       "type": "TEXT"},
            {"name": "Plate #",          "type": "TEXT"},
            {"name": "Capacity (lbs)",   "type": "INTEGER"},
            {"name": "Year",             "type": "INTEGER"},
            {"name": "Last Svc. Dt.",    "type": "DATE"}],
         "rows": [
            [1,  "Freightliner Cascadia", "PLT-4821", 45000, 2020, "2025-01-04"],
            [2,  "Kenworth T680",         "KWT-3390", 44000, 2019, "2024-12-20"],
            [3,  "Peterbilt 579",         "PTB-8841", 46000, 2022, "2025-01-08"],
            [4,  "Mack Anthem",           "MCK-7703", 43000, 2018, "2024-11-15"],
            [5,  "Volvo VNL 860",         "VLV-5512", 44500, 2021, "2025-01-10"],
            [6,  "International LT",      "INT-2294", 42000, 2020, "2024-12-30"],
            [7,  "Western Star 5700",     "WST-6630", 45500, 2023, "2025-01-03"],
            [8,  "Freightliner Cascadia", "PLT-9977", 45000, 2021, "2025-01-06"],
            [9,  "Kenworth W900",         "KWT-1120", 48000, 2017, "2024-10-22"],
            [10, "DAF XF",               "DAF-4401", 43500, 2022, "2025-01-12"]]},
        {"name": "drivers", "columns": [
            {"name": "Driver ID",    "type": "INTEGER"},
            {"name": "First Name",   "type": "TEXT"},
            {"name": "Last Name",    "type": "TEXT"},
            {"name": "CDL #",        "type": "TEXT"},
            {"name": "Hire Date",    "type": "DATE"},
            {"name": "Rating (1-5)", "type": "DECIMAL"}],
         "rows": [
            [1,  "Tom",     "Barrett",    "CDL-TX-48021", "2018-03-14", 4.8],
            [2,  "Rosa",    "Alvarez",    "CDL-CA-39002", "2020-07-01", 4.6],
            [3,  "Wayne",   "Kowalski",   "CDL-IL-55489", "2015-01-22", 4.9],
            [4,  "Linda",   "Freeman",    "CDL-FL-61003", "2022-05-10", 4.4],
            [5,  "Jamal",   "Washington", "CDL-GA-70241", "2019-09-18", 4.7],
            [6,  "Hector",  "Ruiz",       "CDL-AZ-33018", "2021-02-28", 4.5],
            [7,  "Sandra",  "Pierce",     "CDL-OH-44902", "2016-11-05", 4.9],
            [8,  "Mike",    "Thornton",   "CDL-PA-29801", "2017-08-15", 4.3],
            [9,  "Yolanda", "Cruz",       "CDL-TX-52110", "2023-01-09", 4.2],
            [10, "Greg",    "O'Neal",     "CDL-NC-38904", "2014-06-30", 4.8]]},
        {"name": "routes", "columns": [
            {"name": "Route ID",        "type": "INTEGER"},
            {"name": "Route Name",      "type": "TEXT"},
            {"name": "Origin City",     "type": "TEXT"},
            {"name": "Dest. City",      "type": "TEXT"},
            {"name": "Dist. (mi)",      "type": "INTEGER"},
            {"name": "Est. Time (hrs)", "type": "DECIMAL"}],
         "rows": [
            [1,  "I-10 Sunbelt",      "Los Angeles, CA",   "Houston, TX",      1547, 22.5],
            [2,  "I-90 Northern",     "Seattle, WA",       "Chicago, IL",      2064, 30.0],
            [3,  "I-95 Eastern",      "Miami, FL",         "New York, NY",     1281, 18.5],
            [4,  "I-80 Cross Country","San Francisco, CA", "Newark, NJ",       2899, 42.0],
            [5,  "I-35 Midwest",      "Dallas, TX",        "Minneapolis, MN",  1150, 16.5],
            [6,  "I-40 Mid-South",    "Los Angeles, CA",   "Memphis, TN",      1840, 27.0],
            [7,  "I-70 Corridor",     "Denver, CO",        "Columbus, OH",     1250, 18.0],
            [8,  "I-65 Southern",     "Birmingham, AL",    "Indianapolis, IN",  511,  7.5],
            [9,  "I-25 Mountain",     "Albuquerque, NM",   "Denver, CO",        452,  6.5],
            [10, "I-94 Northern",     "Chicago, IL",       "Detroit, MI",       281,  4.0]]},
        {"name": "shipments", "columns": [
            {"name": "Shipment ID",  "type": "INTEGER"},
            {"name": "Vehicle ID",   "type": "INTEGER"},
            {"name": "Driver ID",    "type": "INTEGER"},
            {"name": "Route ID",     "type": "INTEGER"},
            {"name": "Depart. Dt.",  "type": "DATE"},
            {"name": "Arrival Dt.",  "type": "DATE"},
            {"name": "Weight (lbs)", "type": "INTEGER"},
            {"name": "STATUS",       "type": "TEXT"}],
         "rows": [
            [1,  1,  1,  3,  "2025-01-06", "2025-01-07", 28400, "Delivered"],
            [2,  3,  7,  1,  "2025-01-07", "2025-01-08", 42100, "Delivered"],
            [3,  5,  5,  5,  "2025-01-08", "2025-01-09", 31800, "In Transit"],
            [4,  2,  3,  2,  "2025-01-09", "2025-01-10", 38900, "In Transit"],
            [5,  7,  10, 10, "2025-01-10", "2025-01-10", 15200, "Delivered"],
            [6,  4,  8,  6,  "2025-01-11", "2025-01-12", 44000, "Delayed"],
            [7,  6,  2,  7,  "2025-01-12", "2025-01-13", 29600, "In Transit"],
            [8,  8,  4,  8,  "2025-01-13", "2025-01-15", 41800, "In Transit"],
            [9,  9,  9,  4,  "2025-01-14", "2025-01-16", 48000, "Pending"],
            [10, 10, 6,  9,  "2025-01-15", "2025-01-16", 22700, "In Transit"]]}
    ]},
    "media": {"tables": [
        {"name": "hotels", "columns": [
            {"name": "Hotel ID",    "type": "INTEGER"},
            {"name": "Hotel Name",  "type": "TEXT"},
            {"name": "City",        "type": "TEXT"},
            {"name": "Star Rating", "type": "INTEGER"},
            {"name": "# of Rooms",  "type": "INTEGER"},
            {"name": "Chain/Brand", "type": "TEXT"}],
         "rows": [
            [1,  "The Grand Meridian",       "New York, NY",    5, 420, "Meridian Collection"],
            [2,  "Coastal Breeze Inn",        "Miami, FL",       4, 180, "Coastal Group"],
            [3,  "Mountain View Lodge",       "Aspen, CO",       4,  95, "Independent"],
            [4,  "City Lights Boutique",      "Chicago, IL",     3,  72, "Independent"],
            [5,  "Pacific Palms Resort",      "Honolulu, HI",    5, 550, "Pacific Hotels"],
            [6,  "Lone Star Suites",          "Austin, TX",      3, 140, "Lone Star Group"],
            [7,  "Harbor View Hotel",         "Seattle, WA",     4, 230, "Northwest Stay"],
            [8,  "Desert Dunes Resort",       "Scottsdale, AZ",  5, 360, "Luxury Desert Co."],
            [9,  "Historic Elm House",        "New Orleans, LA", 4,  68, "Independent"],
            [10, "Sunset Boulevard Inn",      "Los Angeles, CA", 3, 110, "Pacific Hotels"]]},
        {"name": "rooms", "columns": [
            {"name": "Room ID",       "type": "INTEGER"},
            {"name": "Hotel ID",      "type": "INTEGER"},
            {"name": "Room #",        "type": "TEXT"},
            {"name": "Room Type",     "type": "TEXT"},
            {"name": "Rate/Night ($)","type": "DECIMAL"},
            {"name": "Available?",    "type": "BOOLEAN"}],
         "rows": [
            [1,  1,  "1201", "Suite",          850.00, True],
            [2,  1,  "805",  "Deluxe King",    420.00, False],
            [3,  2,  "302",  "Ocean View",     310.00, True],
            [4,  3,  "101",  "Mountain Suite", 540.00, True],
            [5,  4,  "210",  "Standard Queen", 145.00, True],
            [6,  5,  "1502", "Ocean Suite",   1200.00, False],
            [7,  6,  "312",  "King Room",      175.00, True],
            [8,  7,  "408",  "Harbor View",    295.00, True],
            [9,  8,  "701",  "Pool Suite",    1050.00, True],
            [10, 9,  "105",  "Heritage Room",  220.00, True]]},
        {"name": "guests", "columns": [
            {"name": "Guest ID",    "type": "INTEGER"},
            {"name": "First Name",  "type": "TEXT"},
            {"name": "Last Name",   "type": "TEXT"},
            {"name": "E-Mail",      "type": "TEXT"},
            {"name": "Nationality", "type": "TEXT"},
            {"name": "Loyalty Tier","type": "TEXT"}],
         "rows": [
            [1,  "Emma",      "Whitfield",     "e.whitfield@email.com",   "USA",          "Gold"],
            [2,  "Hiroshi",   "Yamamoto",      "h.yamamoto@email.com",    "Japan",        "Platinum"],
            [3,  "Camille",   "Beaumont",      "c.beaumont@email.com",    "France",       "Silver"],
            [4,  "Andile",    "Dlamini",       "a.dlamini@email.com",     "South Africa", "Bronze"],
            [5,  "Charlotte", "Hayes",         "c.hayes@email.com",       "UK",           "Gold"],
            [6,  "Mohammed",  "Al-Farsi",      "m.alfarsi@email.com",     "UAE",          "Platinum"],
            [7,  "Isabel",    "Cruz",          "i.cruz@email.com",        "Brazil",       "Silver"],
            [8,  "Jonas",     "Weber",         "j.weber@email.com",       "Germany",      "Bronze"],
            [9,  "Aiko",      "Nakamura",      "a.nakamura@email.com",    "Japan",        "Gold"],
            [10, "Sophia",    "Papadopoulos",  "s.papadopoulos@email.com","Greece",       "Silver"]]},
        {"name": "reservations", "columns": [
            {"name": "Res. ID",          "type": "INTEGER"},
            {"name": "Hotel ID",         "type": "INTEGER"},
            {"name": "Room ID",          "type": "INTEGER"},
            {"name": "Guest ID",         "type": "INTEGER"},
            {"name": "Check-In Dt.",     "type": "DATE"},
            {"name": "Check-Out Dt.",    "type": "DATE"},
            {"name": "Total Charge ($)", "type": "DECIMAL"},
            {"name": "STATUS",           "type": "TEXT"}],
         "rows": [
            [1,  1, 1,  2, "2025-01-10", "2025-01-14",  3400.00, "Completed"],
            [2,  5, 6,  6, "2025-01-12", "2025-01-18",  7200.00, "Completed"],
            [3,  3, 4,  1, "2025-01-15", "2025-01-18",  1620.00, "Completed"],
            [4,  8, 9,  9, "2025-01-17", "2025-01-22",  5250.00, "Active"],
            [5,  2, 3,  5, "2025-01-18", "2025-01-21",   930.00, "Active"],
            [6,  7, 8,  3, "2025-01-19", "2025-01-23",  1180.00, "Active"],
            [7,  4, 5,  7, "2025-01-20", "2025-01-22",   290.00, "Upcoming"],
            [8,  1, 2,  4, "2025-01-22", "2025-01-25",  1260.00, "Upcoming"],
            [9,  6, 7,  8, "2025-01-25", "2025-01-28",   525.00, "Upcoming"],
            [10, 9, 10, 10,"2025-01-27", "2025-01-30",   660.00, "Upcoming"]]}
    ]},
    "agriculture": {"tables": [
        {"name": "farms", "columns": [
            {"name": "Farm ID",    "type": "INTEGER"},
            {"name": "Farm Name",  "type": "TEXT"},
            {"name": "STATE",      "type": "TEXT"},
            {"name": "Acreage",    "type": "INTEGER"},
            {"name": "Farm Type",  "type": "TEXT"},
            {"name": "Owner Name", "type": "TEXT"}],
         "rows": [
            [1,  "Green Valley Farm",    "Iowa",        1200, "Grain",     "Robert Mueller"],
            [2,  "Sunflower Acres",      "Kansas",       850, "Oilseed",   "Maria Santos"],
            [3,  "Coastal Fresh Co.",    "California",   620, "Vegetable", "Chen Wei"],
            [4,  "Heartland Dairy",      "Wisconsin",    440, "Dairy",     "Emily Larsson"],
            [5,  "Prairie Wind Wheat",   "Nebraska",    2100, "Grain",     "Tom Okafor"],
            [6,  "Rocky Ridge Ranch",    "Montana",     3800, "Livestock", "Diana Patel"],
            [7,  "BlueSky Orchards",     "Washington",   380, "Fruit",     "James Kowalski"],
            [8,  "Gulf Coast Citrus",    "Florida",      560, "Fruit",     "Rosa Hernandez"],
            [9,  "Great Plains Corn",    "Illinois",    1650, "Grain",     "Amir Hassan"],
            [10, "Delta Cotton Fields",  "Mississippi", 1100, "Fiber",     "Sandra Williams"]]},
        {"name": "crops", "columns": [
            {"name": "Crop ID",               "type": "INTEGER"},
            {"name": "Farm ID",               "type": "INTEGER"},
            {"name": "Crop Name",             "type": "TEXT"},
            {"name": "Season",                "type": "TEXT"},
            {"name": "Planting Dt.",          "type": "DATE"},
            {"name": "Exp. Yield (tons)",     "type": "DECIMAL"}],
         "rows": [
            [1,  1,  "Soybeans",     "Summer", "2025-04-15", 3480.0],
            [2,  1,  "Corn",         "Summer", "2025-04-20", 5520.0],
            [3,  2,  "Sunflowers",   "Summer", "2025-05-01", 1360.0],
            [4,  3,  "Tomatoes",     "Spring", "2025-03-10",  980.0],
            [5,  3,  "Lettuce",      "Spring", "2025-02-20",  420.0],
            [6,  5,  "Winter Wheat", "Winter", "2024-10-15", 8400.0],
            [7,  7,  "Apples",       "Fall",   "2025-04-01",  560.0],
            [8,  8,  "Oranges",      "Winter", "2024-11-15",  840.0],
            [9,  9,  "Corn",         "Summer", "2025-04-18", 6600.0],
            [10, 10, "Cotton",       "Summer", "2025-04-25", 2640.0]]},
        {"name": "harvests", "columns": [
            {"name": "Harvest ID",        "type": "INTEGER"},
            {"name": "Crop ID",           "type": "INTEGER"},
            {"name": "Harvest Dt.",       "type": "DATE"},
            {"name": "Actual Yield (tons)","type": "DECIMAL"},
            {"name": "Grade/Quality",     "type": "TEXT"},
            {"name": "Revenue ($)",       "type": "DECIMAL"}],
         "rows": [
            [1,  1,  "2025-09-20",  3210.0, "Grade A",  1605000.0],
            [2,  2,  "2025-09-25",  5180.0, "Grade A",  1295000.0],
            [3,  3,  "2025-09-15",  1290.0, "Grade B",  1032000.0],
            [4,  4,  "2025-07-10",   910.0, "Grade A",  1365000.0],
            [5,  5,  "2025-05-15",   390.0, "Grade A",   780000.0],
            [6,  6,  "2025-07-30",  7840.0, "Grade A",  2352000.0],
            [7,  7,  "2025-10-05",   520.0, "Premium",  1040000.0],
            [8,  8,  "2025-03-20",   810.0, "Grade A",   648000.0],
            [9,  9,  "2025-09-22",  6240.0, "Grade A",  1560000.0],
            [10, 10, "2025-10-15",  2400.0, "Grade B",  1680000.0]]},
        {"name": "distributors", "columns": [
            {"name": "Distributor ID",  "type": "INTEGER"},
            {"name": "Company Name",    "type": "TEXT"},
            {"name": "REGION",          "type": "TEXT"},
            {"name": "Crop ID",         "type": "INTEGER"},
            {"name": "Units Sold",      "type": "INTEGER"},
            {"name": "Contract Dt.",    "type": "DATE"}],
         "rows": [
            [1,  "Midwest Grain Traders",    "Midwest",   1,  148000, "2025-03-01"],
            [2,  "National Corn Exchange",   "National",  2,  212000, "2025-01-15"],
            [3,  "SunGold Oilseeds LLC",     "Central",   3,   58000, "2025-02-20"],
            [4,  "Pacific Fresh Markets",    "West",      4,   42000, "2025-03-15"],
            [5,  "Organic Greens Co.",       "National",  5,   18000, "2025-01-10"],
            [6,  "Great Plains Wheat Co.",   "National",  6,  380000, "2025-01-05"],
            [7,  "Northwest Fruit Dist.",    "West",      7,   22000, "2025-04-01"],
            [8,  "Sunshine Citrus Group",    "Southeast", 8,   34000, "2025-03-10"],
            [9,  "Illinois Corn Exports",    "National",  9,  280000, "2025-02-01"],
            [10, "Southern Cotton Mills",    "Southeast", 10,  96000, "2025-04-15"]]}
    ]},
}

# ── Mock data — CLEAN column names (same rows, already-normalized names) ──────
_MOCK_DATA_CLEAN: dict[str, dict] = {
    "healthcare": {"tables": [
        {"name": "doctors", "columns": [
            {"name": "doctor_id",        "type": "INTEGER"},
            {"name": "first_name",       "type": "TEXT"},
            {"name": "last_name",        "type": "TEXT"},
            {"name": "specialty",        "type": "TEXT"},
            {"name": "years_experience", "type": "INTEGER"},
            {"name": "email",            "type": "TEXT"}],
         "rows": _MOCK_DATA_MESSY["healthcare"]["tables"][0]["rows"]},
        {"name": "patients", "columns": [
            {"name": "patient_id",        "type": "INTEGER"},
            {"name": "first_name",        "type": "TEXT"},
            {"name": "last_name",         "type": "TEXT"},
            {"name": "date_of_birth",     "type": "DATE"},
            {"name": "gender",            "type": "TEXT"},
            {"name": "blood_type",        "type": "TEXT"},
            {"name": "primary_doctor_id", "type": "INTEGER"}],
         "rows": _MOCK_DATA_MESSY["healthcare"]["tables"][1]["rows"]},
        {"name": "appointments", "columns": [
            {"name": "appointment_id",   "type": "INTEGER"},
            {"name": "patient_id",       "type": "INTEGER"},
            {"name": "doctor_id",        "type": "INTEGER"},
            {"name": "appointment_date", "type": "DATE"},
            {"name": "status",           "type": "TEXT"},
            {"name": "chief_complaint",  "type": "TEXT"}],
         "rows": _MOCK_DATA_MESSY["healthcare"]["tables"][2]["rows"]},
        {"name": "prescriptions", "columns": [
            {"name": "prescription_id",   "type": "INTEGER"},
            {"name": "patient_id",        "type": "INTEGER"},
            {"name": "doctor_id",         "type": "INTEGER"},
            {"name": "medication",        "type": "TEXT"},
            {"name": "dosage",            "type": "TEXT"},
            {"name": "date_prescribed",   "type": "DATE"},
            {"name": "refills_remaining", "type": "INTEGER"}],
         "rows": _MOCK_DATA_MESSY["healthcare"]["tables"][3]["rows"]},
    ]},
    "financial": {"tables": [
        {"name": "customers", "columns": [
            {"name": "customer_id",  "type": "INTEGER"},
            {"name": "first_name",   "type": "TEXT"},
            {"name": "last_name",    "type": "TEXT"},
            {"name": "email",        "type": "TEXT"},
            {"name": "credit_score", "type": "INTEGER"},
            {"name": "member_since", "type": "DATE"}],
         "rows": _MOCK_DATA_MESSY["financial"]["tables"][0]["rows"]},
        {"name": "products", "columns": [
            {"name": "product_id",    "type": "INTEGER"},
            {"name": "product_name",  "type": "TEXT"},
            {"name": "category",      "type": "TEXT"},
            {"name": "interest_rate", "type": "DECIMAL"},
            {"name": "min_balance",   "type": "DECIMAL"}],
         "rows": _MOCK_DATA_MESSY["financial"]["tables"][1]["rows"]},
        {"name": "accounts", "columns": [
            {"name": "account_id",  "type": "INTEGER"},
            {"name": "customer_id", "type": "INTEGER"},
            {"name": "product_id",  "type": "INTEGER"},
            {"name": "balance",     "type": "DECIMAL"},
            {"name": "currency",    "type": "TEXT"},
            {"name": "date_opened", "type": "DATE"}],
         "rows": _MOCK_DATA_MESSY["financial"]["tables"][2]["rows"]},
        {"name": "transactions", "columns": [
            {"name": "transaction_id",   "type": "INTEGER"},
            {"name": "account_id",       "type": "INTEGER"},
            {"name": "transaction_date", "type": "DATE"},
            {"name": "amount",           "type": "DECIMAL"},
            {"name": "type",             "type": "TEXT"},
            {"name": "description",      "type": "TEXT"},
            {"name": "merchant",         "type": "TEXT"}],
         "rows": _MOCK_DATA_MESSY["financial"]["tables"][3]["rows"]},
    ]},
    "technology": {"tables": [
        {"name": "employees", "columns": [
            {"name": "employee_id",      "type": "INTEGER"},
            {"name": "first_name",       "type": "TEXT"},
            {"name": "last_name",        "type": "TEXT"},
            {"name": "job_title",        "type": "TEXT"},
            {"name": "department",       "type": "TEXT"},
            {"name": "years_experience", "type": "INTEGER"},
            {"name": "email",            "type": "TEXT"}],
         "rows": _MOCK_DATA_MESSY["technology"]["tables"][0]["rows"]},
        {"name": "projects", "columns": [
            {"name": "project_id",       "type": "INTEGER"},
            {"name": "project_name",     "type": "TEXT"},
            {"name": "lead_employee_id", "type": "INTEGER"},
            {"name": "start_date",       "type": "DATE"},
            {"name": "due_date",         "type": "DATE"},
            {"name": "status",           "type": "TEXT"},
            {"name": "budget",           "type": "DECIMAL"}],
         "rows": _MOCK_DATA_MESSY["technology"]["tables"][1]["rows"]},
        {"name": "bugs", "columns": [
            {"name": "bug_id",        "type": "INTEGER"},
            {"name": "project_id",    "type": "INTEGER"},
            {"name": "reporter_id",   "type": "INTEGER"},
            {"name": "title",         "type": "TEXT"},
            {"name": "severity",      "type": "TEXT"},
            {"name": "reported_date", "type": "DATE"},
            {"name": "status",        "type": "TEXT"}],
         "rows": _MOCK_DATA_MESSY["technology"]["tables"][2]["rows"]},
        {"name": "deployments", "columns": [
            {"name": "deployment_id", "type": "INTEGER"},
            {"name": "project_id",    "type": "INTEGER"},
            {"name": "deploy_date",   "type": "DATE"},
            {"name": "environment",   "type": "TEXT"},
            {"name": "version",       "type": "TEXT"},
            {"name": "deployed_by",   "type": "INTEGER"},
            {"name": "success",       "type": "BOOLEAN"}],
         "rows": _MOCK_DATA_MESSY["technology"]["tables"][3]["rows"]},
    ]},
    "retail": {"tables": [
        {"name": "products", "columns": [
            {"name": "product_id",      "type": "INTEGER"},
            {"name": "product_name",    "type": "TEXT"},
            {"name": "category",        "type": "TEXT"},
            {"name": "unit_price",      "type": "DECIMAL"},
            {"name": "stock_quantity",  "type": "INTEGER"},
            {"name": "sku",             "type": "TEXT"}],
         "rows": _MOCK_DATA_MESSY["retail"]["tables"][0]["rows"]},
        {"name": "customers", "columns": [
            {"name": "customer_id",  "type": "INTEGER"},
            {"name": "first_name",   "type": "TEXT"},
            {"name": "last_name",    "type": "TEXT"},
            {"name": "email",        "type": "TEXT"},
            {"name": "member_tier",  "type": "TEXT"},
            {"name": "join_date",    "type": "DATE"}],
         "rows": _MOCK_DATA_MESSY["retail"]["tables"][1]["rows"]},
        {"name": "orders", "columns": [
            {"name": "order_id",         "type": "INTEGER"},
            {"name": "customer_id",      "type": "INTEGER"},
            {"name": "order_date",       "type": "DATE"},
            {"name": "total",            "type": "DECIMAL"},
            {"name": "status",           "type": "TEXT"},
            {"name": "shipping_method",  "type": "TEXT"}],
         "rows": _MOCK_DATA_MESSY["retail"]["tables"][2]["rows"]},
        {"name": "order_items", "columns": [
            {"name": "item_id",       "type": "INTEGER"},
            {"name": "order_id",      "type": "INTEGER"},
            {"name": "product_id",    "type": "INTEGER"},
            {"name": "quantity",      "type": "INTEGER"},
            {"name": "unit_price",    "type": "DECIMAL"},
            {"name": "discount_pct",  "type": "DECIMAL"}],
         "rows": _MOCK_DATA_MESSY["retail"]["tables"][3]["rows"]},
    ]},
    "manufacturing": {"tables": [
        {"name": "facilities", "columns": [
            {"name": "facility_id",    "type": "INTEGER"},
            {"name": "facility_name",  "type": "TEXT"},
            {"name": "location",       "type": "TEXT"},
            {"name": "daily_capacity", "type": "INTEGER"},
            {"name": "year_built",     "type": "INTEGER"},
            {"name": "is_active",      "type": "BOOLEAN"}],
         "rows": _MOCK_DATA_MESSY["manufacturing"]["tables"][0]["rows"]},
        {"name": "equipment", "columns": [
            {"name": "equipment_id",           "type": "INTEGER"},
            {"name": "facility_id",            "type": "INTEGER"},
            {"name": "equipment_name",         "type": "TEXT"},
            {"name": "manufacturer",           "type": "TEXT"},
            {"name": "manufacture_year",       "type": "INTEGER"},
            {"name": "last_maintenance_date",  "type": "DATE"}],
         "rows": _MOCK_DATA_MESSY["manufacturing"]["tables"][1]["rows"]},
        {"name": "production_runs", "columns": [
            {"name": "run_id",         "type": "INTEGER"},
            {"name": "facility_id",    "type": "INTEGER"},
            {"name": "product_line",   "type": "TEXT"},
            {"name": "start_date",     "type": "DATE"},
            {"name": "end_date",       "type": "DATE"},
            {"name": "units_produced", "type": "INTEGER"},
            {"name": "shift",          "type": "TEXT"}],
         "rows": _MOCK_DATA_MESSY["manufacturing"]["tables"][2]["rows"]},
        {"name": "quality_checks", "columns": [
            {"name": "check_id",       "type": "INTEGER"},
            {"name": "run_id",         "type": "INTEGER"},
            {"name": "equipment_id",   "type": "INTEGER"},
            {"name": "defect_rate_pct","type": "DECIMAL"},
            {"name": "check_date",     "type": "DATE"},
            {"name": "result",         "type": "TEXT"},
            {"name": "inspector_id",   "type": "INTEGER"}],
         "rows": _MOCK_DATA_MESSY["manufacturing"]["tables"][3]["rows"]},
    ]},
    "energy": {"tables": [
        {"name": "plants", "columns": [
            {"name": "plant_id",    "type": "INTEGER"},
            {"name": "plant_name",  "type": "TEXT"},
            {"name": "energy_type", "type": "TEXT"},
            {"name": "capacity_mw", "type": "DECIMAL"},
            {"name": "online_date", "type": "DATE"},
            {"name": "state",       "type": "TEXT"}],
         "rows": _MOCK_DATA_MESSY["energy"]["tables"][0]["rows"]},
        {"name": "meters", "columns": [
            {"name": "meter_id",          "type": "INTEGER"},
            {"name": "plant_id",          "type": "INTEGER"},
            {"name": "meter_type",        "type": "TEXT"},
            {"name": "install_date",      "type": "DATE"},
            {"name": "last_reading_kwh",  "type": "DECIMAL"},
            {"name": "status",            "type": "TEXT"}],
         "rows": _MOCK_DATA_MESSY["energy"]["tables"][1]["rows"]},
        {"name": "consumption_records", "columns": [
            {"name": "record_id",       "type": "INTEGER"},
            {"name": "meter_id",        "type": "INTEGER"},
            {"name": "record_date",     "type": "DATE"},
            {"name": "kwh_consumed",    "type": "DECIMAL"},
            {"name": "peak_demand_kw",  "type": "DECIMAL"},
            {"name": "cost_per_kwh",    "type": "DECIMAL"}],
         "rows": _MOCK_DATA_MESSY["energy"]["tables"][2]["rows"]},
        {"name": "maintenance_logs", "columns": [
            {"name": "log_id",            "type": "INTEGER"},
            {"name": "plant_id",          "type": "INTEGER"},
            {"name": "maintenance_type",  "type": "TEXT"},
            {"name": "scheduled_date",    "type": "DATE"},
            {"name": "completed_date",    "type": "DATE"},
            {"name": "cost",              "type": "DECIMAL"},
            {"name": "technician_id",     "type": "INTEGER"}],
         "rows": _MOCK_DATA_MESSY["energy"]["tables"][3]["rows"]},
    ]},
    "construction": {"tables": [
        {"name": "properties", "columns": [
            {"name": "property_id", "type": "INTEGER"},
            {"name": "address",     "type": "TEXT"},
            {"name": "city",        "type": "TEXT"},
            {"name": "bedrooms",    "type": "INTEGER"},
            {"name": "bathrooms",   "type": "DECIMAL"},
            {"name": "sq_ft",       "type": "INTEGER"},
            {"name": "year_built",  "type": "INTEGER"}],
         "rows": _MOCK_DATA_MESSY["construction"]["tables"][0]["rows"]},
        {"name": "agents", "columns": [
            {"name": "agent_id",       "type": "INTEGER"},
            {"name": "first_name",     "type": "TEXT"},
            {"name": "last_name",      "type": "TEXT"},
            {"name": "license_number", "type": "TEXT"},
            {"name": "agency",         "type": "TEXT"},
            {"name": "years_active",   "type": "INTEGER"}],
         "rows": _MOCK_DATA_MESSY["construction"]["tables"][1]["rows"]},
        {"name": "listings", "columns": [
            {"name": "listing_id",     "type": "INTEGER"},
            {"name": "property_id",    "type": "INTEGER"},
            {"name": "agent_id",       "type": "INTEGER"},
            {"name": "list_price",     "type": "DECIMAL"},
            {"name": "list_date",      "type": "DATE"},
            {"name": "status",         "type": "TEXT"},
            {"name": "days_on_market", "type": "INTEGER"}],
         "rows": _MOCK_DATA_MESSY["construction"]["tables"][2]["rows"]},
        {"name": "transactions", "columns": [
            {"name": "transaction_id",   "type": "INTEGER"},
            {"name": "listing_id",       "type": "INTEGER"},
            {"name": "sale_price",       "type": "DECIMAL"},
            {"name": "close_date",       "type": "DATE"},
            {"name": "buyer_agent_id",   "type": "INTEGER"},
            {"name": "commission_pct",   "type": "DECIMAL"}],
         "rows": _MOCK_DATA_MESSY["construction"]["tables"][3]["rows"]},
    ]},
    "transportation": {"tables": [
        {"name": "vehicles", "columns": [
            {"name": "vehicle_id",        "type": "INTEGER"},
            {"name": "make_model",        "type": "TEXT"},
            {"name": "license_plate",     "type": "TEXT"},
            {"name": "capacity_lbs",      "type": "INTEGER"},
            {"name": "year",              "type": "INTEGER"},
            {"name": "last_service_date", "type": "DATE"}],
         "rows": _MOCK_DATA_MESSY["transportation"]["tables"][0]["rows"]},
        {"name": "drivers", "columns": [
            {"name": "driver_id",   "type": "INTEGER"},
            {"name": "first_name",  "type": "TEXT"},
            {"name": "last_name",   "type": "TEXT"},
            {"name": "cdl_number",  "type": "TEXT"},
            {"name": "hire_date",   "type": "DATE"},
            {"name": "rating",      "type": "DECIMAL"}],
         "rows": _MOCK_DATA_MESSY["transportation"]["tables"][1]["rows"]},
        {"name": "routes", "columns": [
            {"name": "route_id",          "type": "INTEGER"},
            {"name": "route_name",        "type": "TEXT"},
            {"name": "origin_city",       "type": "TEXT"},
            {"name": "destination_city",  "type": "TEXT"},
            {"name": "distance_miles",    "type": "INTEGER"},
            {"name": "estimated_hours",   "type": "DECIMAL"}],
         "rows": _MOCK_DATA_MESSY["transportation"]["tables"][2]["rows"]},
        {"name": "shipments", "columns": [
            {"name": "shipment_id",  "type": "INTEGER"},
            {"name": "vehicle_id",   "type": "INTEGER"},
            {"name": "driver_id",    "type": "INTEGER"},
            {"name": "route_id",     "type": "INTEGER"},
            {"name": "depart_date",  "type": "DATE"},
            {"name": "arrival_date", "type": "DATE"},
            {"name": "weight_lbs",   "type": "INTEGER"},
            {"name": "status",       "type": "TEXT"}],
         "rows": _MOCK_DATA_MESSY["transportation"]["tables"][3]["rows"]},
    ]},
    "media": {"tables": [
        {"name": "hotels", "columns": [
            {"name": "hotel_id",     "type": "INTEGER"},
            {"name": "hotel_name",   "type": "TEXT"},
            {"name": "city",         "type": "TEXT"},
            {"name": "star_rating",  "type": "INTEGER"},
            {"name": "total_rooms",  "type": "INTEGER"},
            {"name": "brand",        "type": "TEXT"}],
         "rows": _MOCK_DATA_MESSY["media"]["tables"][0]["rows"]},
        {"name": "rooms", "columns": [
            {"name": "room_id",        "type": "INTEGER"},
            {"name": "hotel_id",       "type": "INTEGER"},
            {"name": "room_number",    "type": "TEXT"},
            {"name": "room_type",      "type": "TEXT"},
            {"name": "rate_per_night", "type": "DECIMAL"},
            {"name": "is_available",   "type": "BOOLEAN"}],
         "rows": _MOCK_DATA_MESSY["media"]["tables"][1]["rows"]},
        {"name": "guests", "columns": [
            {"name": "guest_id",     "type": "INTEGER"},
            {"name": "first_name",   "type": "TEXT"},
            {"name": "last_name",    "type": "TEXT"},
            {"name": "email",        "type": "TEXT"},
            {"name": "nationality",  "type": "TEXT"},
            {"name": "loyalty_tier", "type": "TEXT"}],
         "rows": _MOCK_DATA_MESSY["media"]["tables"][2]["rows"]},
        {"name": "reservations", "columns": [
            {"name": "reservation_id", "type": "INTEGER"},
            {"name": "hotel_id",       "type": "INTEGER"},
            {"name": "room_id",        "type": "INTEGER"},
            {"name": "guest_id",       "type": "INTEGER"},
            {"name": "check_in_date",  "type": "DATE"},
            {"name": "check_out_date", "type": "DATE"},
            {"name": "total_charge",   "type": "DECIMAL"},
            {"name": "status",         "type": "TEXT"}],
         "rows": _MOCK_DATA_MESSY["media"]["tables"][3]["rows"]},
    ]},
    "agriculture": {"tables": [
        {"name": "farms", "columns": [
            {"name": "farm_id",    "type": "INTEGER"},
            {"name": "farm_name",  "type": "TEXT"},
            {"name": "state",      "type": "TEXT"},
            {"name": "acreage",    "type": "INTEGER"},
            {"name": "farm_type",  "type": "TEXT"},
            {"name": "owner_name", "type": "TEXT"}],
         "rows": _MOCK_DATA_MESSY["agriculture"]["tables"][0]["rows"]},
        {"name": "crops", "columns": [
            {"name": "crop_id",              "type": "INTEGER"},
            {"name": "farm_id",              "type": "INTEGER"},
            {"name": "crop_name",            "type": "TEXT"},
            {"name": "season",               "type": "TEXT"},
            {"name": "planting_date",        "type": "DATE"},
            {"name": "expected_yield_tons",  "type": "DECIMAL"}],
         "rows": _MOCK_DATA_MESSY["agriculture"]["tables"][1]["rows"]},
        {"name": "harvests", "columns": [
            {"name": "harvest_id",        "type": "INTEGER"},
            {"name": "crop_id",           "type": "INTEGER"},
            {"name": "harvest_date",      "type": "DATE"},
            {"name": "actual_yield_tons", "type": "DECIMAL"},
            {"name": "grade",             "type": "TEXT"},
            {"name": "revenue",           "type": "DECIMAL"}],
         "rows": _MOCK_DATA_MESSY["agriculture"]["tables"][2]["rows"]},
        {"name": "distributors", "columns": [
            {"name": "distributor_id", "type": "INTEGER"},
            {"name": "company_name",   "type": "TEXT"},
            {"name": "region",         "type": "TEXT"},
            {"name": "crop_id",        "type": "INTEGER"},
            {"name": "units_sold",     "type": "INTEGER"},
            {"name": "contract_date",  "type": "DATE"}],
         "rows": _MOCK_DATA_MESSY["agriculture"]["tables"][3]["rows"]},
    ]},
}

# ── Mock summaries ────────────────────────────────────────────────────────────
_MOCK_SUMMARIES: dict[str, str] = {
    "financial": (
        "This financial services database connects 10 customers and 10 insurance/banking products "
        "across 10 accounts and 10 January 2025 transactions, capturing a mixed-risk portfolio "
        "with credit scores ranging from 590 to 820. The top three customers collectively hold "
        "over $260,000 in savings and money market balances, making them high-value retention "
        "targets. Debit transactions dominate the log, with rent and wire transfers as the largest "
        "single outflows. Product diversity across checking, savings, credit cards, and loans "
        "indicates strong cross-sell analytics opportunities for the insurance and banking lines."
    ),
    "energy": (
        "This energy & oil and gas portfolio covers 10 generation plants across 9 states with "
        "3,965 MW of combined nameplate capacity spanning solar, wind, hydro, gas, nuclear, coal, "
        "biomass, and geothermal sources. Nuclear and coal plants drive the bulk of generation "
        "volume but carry the highest maintenance costs -- $85,000 and $15,000 respectively for "
        "January 2025. Five of the ten active meters show cost-per-kWh below $0.05, indicating "
        "strong efficiency for renewable assets. The two oldest facilities (nuclear: 1988, coal: "
        "1995) should be flagged as priority items in the capital replacement roadmap."
    ),
    "healthcare": (
        "This healthcare & pharmaceuticals database spans 4 relational tables -- doctors, patients, "
        "appointments, and prescriptions -- covering 10 physicians across 8 specialties and 10 "
        "patient records. Appointments in January 2025 show a 70% completion rate with two still "
        "scheduled and one cancelled, pointing to manageable cancellation risk. Cardiology carries "
        "the highest patient-to-doctor ratio, suggesting additional capacity planning is warranted. "
        "With 10 active prescriptions across 8 unique medications, the pharmacology data is rich "
        "enough to support drug utilization and refill-adherence analytics."
    ),
    "technology": (
        "This technology/IT database connects 10 employees across 5 teams, 10 projects, 10 reported "
        "bugs, and 10 deployment events. The project portfolio carries $1.525M in total budget, "
        "led by the AIDA Platform v2 at $420K. Two critical bugs remain open -- one in the ETL "
        "pipeline and one causing session token failures -- representing pipeline risk for the two "
        "highest-budget active projects. With a 90% deployment success rate and one failed "
        "production push, the team's release cadence is strong but warrants a post-mortem on "
        "the security hardening rollback."
    ),
    "construction": (
        "This construction & real estate database connects 10 residential properties across 8 cities, "
        "10 licensed agents, 10 listings, and 10 closed transactions from January 2025. Sold "
        "listings cleared at an average of 98.6% of list price, indicating a strong seller's market. "
        "The Scottsdale luxury listing at $1.895M was the highest-value transaction, closing $45,000 "
        "under ask. Days on market average 16 days across active listings, with the oldest at 34 "
        "days -- a prime candidate for a price-adjustment strategy. Agent coverage is one-to-one "
        "per listing, suggesting a boutique brokerage or contractor referral model."
    ),
    "agriculture": (
        "This agriculture & food production database covers 10 farms across 9 US states, 10 crop "
        "varieties, 10 harvest records, and 10 distributor contracts for the 2024-2025 growing "
        "season. Total expected yield across all crops exceeds 30,000 tons, with grain crops "
        "(corn, wheat, soybeans) dominating at 75% of volume. Harvest revenue across completed "
        "records tops $13.9M, led by the Prairie Wind Wheat harvest at $2.35M. Three farms "
        "operate above 1,500 acres -- Great Plains Corn, Rocky Ridge Ranch, and Prairie Wind "
        "Wheat -- making them prime candidates for precision agriculture investment to maximize "
        "yield-per-acre efficiency."
    ),
    "manufacturing": (
        "This manufacturing database spans 10 facilities across 9 US states, 10 equipment records, "
        "10 production runs, and 10 quality inspections from January 2025. Total output reached "
        "over 142,000 units across active facilities, led by the Gulf Coast Plant's plastic "
        "extrusion line at 45,000 units. Two quality checks failed with defect rates above 2% -- "
        "concentrated in consumer electronics housing and heavy machinery frames -- warranting "
        "immediate root-cause analysis. Eastbrook Hub remains offline, reducing available network "
        "capacity by 1,500 units per day."
    ),
    "retail": (
        "This retail & e-commerce database captures 10 products across 5 categories, 10 customers "
        "segmented by loyalty tier, 10 orders, and 10 line items from January 2025. Platinum-tier "
        "customers account for 3 of the top 4 orders by value, making this segment critical for "
        "retention. Electronics commands the highest average unit price at $69.99, while Kitchen "
        "holds the broadest inventory depth across 3 SKUs. Two orders remain in Processing status, "
        "signaling a fulfillment optimization opportunity for standard shipping customers."
    ),
    "transportation": (
        "This transportation & logistics database tracks 10 heavy freight vehicles, 10 CDL drivers, "
        "10 interstate routes, and 10 January 2025 shipments. Combined payload across active "
        "shipments exceeds 370,000 lbs, with 3 delivered, 5 in transit, 1 delayed, and 1 pending. "
        "The I-80 cross-country route (SF to Newark, 2,899 miles) carries the longest ETA at 42 "
        "hours and the heaviest vehicle utilization. Driver ratings average 4.61 out of 5.0, with "
        "two drivers above 4.8 -- strong candidates for a performance-based retention incentive. "
        "The delayed I-40 shipment should trigger an immediate ETA escalation."
    ),
    "media": (
        "This media, entertainment & tourism database covers 10 hotel and resort properties across "
        "9 US cities, 10 room types priced between $145 and $1,200 per night, 10 international "
        "guests, and 10 reservations spanning January 2025. Platinum loyalty guests generate the "
        "top two reservations by revenue ($7,200 and $3,400), confirming the outsized revenue "
        "contribution of the top loyalty tier. The Pacific Palms Resort and Grand Meridian anchor "
        "the portfolio's luxury segment, while 3-star properties serve as volume drivers. Two "
        "premium rooms are currently unavailable, representing up to $2,050 in lost nightly "
        "revenue -- a direct content and guest-experience recovery opportunity."
    ),
}

# ── PostgreSQL write ──────────────────────────────────────────────────────────
_PG_TYPE_MAP = {"TEXT": "TEXT", "INTEGER": "INTEGER", "DECIMAL": "NUMERIC",
                "DATE": "DATE", "BOOLEAN": "BOOLEAN"}


def _pg_id(name: str) -> str:
    """Double-quote a PostgreSQL identifier (for DDL — no psycopg2 substitution)."""
    return '"' + name.replace('"', '""') + '"'


def _pg_id_dml(name: str) -> str:
    """Double-quote a PostgreSQL identifier for DML (executemany).
    psycopg2 applies %-substitution on the query string even for column names,
    so a literal % in a column name must be escaped as %% to survive."""
    return '"' + name.replace('"', '""').replace('%', '%%') + '"'


def write_postgres(data: dict) -> None:
    conn = psycopg2.connect(**_PG)
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(f"DROP SCHEMA IF EXISTS {_PG_SCHEMA} CASCADE")
            cur.execute(f"CREATE SCHEMA {_PG_SCHEMA}")
            for tbl in data["tables"]:
                name = tbl["name"]
                col_defs = ", ".join(
                    f'{_pg_id(c["name"])} {_PG_TYPE_MAP.get(c["type"].upper(), "TEXT")}'
                    for c in tbl["columns"]
                )
                cur.execute(f'CREATE TABLE {_PG_SCHEMA}."{name}" ({col_defs})')
                if tbl["rows"]:
                    col_names = ", ".join(_pg_id_dml(c["name"]) for c in tbl["columns"])
                    ph = ", ".join(["%s"] * len(tbl["columns"]))
                    cur.executemany(
                        f'INSERT INTO {_PG_SCHEMA}."{name}" ({col_names}) VALUES ({ph})',
                        [tuple(r) for r in tbl["rows"]],
                    )
    finally:
        conn.close()

# ── DuckDB snapshot ───────────────────────────────────────────────────────────
def _safe_val(v: object) -> object:
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if hasattr(v, "item"):
        return v.item()
    if hasattr(v, "isoformat"):
        s = v.isoformat()
        # Strip T00:00:00 suffix that DuckDB adds when it upcasts DATE → TIMESTAMP
        if "T" in s and s.endswith("00:00:00"):
            return s.split("T")[0]
        return s
    return v


def _df_rows(df: pd.DataFrame) -> list[list]:
    return [[_safe_val(v) for v in row] for row in df.itertuples(index=False)]


def snapshot_to_duckdb(industry: str) -> tuple[dict, str, dict, dict]:
    project = f"demo_{industry}"
    # Remove the stale DuckDB file so each generation starts with a clean slate
    _db_dir  = pathlib.Path(__file__).parent / "files" / "duckdb"
    _db_file = _db_dir / f"{project}.duckdb"
    if _db_file.exists():
        _db_file.unlink()
    with DataLayer(project) as dl:
        dl.ingest_postgres(dsn=_DSN, pg_schema=_PG_SCHEMA)
        schema        = dl.schema_json()
        schema_t      = dl.schema_text()
        previews      = {
            t: {"columns": list(df.columns), "rows": _df_rows(df)}
            for t in dl.list_tables()
            for df in [dl.materialize_df(t, max_rows=100)]
        }
        column_renames = dl.column_renames.copy()
    return schema, schema_t, previews, column_renames


def _sanitize_for_duckdb(df: pd.DataFrame) -> pd.DataFrame:
    """
    Coerce object columns to plain Python str / None before handing the frame
    to DuckDB. DuckDB's pandas scanner raises "unsupported string type" when an
    object column contains pandas NAType, numpy.str_, or a mix of types — this
    normalizes every text cell to a real str (or None for missing).
    """
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == object:
            notna = df[col].notna()
            df[col] = df[col].where(notna, None).map(
                lambda v: None if v is None else str(v)
            )
    return df


def snapshot_dfs_to_duckdb(
    industry: str, tables: dict[str, pd.DataFrame]
) -> tuple[dict, str, dict, dict]:
    """Write DataFrames directly into DuckDB — no PostgreSQL round-trip."""
    project  = f"demo_{industry}"
    _db_dir  = pathlib.Path(__file__).parent / "files" / "duckdb"
    _db_file = _db_dir / f"{project}.duckdb"
    if _db_file.exists():
        _db_file.unlink()
    with DataLayer(project) as dl:
        for name, df in tables.items():
            df  = _sanitize_for_duckdb(df)
            reg = f"_sdv_reg_{name}"
            dl.con.register(reg, df)
            dl.con.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM "{reg}"')
            dl.con.unregister(reg)
            dl._rename_columns(name)
        schema        = dl.schema_json()
        schema_t      = dl.schema_text()
        previews      = {
            t: {"columns": list(dft.columns), "rows": _df_rows(dft)}
            for t in dl.list_tables()
            for dft in [dl.materialize_df(t, max_rows=100)]
        }
        column_renames = dl.column_renames.copy()
    return schema, schema_t, previews, column_renames

# ── LLM summary ───────────────────────────────────────────────────────────────
_SUM_SYSTEM = (
    "You are a senior data analyst. Given a database schema, write a concise 3-5 sentence "
    "executive summary: what the database represents, how the tables relate, key metrics from "
    "structure and row counts, and one actionable insight. Be specific — no generic filler."
)

_MOCK_INSIGHTS = [
    "high-value customers who reorder frequently are the best candidates for loyalty reward escalation.",
    "order type distribution (dine-in vs. takeout vs. delivery) reveals staffing and supply-chain priorities.",
    "cross-referencing inventory reorder levels with daily sales velocity can prevent peak-hour stockouts.",
    "comparing revenue per location surfaces underperforming stores that could benefit from targeted promotions.",
    "payment method mix (cash vs. card vs. mobile) signals digital readiness for app-based order campaigns.",
    "customer acquisition-date cohorts show which sign-up months produce the highest long-term retention.",
    "discount frequency by product category indicates where margin pressure is highest.",
    "average items per order is a key upsell metric - raising it by even 0.3 can meaningfully lift revenue.",
    "loyalty point redemption rate is an early indicator of customer satisfaction and upcoming churn risk.",
    "store opening dates correlated with local order density can validate expansion strategy assumptions.",
    "time-to-reorder for inventory items, plotted against sales trends, predicts supply chain risk windows.",
]


def _build_mock_summary(schema_txt: str, industry: str,
                        company_name: str, company_context: str) -> str:
    """Generate a company-specific, call-varied summary without an LLM."""
    industry_label = INDUSTRIES.get(industry, industry.replace("_", " ").title())
    co = company_name if company_name else f"a {industry_label} business"

    tbl_lines = [ln for ln in schema_txt.splitlines() if ln.startswith("TABLE ")]
    n = len(tbl_lines)
    names = [ln.split()[1] for ln in tbl_lines]
    if n == 0:
        names_str = "multiple tables"
    elif n == 1:
        names_str = names[0]
    elif n <= 4:
        names_str = ", ".join(names[:-1]) + f" and {names[-1]}"
    else:
        names_str = ", ".join(names[:3]) + f" and {n - 3} more"

    ctx_sent = (f" ({company_context.strip().rstrip('.').lower()[:100]})"
                if company_context else "")

    insight = _MOCK_INSIGHTS[_gen_call_count % len(_MOCK_INSIGHTS)]

    return (
        f"This database contains synthetic {industry_label} data for {co}{ctx_sent}, "
        f"organized across {n} table{'s' if n != 1 else ''}: {names_str}. "
        f"Records simulate realistic {co} operations covering transaction management, "
        f"customer relationships, and operational tracking. "
        f"All column names are normalized to snake_case for consistent SQL access, "
        f"and foreign-key relationships between tables are auto-detected. "
        f"Actionable insight: {insight}"
    )


def generate_summary(schema_txt: str, model: str, industry: str,
                     company_name: str = "", company_context: str = "") -> str:
    if _MOCK_MODE:
        return _build_mock_summary(schema_txt, industry, company_name, company_context)
    if _BACKEND is None:
        tables = [ln for ln in schema_txt.splitlines() if ln.startswith("TABLE")]
        return (
            f"This database contains {len(tables)} table(s) of synthetic {INDUSTRIES.get(industry, '')} data. "
            "Column names were automatically normalized to snake_case. "
            "Add an LLM API key (ANTHROPIC_API_KEY / OPENAI_API_KEY) to generate an AI-powered summary."
        )
    context_prefix = ""
    if company_name or company_context:
        context_prefix = f"This database belongs to {company_name}" if company_name else "This database belongs to a company"
        if company_context:
            context_prefix += f", described as: {company_context.strip()}"
        context_prefix += ". "
    return _call_llm(model, _SUM_SYSTEM,
                     f"{context_prefix}Summarize this {INDUSTRIES.get(industry, '')} database "
                     f"with specific insights relevant to the company's context:\n\n{schema_txt}")

# ── Export ────────────────────────────────────────────────────────────────────
def _export_table(industry: str, table: str, fmt: str) -> Response:
    project = f"demo_{industry}"
    with DataLayer(project) as dl:
        if not dl.table_exists(table):
            raise HTTPException(404, f"Table '{table}' not found in project '{project}'")
        df = dl.materialize_df(table, max_rows=50_000)

    if fmt == "csv":
        return Response(
            content=df.to_csv(index=False),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{table}.csv"'},
        )
    if fmt == "json":
        return Response(
            content=df.to_json(orient="records", date_format="iso", indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{table}.json"'},
        )
    if fmt == "parquet":
        buf = io.BytesIO()
        df.to_parquet(buf, index=False, engine="pyarrow")
        buf.seek(0)
        return Response(
            content=buf.read(),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{table}.parquet"'},
        )
    if fmt == "txt":
        return Response(
            content=df.to_csv(index=False, sep="\t"),
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{table}.txt"'},
        )
    if fmt == "xlsx":
        buf = io.BytesIO()
        df.to_excel(buf, index=False, engine="openpyxl")
        buf.seek(0)
        return Response(
            content=buf.read(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{table}.xlsx"'},
        )
    raise HTTPException(400, f"Unknown format: {fmt!r}")

# ── PDF report ────────────────────────────────────────────────────────────────
_PDF_CHAR_MAP = str.maketrans({
    '—': '--', '–': '-',
    '‘': "'",  '’': "'",
    '“': '"',  '”': '"',
    '…': '...','·': '.',
    '•': '-',  '’': "'",
})


def _ps(s: str) -> str:
    """Make a string safe for Helvetica (Latin-1) in fpdf."""
    return s.translate(_PDF_CHAR_MAP).encode('latin-1', errors='replace').decode('latin-1')


def _make_pdf(industry: str) -> bytes:
    from fpdf import FPDF

    cached  = _result_cache.get(industry, {})
    summary = cached.get("summary", "")
    project = f"demo_{industry}"

    with DataLayer(project) as dl:
        tables      = dl.list_tables()
        dfs         = {t: dl.materialize_df(t, max_rows=50_000) for t in tables}
        col_renames = dl.column_renames.copy()
        schema      = dl.schema_json()

    all_renames = [(tbl, r) for tbl, rlist in col_renames.items()
                   for r in rlist if r["changed"]]
    total_rows  = sum(len(df) for df in dfs.values())
    total_cols  = sum(len(df.columns) for df in dfs.values())

    W     = 180   # usable width mm (A4, 15mm margins each side)
    ORANGE = (196, 82,  42)
    NAVY   = (18,  26,  56)
    LGRAY  = (241, 245, 249)
    MGRAY  = (100, 116, 139)
    DGRAY  = (51,  65,  85)
    WHITE  = (255, 255, 255)

    class _PDF(FPDF):
        def footer(self):
            self.set_y(-14)
            self.set_draw_color(*ORANGE)
            self.set_line_width(0.4)
            self.line(15, self.get_y(), 195, self.get_y())
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*MGRAY)
            self.cell(0, 8, _ps(f"TDG  --  Tailored Data Generation  |  Page {self.page_no()}"), align="C")

    pdf = _PDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(auto=True, margin=20)

    def section(title: str, sub: str = ""):
        y = pdf.get_y()
        pdf.set_fill_color(*ORANGE)
        pdf.rect(15, y, 3, 8, style="F")
        pdf.set_xy(20, y)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*NAVY)
        pdf.cell(0, 8, _ps(title), ln=True)
        if sub:
            pdf.set_x(20)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*MGRAY)
            pdf.cell(0, 5, _ps(sub), ln=True)
        pdf.ln(3)

    # ── COVER PAGE ────────────────────────────────────────────────────
    pdf.add_page()

    # Orange header bar
    pdf.set_fill_color(*ORANGE)
    pdf.rect(0, 0, 210, 46, style="F")

    # Navy logo box
    pdf.set_fill_color(*NAVY)
    pdf.rect(15, 9, 26, 26, style="F")
    pdf.set_xy(15, 14)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*WHITE)
    pdf.cell(26, 5, "DATABASE", align="C", ln=True)
    pdf.set_xy(15, 22)
    pdf.set_font("Helvetica", "BI", 11)
    pdf.cell(26, 6, "TDG", align="C", ln=True)

    # Title
    pdf.set_xy(46, 12)
    pdf.set_font("Helvetica", "BI", 28)
    pdf.set_text_color(*WHITE)
    pdf.cell(0, 12, "TDG", ln=True)
    pdf.set_xy(46, 28)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(255, 220, 200)
    pdf.cell(0, 7, "Tailored Data Generation  --  Data Report", ln=True)

    # Company / industry info
    pdf.set_y(54)
    co_name = cached.get("company_name", "")
    co_ctx  = cached.get("company_context", "")
    if co_name:
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(*NAVY)
        pdf.cell(0, 8, _ps(co_name), ln=True)
    if co_ctx:
        short_ctx = co_ctx[:220] + ("..." if len(co_ctx) > 220 else "")
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(*MGRAY)
        pdf.multi_cell(W, 5.5, _ps(short_ctx))
        pdf.ln(2)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*ORANGE)
    pdf.cell(0, 6, _ps(f"Industry: {INDUSTRIES.get(industry, industry)}"), ln=True)
    pdf.ln(6)

    # Stats boxes (4 in a row)
    stats_data = [
        ("Tables",        str(len(tables))),
        ("Total Rows",    str(total_rows)),
        ("Total Columns", str(total_cols)),
        ("Cols Renamed",  str(len(all_renames))),
    ]
    BW, BH, GAP = 41, 22, 3
    y0 = pdf.get_y()
    for i, (lbl, val) in enumerate(stats_data):
        bx = 15 + i * (BW + GAP)
        pdf.set_fill_color(*LGRAY)
        pdf.set_draw_color(*NAVY)
        pdf.set_line_width(0.3)
        pdf.rect(bx, y0, BW, BH, style="FD")
        pdf.set_fill_color(*ORANGE)
        pdf.rect(bx, y0, BW, 2.5, style="F")
        pdf.set_xy(bx, y0 + 3)
        pdf.set_font("Helvetica", "B", 17)
        pdf.set_text_color(*NAVY)
        pdf.cell(BW, 11, val, align="C")
        pdf.set_xy(bx, y0 + 14)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*MGRAY)
        pdf.cell(BW, 6, lbl, align="C")
    pdf.set_y(y0 + BH + 10)

    # AI Summary
    if summary:
        section("AI Analysis")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*DGRAY)
        pdf.multi_cell(W, 5.5, _ps(summary))
        pdf.ln(5)

    # Database Schema
    section("Database Schema",
            f"{len(tables)} tables  |  {total_rows} rows  |  {total_cols} columns")
    for t in schema.get("tables", []):
        if pdf.get_y() > 232:
            pdf.add_page()
        # Navy table name header
        y_t = pdf.get_y()
        pdf.set_fill_color(*NAVY)
        pdf.rect(15, y_t, W, 7, style="F")
        pdf.set_xy(18, y_t)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*WHITE)
        pdf.cell(W - 3, 7,
                 _ps(f"{t['name']}   ({t['row_count']} rows  |  {len(t['columns'])} cols)"),
                 ln=True)
        # Columns 3 per row
        col_items = [(c["name"], c["type"]) for c in t["columns"]]
        PER  = 3
        cw   = W / PER
        for ci in range(0, len(col_items), PER):
            chunk = col_items[ci:ci + PER]
            bg    = (ci // PER) % 2 == 0
            pdf.set_fill_color(*(LGRAY if bg else WHITE))
            for (cname, ctype) in chunk:
                pdf.set_font("Helvetica", "B", 8)
                pdf.set_text_color(*NAVY)
                pdf.cell(cw * 0.55, 5.5, _ps(cname[:20]), fill=True)
                pdf.set_font("Helvetica", "", 7)
                pdf.set_text_color(*MGRAY)
                pdf.cell(cw * 0.45, 5.5, _ps(ctype[:14]), fill=True)
            for _ in range(PER - len(chunk)):
                pdf.set_fill_color(*(LGRAY if bg else WHITE))
                pdf.cell(cw, 5.5, "", fill=True)
            pdf.ln()
        pdf.ln(4)

    # ── Column Cleaning ───────────────────────────────────────────────
    if all_renames:
        pdf.add_page()
        section("Column Name Cleaning",
                f"{len(all_renames)} columns automatically normalized to snake_case")
        CW = [46, 67, 67]
        pdf.set_fill_color(*NAVY)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*WHITE)
        for txt, w in zip(["Table", "Original (messy)", "Cleaned (snake_case)"], CW):
            pdf.cell(w, 7, txt, fill=True, align="C")
        pdf.ln()
        pdf.set_font("Courier", "", 8)
        for i, (tbl, r) in enumerate(all_renames):
            bg = i % 2 == 0
            pdf.set_fill_color(*(LGRAY if bg else WHITE))
            pdf.set_text_color(*DGRAY)
            pdf.cell(CW[0], 6, _ps(tbl[:20]), fill=True)
            pdf.set_text_color(*ORANGE)
            pdf.cell(CW[1], 6, _ps(r["original"][:32]), fill=True)
            pdf.set_text_color(*NAVY)
            pdf.cell(CW[2], 6, _ps(r["cleaned"][:32]), fill=True, ln=True)

    # ── Two data tables per page ─────────────────────────────────────
    def draw_table(tname, df):
        cols   = list(df.columns)
        n      = len(cols)
        col_w  = W / n
        fs     = 8 if n <= 6 else (7 if n <= 9 else 6)
        max_ch = max(4, int(col_w / (fs * 0.44)))
        actual = min(10, len(df))
        y0     = pdf.get_y()

        # Navy title banner
        BANNER_H = 12
        pdf.set_fill_color(*NAVY)
        pdf.rect(15, y0, W, BANNER_H, style="F")
        # Table name (left-aligned, bold white)
        pdf.set_xy(19, y0 + 2)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*WHITE)
        pdf.cell(W * 0.55, 8, _ps(tname))
        # Metadata (right-aligned, light)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(195, 205, 225)
        pdf.cell(W * 0.45 - 4, 8,
                 _ps(f"{len(df)} rows  x  {n} cols  --  first {actual} rows"),
                 align="R", ln=True)

        # Orange accent strip
        pdf.set_fill_color(*ORANGE)
        pdf.rect(15, y0 + BANNER_H, W, 2, style="F")
        pdf.set_y(y0 + BANNER_H + 2)

        # Column header row (slightly lighter navy)
        pdf.set_fill_color(30, 45, 85)
        pdf.set_font("Helvetica", "B", fs)
        pdf.set_text_color(*WHITE)
        for col in cols:
            pdf.cell(col_w, 7, _ps(str(col)[:max_ch]), fill=True)
        pdf.ln()

        # Data rows — alternating fill, subtle bottom border per row
        pdf.set_font("Helvetica", "", fs)
        pdf.set_draw_color(210, 215, 228)
        pdf.set_line_width(0.1)
        for i, (_, row) in enumerate(df.head(actual).iterrows()):
            pdf.set_fill_color(*((LGRAY) if i % 2 == 0 else WHITE))
            pdf.set_text_color(*DGRAY)
            for col in cols:
                v = row[col]
                cell_str = "" if (v is None or (isinstance(v, float) and math.isnan(v))) \
                           else _ps(str(v)[:max_ch])
                pdf.cell(col_w, 6, cell_str, fill=True, border="B")
            pdf.ln()

        # Navy bottom border line
        pdf.set_draw_color(*NAVY)
        pdf.set_line_width(0.5)
        pdf.line(15, pdf.get_y(), 15 + W, pdf.get_y())
        pdf.ln(10)

    tname_list = list(dfs.items())
    for i in range(0, len(tname_list), 2):
        pdf.add_page()
        draw_table(*tname_list[i])
        if i + 1 < len(tname_list):
            draw_table(*tname_list[i + 1])

    return bytes(pdf.output())

# ── Upload & Scale helpers ────────────────────────────────────────────────────
_MAX_CTGAN_CARD  = 30     # max unique values per text column fed to CTGAN
_MAX_TRAIN_ROWS  = 2000   # max source rows CTGAN trains on (bounds fit time)

def _df_dtype(series: pd.Series) -> str:
    if pd.api.types.is_integer_dtype(series):   return "INTEGER"
    if pd.api.types.is_float_dtype(series):     return "DECIMAL"
    if pd.api.types.is_bool_dtype(series):      return "BOOLEAN"
    if pd.api.types.is_datetime64_any_dtype(series): return "DATE"
    return "TEXT"


def _is_integer_like(series: pd.Series) -> bool:
    """
    True if every non-null value is a whole number — even when pandas stored
    the column as float64 (which it does whenever an integer column contains
    missing values).  Used so columns like Attendance / RoundID are treated
    as integers, not decimals.
    """
    s = series.dropna()
    if s.empty or not pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s):
        return False
    try:
        return bool((s == s.round()).all())
    except Exception:
        return False


def _pg_data_to_dfs(data: dict) -> dict[str, pd.DataFrame]:
    """Convert generate_data()'s table dict into {table_name: DataFrame}, with
    numeric columns coerced to real numeric dtypes so SDV models them correctly."""
    out: dict[str, pd.DataFrame] = {}
    for tbl in data.get("tables", []):
        cols = [c["name"] for c in tbl["columns"]]
        df = pd.DataFrame(tbl.get("rows", []), columns=cols)
        for meta in tbl["columns"]:
            if meta.get("type", "").upper() in ("INTEGER", "DECIMAL"):
                df[meta["name"]] = pd.to_numeric(df[meta["name"]], errors="coerce")
        out[tbl["name"]] = df
    return out


def _is_identifier_column(name: str, series: pd.Series) -> bool:
    """
    True if a numeric column should be treated as an identifier / code / year
    rather than a continuous quantity.  Such columns must be resampled from the
    original values (CTGAN would interpolate nonsense like a RoundID of 178432
    or render a large float in scientific notation).

    Detected when the column is integer-like AND either:
      - its name ends with "id" (MatchID, RoundID, round_id, …), or
      - its values are large-magnitude non-negative integers (>= 1000), which
        is the signature of codes / IDs / years rather than small counts.
    Small bounded counts (goals 0-10, half-time goals) are left for CTGAN so
    they still vary realistically.
    """
    if not _is_integer_like(series):
        return False
    cleaned = re.sub(r"[^a-z0-9]", "", str(name).lower())
    if cleaned == "id" or cleaned.endswith("id"):
        return True
    s = series.dropna()
    try:
        return bool(float(s.min()) >= 0 and float(s.max()) >= 1000)
    except Exception:
        return False


def _fix_cross_references(out: pd.DataFrame, src: pd.DataFrame) -> pd.DataFrame:
    """
    For sparse text columns (>60% originally empty) whose non-empty values
    EMBED text from other columns as part of a longer phrase (e.g. "Germany win
    on penalties" referencing a team name), blank out any generated cell where
    the referenced value is not actually present elsewhere in that row.

    Only phrase-style embeddings count: a cell that *equals* another column's
    value (e.g. a home-team cell "Sweden" that equals an away-team value) is NOT
    a reference — otherwise this would wrongly blank ordinary entity columns.
    """
    out = out.copy()
    text_cols = [c for c in src.columns if src[c].dtype == object and c in out.columns]
    for col in text_cols:
        src_nonempty = src[col].dropna()
        if len(src_nonempty) == 0 or len(src_nonempty) / len(src) > 0.4:
            continue
        other_text_cols = [c for c in text_cols if c != col]
        all_other_vals = sorted(
            {str(v) for c2 in other_text_cols for v in src[c2].dropna() if len(str(v)) > 2},
            key=len, reverse=True,
        )
        if not all_other_vals:
            continue
        nonempty_mask = out[col].notna() & (out[col].astype(str).str.strip() != "")
        bad_rows = []
        for i in out.index[nonempty_mask]:
            cell_str = str(out.at[i, col])
            # Embedded-as-phrase only: the value appears inside a LONGER cell.
            # A cell that exactly equals another column's value is not a ref.
            refs = [v for v in all_other_vals if v != cell_str and v in cell_str]
            if not refs:
                continue
            row_other_vals = {
                str(out.at[i, c2])
                for c2 in other_text_cols
                if c2 in out.columns and pd.notna(out.at[i, c2])
            }
            if any(ref not in row_other_vals for ref in refs):
                bad_rows.append(i)
        if bad_rows:
            out.loc[bad_rows, col] = ""
    return out


def _sdv_fit_and_sample(
    tables: dict[str, pd.DataFrame], target_rows: int, epochs: int = 50
) -> dict[str, pd.DataFrame]:
    """
    Block-bootstrap synthetic data generation.

    Every output row is sampled as a COMPLETE row from the source data, so all
    within-row relationships are preserved exactly. Independent per-column
    generation (the previous CTGAN / per-column resampling approach) destroyed
    these relationships and produced impossible rows; bootstrapping whole rows
    guarantees, for example:
      • the home and away teams differ — a team never plays itself
      • Year agrees with Datetime; MatchID/RoundID belong to their row; Stadium
        matches its City
      • half-time goals never exceed full-time goals
      • identifiers, years and codes stay real and in-range — no interpolated
        values, no scientific-notation floats, no decimals on integer columns

    Variety + completeness: pure bootstrap reproduces the source's value
    frequencies, so a degraded source (one value dominating a column, or a
    column that is mostly blank) yields equally bad output. A per-column pass
    therefore resamples any column that has notable gaps (filled <90%) OR is
    over-dominated by one value (>50% share) from its DISTINCT real values —
    filling blanks and breaking domination, for text AND identifier-numeric
    columns (Year, MatchID, RoundID, Attendance, team names). Small-count
    numeric columns (goals) and genuinely-sparse columns (Win conditions) are
    left as bootstrapped so constraints and intended blanks are preserved;
    well-populated, non-dominated columns keep their consistent bootstrapped
    values so clean inputs stay internally consistent.

    `epochs` is accepted for API compatibility but no longer affects output
    (there is no model training — generation is near-instant).
    """
    import numpy as np
    results: dict[str, pd.DataFrame] = {}
    rng = np.random.default_rng()

    for tname, df in tables.items():
        df = df.copy()

        # 1. Pre-clean strings
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].astype(str).str.strip()
                df[col] = df[col].replace({"nan": pd.NA, "None": pd.NA, "": pd.NA})
        df = df[[c for c in df.columns if not df[c].isna().all()]]
        if df.empty:
            continue

        df = df.reset_index(drop=True)
        n = len(df)

        # 2. Block bootstrap — sample WHOLE rows. Every field in an output row
        #    comes from the same real source row, so all relationships hold.
        idx = rng.integers(0, n, size=target_rows)
        out = df.iloc[idx].reset_index(drop=True)

        # 3. Per-column variety + fill pass.
        #    Block bootstrap reproduces the source distribution exactly, so a
        #    degraded source (one value dominating a column, or a column that is
        #    mostly blank) yields equally bad output. For each column:
        #      • SPARSE columns (filled <10% of the time, e.g. Win conditions):
        #        leave mostly blank — that is their nature.
        #      • SMALL-COUNT numeric columns (e.g. goals 0-7): keep the
        #        bootstrapped values so half-time<=full-time and integer
        #        validity are preserved.
        #      • Columns with notable gaps (filled <90%) OR over-dominated by one
        #        value (>50% share) are resampled independently from their
        #        DISTINCT real values. This both fills blanks and breaks
        #        single-value domination — for TEXT and IDENTIFIER NUMERIC
        #        columns alike (Year, MatchID, RoundID, Attendance, team names).
        #      • Well-populated, non-dominated columns keep their bootstrapped
        #        (row-consistent) values, so clean inputs stay internally
        #        consistent (Year matches Datetime, etc.).
        for col in out.columns:
            if col not in df.columns:
                continue
            pool = df[col].dropna()
            if pool.dtype == object:
                pool = pool[pool.astype(str).str.strip() != ""]
            if pool.empty:
                continue
            distinct = pool.unique()
            if len(distinct) < 2:
                continue  # only one real value — nothing to diversify
            fill_rate = len(pool) / n
            top_share = float(pool.value_counts(normalize=True).iloc[0])
            is_numeric = pd.api.types.is_numeric_dtype(df[col])
            small_count_numeric = (
                is_numeric and _is_integer_like(df[col])
                and not _is_identifier_column(col, df[col])
                and pool.nunique() <= 30
            )

            if fill_rate < 0.10:
                continue   # genuinely sparse — keep blanks
            if small_count_numeric:
                continue   # goals etc. — keep bootstrapped for constraints
            if fill_rate >= 0.90 and top_share <= 0.50:
                continue   # well-populated and not dominated — keep consistent

            # Resample independently from distinct real values.
            if is_numeric:
                picks = rng.choice(np.asarray(distinct), size=len(out), replace=True)
                ser = pd.to_numeric(pd.Series(picks), errors="coerce")
                if _is_integer_like(df[col]):
                    ser = ser.round().astype(int)
                out[col] = ser.values
            else:
                picks = rng.choice(
                    np.array([str(v) for v in distinct], dtype=object),
                    size=len(out), replace=True,
                )
                out[col] = picks

        # 5. Safety net — two columns drawn from the same entity vocabulary
        #    (e.g. home/away team name, or home/away initials) must never hold
        #    the same value in a row. Real source rows already satisfy this, so
        #    this only ever fires on degraded inputs.
        text_cols = [c for c in df.columns if df[c].dtype == object]
        for i, c1 in enumerate(text_cols):
            v1 = set(df[c1].dropna().astype(str))
            if not v1:
                continue
            for c2 in text_cols[i + 1:]:
                v2 = set(df[c2].dropna().astype(str))
                if len(v2) < 2:
                    continue
                if len(v1 & v2) / len(v1 | v2) < 0.5:
                    continue  # not the same kind of value — not a real pair
                alt_pool = list(v2)
                clash = out[c1].astype(str).values == out[c2].astype(str).values
                for ridx in np.where(clash)[0]:
                    cur = str(out.at[ridx, c1])
                    choices = [v for v in alt_pool if v != cur]
                    if choices:
                        out.at[ridx, c2] = rng.choice(choices)

        # 6. Reorder columns to match the original table
        out = out[[c for c in df.columns if c in out.columns]]

        # 6b. Keep sparse "reference" columns consistent: a Win-conditions value
        #     like "Argentina win" must only appear when Argentina is one of the
        #     teams in that row. After independent resampling this can break, so
        #     blank any sparse-column cell whose embedded reference isn't present.
        out = _fix_cross_references(out, df)

        # 7. Final repair sweep.
        #     A bootstrapped row can carry a genuine source null. Here we
        #     (a) normalize empty/whitespace strings to null, then (b) for
        #     columns that were populated in the source (>=10% filled) repair
        #     every gap by drawing from the original value pool. Columns that
        #     were genuinely sparse (e.g. Win conditions) keep their blanks.
        for col in out.columns:
            src_col = df[col] if col in df.columns else None

            # Normalize empty / whitespace-only strings to NA (object cols only)
            if out[col].dtype == object:
                blank = out[col].isna() | (out[col].astype(str).str.strip() == "")
                out.loc[blank, col] = pd.NA

            if not out[col].isna().any():
                continue

            # How densely was this column filled in the source?  Only genuinely
            # sparse columns (<10% filled, e.g. Win conditions) keep their gaps.
            if src_col is not None:
                src_clean = src_col.dropna()
                if src_clean.dtype == object:
                    src_clean = src_clean[src_clean.astype(str).str.strip() != ""]
                dense = len(src_clean) / max(len(src_col), 1) >= 0.10
            else:
                src_clean = pd.Series([], dtype=object)
                dense = False

            if not dense:
                # Sparse source column — blanks are expected, leave them empty
                if out[col].dtype == object:
                    out[col] = out[col].fillna("")
                continue

            # Dense column — must not have gaps. Repair from the original pool.
            if src_col is not None and pd.api.types.is_numeric_dtype(src_col):
                out[col] = out[col].fillna(src_col.dropna().median())
            else:
                pool = src_clean.values
                n_missing = int(out[col].isna().sum())
                if len(pool) > 0 and n_missing > 0:
                    out.loc[out[col].isna(), col] = rng.choice(
                        pool, size=n_missing, replace=True
                    )
                else:
                    out[col] = out[col].fillna("")

        results[tname] = out
    return results


# ── Result cache (last generation per industry, for the download endpoint) ────
_result_cache: dict[str, dict] = {}

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="TDG Demo")


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc)})


class GenerateRequest(BaseModel):
    industry: str
    model: str
    messy: bool = True
    company_name: str = ""
    company_context: str = ""
    num_rows: int | None = None
    num_cols: int | None = None
    custom_columns: list[str] | None = None

    @field_validator("num_rows")
    @classmethod
    def _check_rows(cls, v):
        if v is not None and not (5 <= v <= 50):
            raise ValueError("num_rows must be between 5 and 50")
        return v

    @field_validator("num_cols")
    @classmethod
    def _check_cols(cls, v):
        if v is not None and not (3 <= v <= 8):
            raise ValueError("num_cols must be between 3 and 8")
        return v

    @field_validator("custom_columns")
    @classmethod
    def _check_custom_cols(cls, v):
        if v is not None:
            cleaned = [c.strip() for c in v if c.strip()]
            if len(cleaned) > 15:
                raise ValueError("custom_columns must have at most 15 entries")
            return cleaned if cleaned else None
        return v


@app.get("/api/config")
def api_config():
    return {"models": MODELS, "industries": INDUSTRIES, "file_formats": FILE_FORMATS}


@app.post("/api/generate")
def api_generate(req: GenerateRequest):
    if req.industry not in INDUSTRIES:
        raise HTTPException(400, f"Unknown industry: {req.industry!r}")
    if _BACKEND is None and not _MOCK_MODE:
        raise HTTPException(
            500,
            "No LLM backend installed. Run: pip install litellm "
            "(then set ANTHROPIC_API_KEY / OPENAI_API_KEY)",
        )
    try:
        co_name = req.company_name.strip()
        co_ctx  = req.company_context.strip()
        data                                    = generate_data(req.industry, req.model, req.messy,
                                                                co_name, co_ctx,
                                                                req.num_rows, req.num_cols,
                                                                req.custom_columns)
        write_postgres(data)
        schema, schema_t, previews, col_renames = snapshot_to_duckdb(req.industry)
        summary                                 = generate_summary(schema_t, req.model, req.industry,
                                                                   co_name, co_ctx)
        sources = _MOCK_SOURCES.get(req.industry, {})
        _result_cache[req.industry] = {
            "summary":      summary,
            "schema_text":  schema_t,
            "company_name": co_name,
            "company_context": co_ctx,
        }
        return {
            "industry":       req.industry,
            "model":          req.model,
            "messy":          req.messy,
            "company_name":   co_name,
            "schema":         schema,
            "tables":         previews,
            "summary":        summary,
            "column_renames": col_renames,
            "sources":        sources,
            "num_rows":        req.num_rows,
            "num_cols":        req.num_cols,
            "custom_columns":  req.custom_columns,
        }
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"LLM returned malformed JSON — try again. ({exc})")
    except psycopg2.OperationalError as exc:
        raise HTTPException(
            503,
            f"PostgreSQL connection failed: {exc}\n"
            "Set DEMO_PG_HOST / DEMO_PG_DB / DEMO_PG_USER / DEMO_PG_PASSWORD env vars.",
        )
    except Exception as exc:
        raise HTTPException(500, str(exc))


class GenerateScaleRequest(GenerateRequest):
    """AI-generate a seed dataset, then scale it up with SDV."""
    scale_rows: int = 1000
    epochs: int = 50


@app.post("/api/generate-and-scale")
async def api_generate_and_scale(req: GenerateScaleRequest):
    """
    Pipeline: the LLM (or mock) generates a small, realistic seed dataset, then
    SDV/CTGAN learns its patterns and scales it up to `scale_rows` rows — giving
    AI-quality domain realism at a volume the LLM alone could never produce.
    """
    if req.industry not in INDUSTRIES:
        raise HTTPException(400, f"Unknown industry: {req.industry!r}")
    if _BACKEND is None and not _MOCK_MODE:
        raise HTTPException(
            500,
            "No LLM backend installed. Run: pip install litellm "
            "(then set ANTHROPIC_API_KEY / OPENAI_API_KEY)",
        )
    if not _SDV_AVAILABLE:
        raise HTTPException(500, "SDV is not installed. Run: pip install sdv")

    scale_rows = max(100, min(req.scale_rows, 100_000))
    epochs     = max(10,  min(req.epochs, 500))

    try:
        co_name = req.company_name.strip()
        co_ctx  = req.company_context.strip()
        from fastapi.concurrency import run_in_threadpool

        # 1. AI generates a small seed dataset
        data = await run_in_threadpool(
            lambda: generate_data(req.industry, req.model, req.messy, co_name, co_ctx,
                                  req.num_rows, req.num_cols, req.custom_columns)
        )
        seed = _pg_data_to_dfs(data)
        if not seed:
            raise HTTPException(500, "AI generation produced no tables to scale.")

        # 2. SDV scales the seed up (CPU-bound → threadpool so the loop stays alive)
        scaled = await run_in_threadpool(
            lambda: _sdv_fit_and_sample(seed, scale_rows, epochs)
        )

        # 3. Snapshot directly to DuckDB (no PostgreSQL round-trip)
        schema, schema_t, previews, col_renames = await run_in_threadpool(
            lambda: snapshot_dfs_to_duckdb(req.industry, scaled)
        )

        _result_cache[req.industry] = {
            "summary":         "",
            "schema_text":     schema_t,
            "company_name":    co_name,
            "company_context": co_ctx,
        }
        return {
            "industry":       req.industry,
            "model":          req.model,
            "messy":          req.messy,
            "company_name":   co_name,
            "schema":         schema,
            "tables":         previews,
            "summary":        "",
            "column_renames": col_renames,
            "sources":        _MOCK_SOURCES.get(req.industry, {}),
            "num_rows":       scale_rows,
            "num_cols":       req.num_cols,
            "custom_columns": req.custom_columns,
        }
    except HTTPException:
        raise
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"LLM returned malformed JSON — try again. ({exc})")
    except Exception as exc:
        raise HTTPException(500, f"Generate-and-scale failed: {exc}")


@app.get("/api/export/{industry}/{table}")
def api_export(industry: str, table: str, fmt: str = Query("csv")):
    return _export_table(industry, table, fmt)


@app.get("/api/download/{industry}")
def api_download_all(industry: str, formats: str = Query("csv,json,parquet")):
    fmt_list = [f.strip().lower() for f in formats.split(",") if f.strip()]
    valid_fmts = [f for f in fmt_list if f in {"csv", "json", "parquet", "txt", "xlsx"}]
    if not valid_fmts:
        raise HTTPException(400, "No valid formats specified")

    project = f"demo_{industry}"
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        with DataLayer(project) as dl:
            if not dl.list_tables():
                raise HTTPException(404, f"No data found for '{industry}' — generate it first")
            for table in dl.list_tables():
                df = dl.materialize_df(table, max_rows=50_000)
                for fmt in valid_fmts:
                    if fmt == "csv":
                        zf.writestr(f"{table}.csv", df.to_csv(index=False))
                    elif fmt == "json":
                        zf.writestr(f"{table}.json",
                                    df.to_json(orient="records", date_format="iso", indent=2))
                    elif fmt == "parquet":
                        pq_buf = io.BytesIO()
                        df.to_parquet(pq_buf, index=False, engine="pyarrow")
                        zf.writestr(f"{table}.parquet", pq_buf.getvalue())
                    elif fmt == "txt":
                        zf.writestr(f"{table}.txt", df.to_csv(index=False, sep="\t"))
                    elif fmt == "xlsx":
                        xl_buf = io.BytesIO()
                        df.to_excel(xl_buf, index=False, engine="openpyxl")
                        zf.writestr(f"{table}.xlsx", xl_buf.getvalue())

        cached = _result_cache.get(industry, {})
        if cached.get("summary"):
            zf.writestr("summary.txt", cached["summary"])
        if cached.get("schema_text"):
            zf.writestr("schema.txt", cached["schema_text"])

    zip_buf.seek(0)
    return Response(
        content=zip_buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{industry}_data.zip"'},
    )


@app.post("/api/parse-context")
async def api_parse_context(file: UploadFile = File(...)):
    content  = await file.read()
    filename = file.filename or ""
    ext      = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"

    if ext in ("txt", "md", "csv", "rst"):
        text = content.decode("utf-8", errors="replace")
    elif ext == "pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content))
            text   = "\n".join(p.extract_text() or "" for p in reader.pages)
        except ImportError:
            raise HTTPException(500, "PDF parsing requires pypdf: pip install pypdf")
        except Exception as exc:
            raise HTTPException(400, f"Could not parse PDF: {exc}")
    elif ext == "docx":
        try:
            import docx
            doc  = docx.Document(io.BytesIO(content))
            text = "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            raise HTTPException(500, "DOCX parsing requires python-docx: pip install python-docx")
        except Exception as exc:
            raise HTTPException(400, f"Could not parse DOCX: {exc}")
    else:
        raise HTTPException(400, f"Unsupported file type '.{ext}'. Accepted: TXT, MD, PDF, DOCX.")

    text = text.strip()
    if not text:
        raise HTTPException(400, "No text could be extracted from this file.")

    return {"text": text[:4000], "filename": filename, "chars": len(text)}


@app.get("/api/report/{industry}")
def api_report(industry: str):
    try:
        from fpdf import FPDF  # noqa: F401
    except ImportError:
        raise HTTPException(500, "PDF generation requires fpdf2 — run: pip install fpdf2")
    project = f"demo_{industry}"
    with DataLayer(project) as dl:
        if not dl.list_tables():
            raise HTTPException(404, f"No data found for '{industry}' — generate it first")
    try:
        pdf_bytes = _make_pdf(industry)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{industry}_report.pdf"'},
        )
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.get("/api/sdv-status")
def api_sdv_status():
    return {"available": _SDV_AVAILABLE}


@app.post("/api/upload-and-scale")
async def api_upload_and_scale(
    files: list[UploadFile] = File(...),
    scale_rows: int = Form(1000),
    epochs: int = Form(100),
    industry: str = Form("retail"),
    company_name: str = Form(""),
    company_context: str = Form(""),
    model: str = Form("gpt-4o"),
):
    if not _SDV_AVAILABLE:
        raise HTTPException(500, "SDV is not installed. Run: pip install sdv")
    if industry not in INDUSTRIES:
        raise HTTPException(400, f"Unknown industry: {industry!r}")
    scale_rows = max(100, min(scale_rows, 100_000))
    epochs     = max(10,  min(epochs, 500))

    seed_tables: dict[str, pd.DataFrame] = {}
    for f in files:
        fname   = f.filename or "table"
        stem    = re.sub(r"[^a-zA-Z0-9_]", "_", pathlib.Path(fname).stem) or "table"
        ext     = fname.rsplit(".", 1)[-1].lower() if "." in fname else "csv"
        content = await f.read()
        try:
            if ext == "csv":
                df = pd.read_csv(io.BytesIO(content))
            elif ext in ("xlsx", "xls"):
                df = pd.read_excel(io.BytesIO(content))
            elif ext == "json":
                df = pd.read_json(io.BytesIO(content))
            elif ext == "parquet":
                df = pd.read_parquet(io.BytesIO(content))
            else:
                raise HTTPException(
                    400, f"Unsupported file type '.{ext}'. Accepted: CSV, XLSX, JSON, Parquet"
                )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, f"Could not read '{fname}': {exc}")

        # Sanitize column names
        sanitized: list[str] = []
        seen: dict[str, int] = {}
        for i, c in enumerate(df.columns):
            s = re.sub(r"[^a-zA-Z0-9_]", "_", str(c)).strip("_") or f"col_{i}"
            if s in seen:
                seen[s] += 1
                s = f"{s}_{seen[s]}"
            else:
                seen[s] = 0
            sanitized.append(s)
        df.columns = sanitized
        seed_tables[stem] = df

    if not seed_tables:
        raise HTTPException(400, "No files uploaded")

    try:
        # Run CPU-bound CTGAN training in a thread so the event loop stays alive.
        # Without this, uvicorn blocks entirely and the browser connection drops.
        from fastapi.concurrency import run_in_threadpool
        scaled = await run_in_threadpool(
            lambda: _sdv_fit_and_sample(seed_tables, scale_rows, epochs)
        )
    except Exception as exc:
        raise HTTPException(500, f"SDV scaling failed: {exc}")

    try:
        schema, schema_t, previews, col_renames = await run_in_threadpool(
            lambda: snapshot_dfs_to_duckdb(industry, scaled)
        )
        co_name = company_name.strip()
        co_ctx  = company_context.strip()
        _result_cache[industry] = {
            "summary":        "",
            "schema_text":    schema_t,
            "company_name":   co_name,
            "company_context": co_ctx,
        }
        return {
            "industry":       industry,
            "model":          model,
            "messy":          False,
            "company_name":   co_name,
            "schema":         schema,
            "tables":         previews,
            "summary":        "",
            "column_renames": col_renames,
            "sources":        {},
            "num_rows":       scale_rows,
            "num_cols":       None,
            "custom_columns": None,
        }
    except psycopg2.OperationalError as exc:
        raise HTTPException(
            503,
            f"PostgreSQL connection failed: {exc}\n"
            "Set DEMO_PG_HOST / DEMO_PG_DB / DEMO_PG_USER / DEMO_PG_PASSWORD env vars.",
        )
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.get("/")
def index():
    html_path = pathlib.Path(__file__).parent / "demo_ui.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))
