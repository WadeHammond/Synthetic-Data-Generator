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

from data_layer import DataLayer, clean_column_name
from sic_catalog import SIC_CATALOG

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

# ── Upload & Scale (SDV) ──────────────────────────────────────────────────────
# Detect SDV WITHOUT importing it — `import sdv` pulls in heavy dependencies
# (PyTorch) and must NOT run at container startup (that made the app hang on boot).
# The scaler imports SDV lazily, only when Upload & Scale actually runs.
import importlib.util
_SDV_AVAILABLE = importlib.util.find_spec("sdv") is not None

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
# ── Industry catalog (SIC divisions → subindustries) ───────────────────────────
# The public "industry" identifier used throughout the app is the *subindustry*
# key (globally unique). Tables authored as "<entity>_id" are normalized to
# "<entity>". INDUSTRIES stays a flat {sub_key: label} map so existing validation
# and label lookups keep working; INDUSTRY_TREE drives the two-level UI dropdown.
def _normalize_tables(tables):
    out = []
    for tname, cols in tables:
        if tname.endswith("_id"):
            tname = tname[:-3]
        out.append((tname, list(cols)))
    return out

_SUB_INDEX: dict[str, dict] = {}     # sub_key -> {label, blurb, tables, vocab}
_SUB_DIVISION: dict[str, str] = {}   # sub_key -> division label
INDUSTRIES: dict[str, str] = {}      # sub_key -> sub label (validation + lookups)
INDUSTRY_TREE: list[dict] = []       # [{key, label, subindustries:[{key,label}]}]

for _dkey, _dval in SIC_CATALOG.items():
    _subs = []
    for _skey, _sval in _dval["subs"].items():
        _SUB_INDEX[_skey] = {
            "label":  _sval["label"],
            "blurb":  _sval.get("blurb", ""),
            "tables": _normalize_tables(_sval["tables"]),
            "vocab":  _sval.get("vocab", {}),
        }
        _SUB_DIVISION[_skey] = _dval["label"]
        INDUSTRIES[_skey]    = _sval["label"]
        _subs.append({"key": _skey, "label": _sval["label"]})
    INDUSTRY_TREE.append({"key": _dkey, "label": _dval["label"], "subindustries": _subs})

# Simulated source-file format per table (UI badges), assigned round-robin.
_FILE_FMT_BADGES = ["CSV", "JSON", "Parquet"]
def _mock_sources(subkey: str) -> dict:
    entry = _SUB_INDEX.get(subkey)
    if not entry:
        return {}
    return {tname: _FILE_FMT_BADGES[i % len(_FILE_FMT_BADGES)]
            for i, (tname, _cols) in enumerate(entry["tables"])}

# ── LLM call ─────────────────────────────────────────────────────────────────
def _llm_provider_route(model: str) -> str:
    """Prefix the model id with its provider so litellm targets the right backend
    even when its built-in model map predates the model id (e.g. on Azure)."""
    if model.startswith("claude"):
        return f"anthropic/{model}"
    if model.startswith(("gpt", "o1", "o3", "o4")):
        return f"openai/{model}"
    return model


def _call_llm(model: str, system: str, user: str, max_tokens: int = 8192) -> str:
    """Call the configured LLM backend. The model menu (Claude Sonnet/Haiku, GPT-4o)
    all accept `temperature`; do not add Opus 4.7/4.8 or Fable here without removing
    `temperature`, which those models reject with a 400."""
    if _BACKEND == "litellm":
        r = _llm.completion(
            model=_llm_provider_route(model), temperature=0.7, max_tokens=max_tokens,
            messages=[{"role": "system", "content": system},
                      {"role": "user",   "content": user}],
        )
        return r.choices[0].message.content
    if _BACKEND == "anthropic":
        r = _anth.Anthropic().messages.create(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        )
        return r.content[0].text
    if _BACKEND == "openai":
        r = _oai.OpenAI().chat.completions.create(
            model=model, temperature=0.7, max_tokens=max_tokens,
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

def _messify(col: str) -> str:
    """Render a clean snake_case column as a 'messy' display name (spaces, casing,
    abbreviations) so the column-cleaning step has something to normalize."""
    parts = col.split("_")
    out = []
    for p in parts:
        u = p.lower()
        if u == "id":
            out.append("ID")
        elif u == "pct":
            out.append("%")
        elif u in ("num", "no"):
            out.append("No.")
        else:
            out.append(p.capitalize())
    return " ".join(out)


def _build_llm_prompt(subkey: str, messy: bool) -> str:
    """Build a subindustry-tailored instruction describing the desired relational
    schema, so the LLM produces domain-accurate data for that specific industry."""
    entry = _SUB_INDEX[subkey]
    lines = []
    for tname, cols in entry["tables"]:
        disp = [_messify(c) if messy else c for c in cols]
        lines.append(f"  - {tname}({', '.join(disp)})")
    spec = "\n".join(lines)
    return (
        f"Generate a realistic {entry['label']} database for a business that "
        f"{entry['blurb']}\n"
        f"Use these relational tables and columns as the schema (preserve the "
        f"foreign-key links so the tables join correctly):\n{spec}\n"
        f"Populate every column with values that are domain-accurate and realistic "
        f"for this specific industry — names, dates, amounts, categories, and codes "
        f"should all look like genuine {entry['label']} data, never placeholders."
    )


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


def _make_row_ctx(variety_idx: int, company_name: str, force_food: bool | None = None) -> dict:
    """Return a row-level context dict so related columns (name, category, price) stay
    consistent. `force_food` overrides the company-name heuristic (e.g. for a restaurant
    subindustry that should always use a food menu regardless of company name)."""
    if force_food is None:
        co = company_name.lower()
        is_food = any(k in co for k in (
            "subway", "sandwich", "deli", "restaurant", "cafe", "coffee", "pizza",
            "burger", "taco", "bakery", "kitchen", "bistro", "grill", "eatery", "dining",
            "buffet", "fast food", "food", "sub "
        ))
    else:
        is_food = force_food
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
    if (tok("party", "guests", "guest", "pax", "covers", "occupants", "attendees", "headcount")
            and not tok("name", "id", "type")):
        return [2, 4, 3, 6, 2, 5, 8, 2, 4, 3, 7][vi % 11]
    if tok("seat", "seating", "seats") or (tok("capacity") and not tok("storage", "memory", "production")):
        return [24, 36, 18, 48, 30, 42, 20, 55, 28, 40, 33][vi % 11]
    # Inventory / production counts → large; order-line counts → small (a restaurant
    # order of "250" makes no sense, but stock-on-hand of 250 does).
    BIG_QTY_TOKS = {"stock", "inventory", "threshold", "reorder", "onhand", "on_hand",
                    "hand", "remaining", "produced", "built", "assembled", "completed",
                    "extracted", "output", "enrollment", "boardings", "impressions"}
    if toks & BIG_QTY_TOKS:
        return [100, 250, 40, 500, 75, 320, 180, 60, 420, 90, 155][vi % 11]
    SMALL_QTY_TOKS = {"qty", "quantity", "count", "units", "cases", "pieces", "boxes", "pallets"}
    if toks & SMALL_QTY_TOKS:
        return [2, 1, 3, 6, 2, 4, 1, 8, 3, 5, 2][vi % 11]
    if tok("experience", "exp", "yoe", "tenure", "seniority") or \
       (tok("yrs", "years", "yr") and not (toks & DATE_TOKS)):
        return [3, 8, 12, 5, 18, 7, 15, 2, 22, 10, 6][vi % 11]
    if tok("age"):
        return [27, 34, 41, 22, 58, 30, 45, 19, 63, 38, 51][vi % 11]
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


def _retype_from_values(columns: list[dict], rows: list[list]) -> None:
    """Align each mock column's declared type with the values actually generated.

    The name-based value generator and the name-based type guesser can disagree
    (e.g. "Yrs. Experience" is declared INTEGER but yields a text fallback), which
    makes the downstream Postgres INSERT fail. Re-deriving the type from the real
    values guarantees the column type always matches its data. Mutates `columns`.
    """
    for ci, col in enumerate(columns):
        vals = [r[ci] for r in rows if ci < len(r) and r[ci] is not None]
        if not vals:
            continue
        if all(isinstance(v, bool) for v in vals):
            col["type"] = "BOOLEAN"
        elif all(isinstance(v, int) and not isinstance(v, bool) for v in vals):
            col["type"] = "INTEGER"
        elif all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            col["type"] = "DECIMAL"
        else:
            col["type"] = "TEXT"


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
        cols = [{"name": c, "type": _infer_col_type(c)} for c in columns]
        _retype_from_values(cols, rows)
        tables.append({"name": tname, "columns": cols, "rows": rows})
    return {"tables": tables}


def _mock_value(col, row_num, vi, vocab, company_name="", row_ctx=None):
    """Return a domain value from the subindustry vocab when the column matches one,
    otherwise fall back to the semantic mock-cell generator."""
    vals = vocab.get(col)
    if vals:
        return vals[vi % len(vals)]
    if row_ctx is None:
        row_ctx = _make_row_ctx(vi, company_name)
    return _make_mock_cell(col, row_num, vi, company_name, row_ctx)


# Subindustries that always represent a food/menu business — force the food profile
# so a restaurant produces a real menu even when no company name is given.
_FOOD_SUBINDUSTRIES = {"eating_drinking_places", "food_manufacturing", "food_stores"}

_ITEM_NAME_TOKS = {"item", "product", "menu", "dish", "sandwich", "sub",
                   "entree", "meal", "goods", "merchandise"}


def _is_item_name_col(col: str) -> bool:
    toks = set(clean_column_name(col).split("_"))
    return "name" in toks and bool(toks & _ITEM_NAME_TOKS)


def _is_item_category_col(col: str) -> bool:
    """A column that names the category/type/department an item belongs to — should
    align with the item's name within the same row."""
    toks = set(clean_column_name(col).split("_"))
    if toks & {"category", "categories", "department"}:
        return True
    return bool(toks & {"type", "kind", "class", "genre"}) and bool(toks & _ITEM_NAME_TOKS)


def _table_has_item(cols: list[str]) -> bool:
    return any(_is_item_name_col(c) for c in cols)


# Incremented on every generate_data call so each button press yields different values.
_gen_call_count: int = 0


def generate_data(industry: str, model: str, messy: bool,
                  company_name: str = "", company_context: str = "",
                  num_rows: int | None = None, num_cols: int | None = None,
                  custom_columns: list[str] | None = None) -> dict:
    global _gen_call_count
    entry = _SUB_INDEX.get(industry)
    if entry is None:
        raise RuntimeError(f"Unknown subindustry: {industry!r}")
    vocab = entry["vocab"]

    if _MOCK_MODE:
        _gen_call_count += 1
        # 37 is coprime with the value-list sizes so every call shifts position.
        call_offset = (_gen_call_count * 37) % 1000
        target_rows = num_rows if num_rows is not None else 10

        if custom_columns:
            table_names = [t for t, _c in entry["tables"]]
            return _generate_mock_from_columns(
                table_names, custom_columns, target_rows, company_name, call_offset
            )

        # Build every table fresh from the subindustry's own schema, drawing
        # domain-specific values from its vocab so the data fits the industry.
        force_food = True if industry in _FOOD_SUBINDUSTRIES else None
        result_tables = []
        for tbl_idx, (tname, cols) in enumerate(entry["tables"]):
            use_cols = cols if num_cols is None else cols[:num_cols]
            # In an "item" table (one with an item/product/menu name column), the
            # category column is drawn from the same row profile as the name and
            # price so the three stay consistent (e.g. a sandwich → "Sandwiches").
            item_table = _table_has_item(use_cols)
            rows = []
            for i in range(target_rows):
                vi = call_offset + tbl_idx * target_rows + i
                row_ctx = _make_row_ctx(vi, company_name, force_food)
                row = []
                for c in use_cols:
                    if item_table and _is_item_category_col(c):
                        row.append(row_ctx["item_category"])
                    else:
                        row.append(_mock_value(c, i + 1, vi, vocab, company_name, row_ctx))
                rows.append(row)
            disp = [_messify(c) if messy else c for c in use_cols]
            coldefs = [{"name": d, "type": _infer_col_type(c)} for d, c in zip(disp, use_cols)]
            _retype_from_values(coldefs, rows)
            result_tables.append({"name": tname, "columns": coldefs, "rows": rows})
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

    prompt = _build_llm_prompt(industry, messy)
    if company_name or company_context:
        intro = f"This database is for {company_name}" if company_name else "This database is for a company"
        if company_context:
            intro += f", which {company_context.strip().rstrip('.')}"
        prompt = (f"{intro}.\n{prompt}\n"
                  "Tailor all values, names, amounts, and dates to be realistic for this specific company.")
    raw = _call_llm(model, system, prompt)
    return json.loads(_extract_json(raw))



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
    """Scale each uploaded table with SDV's GaussianCopulaSynthesizer — a lightweight
    statistical model (no PyTorch/deep-learning training), so it runs in seconds and
    fits a small container.

    SDV is imported HERE (lazily), never at module load, so PyTorch is not pulled in
    at container startup. If SDV is unavailable or cannot model a given table, that
    table falls back to the block-bootstrap engine so the request never hard-fails.
    `epochs` is accepted for API compatibility but unused (GaussianCopula doesn't train
    in epochs)."""
    try:
        from sdv.metadata import SingleTableMetadata
        from sdv.single_table import GaussianCopulaSynthesizer
    except Exception:
        # SDV missing or incompatible — scale everything with the bootstrap engine.
        return _bootstrap_fit_and_sample(tables, target_rows, epochs)

    results: dict[str, pd.DataFrame] = {}
    for tname, df in tables.items():
        # Same pre-clean as the bootstrap path: trim strings, drop all-blank columns.
        df = df.copy()
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].astype(str).str.strip()
                df[col] = df[col].replace({"nan": pd.NA, "None": pd.NA, "": pd.NA})
        df = df[[c for c in df.columns if not df[c].isna().all()]]
        if df.empty:
            continue
        df = df.reset_index(drop=True)
        try:
            metadata = SingleTableMetadata()
            metadata.detect_from_dataframe(df)
            synth = GaussianCopulaSynthesizer(metadata)
            synth.fit(df)
            out = synth.sample(num_rows=target_rows)
            out = out[[c for c in df.columns if c in out.columns]]  # original column order
            # GaussianCopula models identifier/code columns as continuous numbers
            # (e.g. a player_id sampled as 3786350). Reset them: a source-unique id
            # becomes a clean sequential primary key; a repeated id is resampled from
            # the real source values so it still looks like a valid reference.
            import numpy as _np
            _rng = _np.random.default_rng()
            for col in out.columns:
                if _is_identifier_column(col, df[col]):
                    src = df[col].dropna()
                    if len(src) == 0:
                        continue
                    if src.nunique() == len(df):
                        out[col] = list(range(1, len(out) + 1))
                    else:
                        out[col] = _rng.choice(src.to_numpy(), size=len(out), replace=True)
            results[tname] = out
        except Exception:
            # Robustness: never fail the whole request over one tricky table.
            fb = _bootstrap_fit_and_sample({tname: df}, target_rows, epochs)
            if tname in fb:
                results[tname] = fb[tname]
    return results


def _bootstrap_fit_and_sample(
    tables: dict[str, pd.DataFrame], target_rows: int, epochs: int = 50
) -> dict[str, pd.DataFrame]:
    """
    Block-bootstrap synthetic data generation (fallback engine).

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
    return {"models": MODELS, "industries": INDUSTRIES, "industry_tree": INDUSTRY_TREE,
            "file_formats": FILE_FORMATS}


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
        sources = _mock_sources(req.industry)
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
            "sources":        _mock_sources(req.industry),
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
    industry: str = Form("misc_retail"),
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


# ── Data masking ──────────────────────────────────────────────────────────────
def _read_upload_to_df(filename: str, content: bytes) -> tuple[str, "pd.DataFrame"]:
    """Read an uploaded file into a DataFrame, preserving its original column names.

    Returns (sanitized_table_stem, dataframe). Raises HTTPException on bad input.
    """
    fname = filename or "table"
    stem  = re.sub(r"[^a-zA-Z0-9_]", "_", pathlib.Path(fname).stem) or "table"
    ext   = fname.rsplit(".", 1)[-1].lower() if "." in fname else "csv"
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
    return stem, df


# ── Realistic value pools for masking ──────────────────────────────────────────
# These are deliberately large so that distinct original values map to distinct,
# realistic replacements instead of recycling a handful of names.
_MASK_FIRST = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
    "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Christopher", "Karen", "Daniel", "Nancy", "Matthew", "Lisa",
    "Anthony", "Margaret", "Mark", "Sandra", "Donald", "Ashley", "Steven", "Kimberly",
    "Paul", "Emily", "Andrew", "Donna", "Joshua", "Michelle", "Kenneth", "Carol",
    "Kevin", "Amanda", "Brian", "Dorothy", "George", "Melissa", "Edward", "Deborah",
    "Aisha", "Diego", "Mei", "Omar", "Priya", "Hiroshi", "Fatima", "Lars",
    "Yuki", "Kwame", "Ingrid", "Mateo", "Nadia", "Soren", "Leila", "Tariq",
]
_MASK_LAST = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas",
    "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White",
    "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker", "Young",
    "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
    "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Patel", "Kim", "Okafor", "Rossi", "Svensson", "Mueller", "Diallo", "Nakamura",
    "Petrov", "Haddad", "Bauer", "Costa", "Larsen", "Mwangi", "Reyes", "Foster",
]
_MASK_CITIES = [
    "New York, NY", "Los Angeles, CA", "Chicago, IL", "Houston, TX", "Phoenix, AZ",
    "Philadelphia, PA", "San Antonio, TX", "San Diego, CA", "Dallas, TX", "San Jose, CA",
    "Austin, TX", "Jacksonville, FL", "Columbus, OH", "Charlotte, NC", "Indianapolis, IN",
    "Seattle, WA", "Denver, CO", "Boston, MA", "Nashville, TN", "Portland, OR",
    "Las Vegas, NV", "Detroit, MI", "Memphis, TN", "Louisville, KY", "Milwaukee, WI",
    "Albuquerque, NM", "Tucson, AZ", "Sacramento, CA", "Kansas City, MO", "Atlanta, GA",
    "Omaha, NE", "Raleigh, NC", "Minneapolis, MN", "Tampa, FL", "Pittsburgh, PA",
]
_MASK_STREETS = [
    "Main St", "Oak Ave", "Maple Dr", "Cedar Ln", "Pine Rd", "Elm St", "Washington Ave",
    "Lake View Dr", "Park Blvd", "Sunset Ave", "Hillcrest Rd", "Riverside Dr", "Birch Ln",
    "Willow Way", "Highland Ave", "Meadow Ln", "Spruce St", "Chestnut St", "Walnut Ave",
    "Lincoln Blvd", "Jefferson St", "Madison Ave", "Franklin Rd", "Adams St", "Church St",
]
_MASK_DOMAINS = ["example.com", "mail.com", "inbox.net", "webmail.org", "email.co", "post.io"]
_MASK_COMPANY_A = [
    "Summit", "Pioneer", "Vertex", "Horizon", "Atlas", "Beacon", "Cascade", "Catalyst",
    "Evergreen", "Granite", "Ironwood", "Meridian", "Northstar", "Pinnacle", "Redwood",
    "Sterling", "Trident", "Vanguard", "Apex", "Crestline", "Highpoint", "Lakeside",
]
_MASK_COMPANY_B = ["Inc.", "LLC", "Group", "Corp.", "Partners", "Holdings",
                   "Systems", "Solutions", "Industries", "Co.", "Labs", "Logistics"]
_MASK_JOB_LEVEL = ["Junior", "Senior", "Lead", "Principal", "Staff", "Associate",
                   "Chief", "Head of", "Regional", "Assistant"]
_MASK_JOB_ROLE = [
    "Engineer", "Analyst", "Manager", "Coordinator", "Specialist", "Consultant",
    "Director", "Administrator", "Designer", "Technician", "Accountant", "Strategist",
    "Developer", "Architect", "Supervisor", "Officer", "Advisor", "Planner",
]
_MASK_DEPTS = [
    "Engineering", "Sales", "Marketing", "Finance", "Human Resources", "Operations",
    "Customer Support", "Legal", "Product", "Research", "Procurement", "Quality Assurance",
    "Logistics", "IT", "Compliance", "Facilities", "Data", "Security",
]
_MASK_COUNTRIES = [
    "United States", "Canada", "United Kingdom", "Germany", "France", "Australia",
    "Japan", "Brazil", "India", "Mexico", "Spain", "Italy", "Netherlands", "Sweden",
    "Singapore", "South Korea", "Ireland", "Norway", "Portugal", "New Zealand",
]
_MASK_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV",
    "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN",
    "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]
_MASK_GENDERS = ["Female", "Male", "Non-binary", "Prefer not to say"]
_MASK_BLOOD = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
_MASK_MARITAL = ["Single", "Married", "Divorced", "Widowed", "Separated"]
_MASK_GENERIC = [
    "Crimson", "Cobalt", "Amber", "Slate", "Verdant", "Onyx", "Ivory", "Scarlet",
    "Indigo", "Sienna", "Teal", "Maroon", "Cyan", "Magenta", "Olive", "Coral",
]
_MASK_AREA_CODES = [212, 310, 415, 312, 713, 602, 215, 619, 214, 408, 512, 305,
                    206, 303, 617, 615, 503, 702, 313, 901]


def _mask_salt(col_key: str) -> int:
    """A stable per-column offset so two same-typed columns don't generate the
    same sequence of fake values. Deterministic (no process-random hashing)."""
    return sum((i + 1) * ord(c) for i, c in enumerate(col_key)) % 1009


def _mask_fake_value(col: str, idx: int, salt: int):
    """Generate a realistic, column-appropriate fake value.

    `idx` is the 0-based ordinal of a *distinct* original value within the column,
    so consecutive distinct inputs walk through the pools and rarely repeat. `salt`
    offsets the walk per column. Detection mirrors how the column is named so the
    output fits the field (a "city" gets a city, an "age" gets an age, etc.).
    """
    n    = clean_column_name(col)
    toks = set(n.split("_"))

    def tok(*words):
        return any(w in toks for w in words)

    k = idx + salt
    F, L = len(_MASK_FIRST), len(_MASK_LAST)
    # Vary BOTH the first and last name every step while keeping (first, last)
    # pairs unique across the first F*L distinct values — avoids long runs that
    # share a surname (e.g. "...Hernandez, ...Hernandez").
    _a    = k % F
    first = _MASK_FIRST[_a]
    last  = _MASK_LAST[((k // F) + _a) % L]

    DATE_TOKS = {"date", "dt", "dob", "birth", "birthday", "born", "since", "opened",
                 "created", "hired", "joined", "start", "end", "expiry", "expiration",
                 "issued", "timestamp"}

    # ── Sensitive identifiers ────────────────────────────────────────────────────
    if tok("ssn") or (tok("social") and tok("security")) or tok("nino", "tin"):
        return f"{100 + k % 800:03d}-{10 + (idx * 7) % 89:02d}-{1000 + (idx * 37 + salt) % 8999:04d}"
    if (tok("card", "creditcard", "cc", "pan") and not tok("loyalty", "gift", "scorecard", "report")):
        return f"**** **** **** {1000 + (idx * 37 + salt) % 9000:04d}"
    if tok("account", "acct", "iban") and (tok("number", "no", "num", "id") or n in ("account", "acct")):
        return f"{10000000 + (idx * 97 + salt) % 89999999:08d}"
    if tok("passport"):
        return f"{chr(65 + salt % 26)}{10000000 + (idx * 53 + salt) % 89999999:08d}"
    if tok("license", "licence", "dl"):
        return f"{chr(65 + (idx + salt) % 26)}{1000000 + (idx * 41 + salt) % 8999999:07d}"
    if tok("username", "user", "login", "handle") and not tok("id"):
        return f"{first.lower()}.{last.lower()}{(idx + salt) % 90 + 10}"
    if tok("ip", "ipaddress") or n == "ip_address":
        return f"{10 + salt % 245}.{(idx * 7) % 256}.{(idx * 13 + salt) % 256}.{(idx * 29) % 254 + 1}"

    # ── Identifier columns kept numeric (preserve join semantics) ────────────────
    if n == "id" or n.endswith("_id") or n in ("uuid", "guid"):
        return int(10001 + idx)
    if tok("number", "num", "no", "code", "ref", "sku", "barcode", "upc", "po", "invoice") \
            and not tok("phone", "mobile", "tel", "fax", "cell"):
        prefix = "".join(w[0] for w in n.split("_") if w)[:3].upper() or "REF"
        return f"{prefix}-{100000 + (idx * 7 + salt) % 899999:06d}"

    # ── Contact ──────────────────────────────────────────────────────────────────
    if tok("email", "mail", "e_mail"):
        suffix = "" if k < F * L else str(k)
        return f"{first.lower()}.{last.lower()}{suffix}@{_MASK_DOMAINS[salt % len(_MASK_DOMAINS)]}"
    if tok("phone", "mobile", "tel", "telephone", "cell", "fax"):
        area = _MASK_AREA_CODES[(idx + salt) % len(_MASK_AREA_CODES)]
        return f"({area}) {200 + (idx * 7 + salt) % 800:03d}-{(idx * 37 + salt) % 10000:04d}"

    # ── Dates / birth dates ───────────────────────────────────────────────────────
    if (toks & DATE_TOKS) or n.endswith("_at") or n.endswith("_dt"):
        if tok("dob", "birth", "birthday", "born"):
            age   = 18 + (idx * 13 + salt) % 62
            year  = 2025 - age
        elif tok("since", "opened", "created", "hired", "joined", "start"):
            year  = 2005 + (idx + salt) % 20
        else:
            year  = 2022 + (idx + salt) % 4
        month = 1 + (idx * 5 + salt) % 12
        day   = 1 + (idx * 11 + salt) % 28
        return f"{year:04d}-{month:02d}-{day:02d}"

    # ── Person names ──────────────────────────────────────────────────────────────
    if n in ("first_name", "firstname", "fname", "given_name") or (tok("first", "given") and tok("name")):
        return first
    if n in ("last_name", "lastname", "surname", "lname", "family_name") or \
            (tok("last", "family", "sur") and tok("name")):
        return last
    if tok("middle") and tok("name", "initial"):
        return _MASK_FIRST[(_a + F // 2) % F]

    # ── Demographics ──────────────────────────────────────────────────────────────
    if tok("age") and not (toks & DATE_TOKS):
        return int(18 + (idx * 13 + salt) % 62)
    if tok("experience", "exp", "yoe", "tenure", "seniority") or \
            (tok("yrs", "years", "yr") and not (toks & DATE_TOKS)):
        return int(1 + (idx * 5 + salt) % 35)
    if tok("gender", "sex"):
        return _MASK_GENDERS[(idx + salt) % len(_MASK_GENDERS)]
    if tok("blood") and tok("type", "group"):
        return _MASK_BLOOD[(idx + salt) % len(_MASK_BLOOD)]
    if tok("marital", "marriage"):
        return _MASK_MARITAL[(idx + salt) % len(_MASK_MARITAL)]

    # ── Locations ──────────────────────────────────────────────────────────────────
    if tok("address", "street", "addr") or n.endswith("_address"):
        return f"{100 + (idx * 7 + salt) % 9800} {_MASK_STREETS[(idx + salt) % len(_MASK_STREETS)]}"
    if n == "city" or n.endswith("_city") or tok("city", "town"):
        return _MASK_CITIES[(idx + salt) % len(_MASK_CITIES)].split(",")[0]
    if tok("state", "province") and not tok("status", "statement", "estate"):
        return _MASK_STATES[(idx + salt) % len(_MASK_STATES)]
    if tok("zip", "zipcode", "postal", "postcode"):
        return f"{10000 + (idx * 61 + salt) % 89999:05d}"
    if tok("country", "nation"):
        return _MASK_COUNTRIES[(idx + salt) % len(_MASK_COUNTRIES)]

    # ── Organization / work ─────────────────────────────────────────────────────
    if tok("company", "employer", "organization", "organisation", "org", "vendor",
           "supplier", "firm", "business", "merchant", "manufacturer", "distributor"):
        a = _MASK_COMPANY_A[(idx + salt) % len(_MASK_COMPANY_A)]
        b = _MASK_COMPANY_B[(idx // len(_MASK_COMPANY_A) + salt) % len(_MASK_COMPANY_B)]
        return f"{a} {b}"
    if tok("department", "dept", "division", "team", "unit"):
        return _MASK_DEPTS[(idx + salt) % len(_MASK_DEPTS)]
    if tok("title", "role", "position", "job", "occupation", "designation"):
        lvl  = _MASK_JOB_LEVEL[(idx + salt) % len(_MASK_JOB_LEVEL)]
        role = _MASK_JOB_ROLE[(idx // len(_MASK_JOB_LEVEL) + salt) % len(_MASK_JOB_ROLE)]
        return f"{lvl} {role}"

    # ── Person-role columns → a full name (checked after org/location so that
    #    "company name" / "team name" aren't mistaken for people) ──
    PERSON_TOKS = {"name", "customer", "client", "user", "person", "guest", "member",
                   "employee", "staff", "worker", "manager", "supervisor", "operator",
                   "associate", "rep", "driver", "attendant", "agent", "contact",
                   "recipient", "owner", "holder", "patient", "doctor", "author",
                   "applicant", "tenant", "buyer", "seller", "passenger", "player"}
    if toks & PERSON_TOKS:
        return f"{first} {last}"

    # ── Money / numbers ─────────────────────────────────────────────────────────
    if tok("salary", "income", "compensation", "wage", "annual") and not tok("anniversary"):
        return int(round((35000 + (idx * 1700 + salt * 53) % 145000) / 1000.0) * 1000)
    MONEY_TOKS = {"price", "cost", "total", "amount", "fee", "charge", "revenue",
                  "subtotal", "balance", "payment", "deposit", "value"}
    if toks & MONEY_TOKS:
        return round(1.99 + (idx * 37 + salt) % 50000 / 100.0, 2)
    if tok("rate", "percent", "pct", "percentage", "ratio"):
        return round(((idx * 17 + salt) % 1000) / 10.0, 1)
    QTY_TOKS = {"qty", "quantity", "count", "units", "stock", "inventory", "amount_of",
                "level", "score", "points", "rating"}
    if toks & QTY_TOKS:
        if tok("rating", "score"):
            return round(1.0 + (idx * 7 + salt) % 40 / 10.0, 1)
        return int(1 + (idx * 17 + salt) % 1000)

    # ── Status / categorical ──────────────────────────────────────────────────────
    if n.startswith("is_") or n.startswith("has_") or n in (
            "active", "enabled", "verified", "approved", "subscribed"):
        return bool((idx + salt) % 4 != 0)

    # ── Generic but realistic fallback (never echoes the column name) ────────────
    return f"{_MASK_GENERIC[(idx + salt) % len(_MASK_GENERIC)]} {chr(65 + (idx // len(_MASK_GENERIC)) % 26)}{(idx * 7 + salt) % 900 + 100}"


def _is_na(v) -> bool:
    """True for None / NaN / NaT — values we leave untouched when masking."""
    if v is None:
        return True
    if isinstance(v, float) and v != v:   # NaN
        return True
    return v != v                          # NaT and other "not-equal-to-self" sentinels


_PERSON_NAME_TOKENS = {
    "customer", "client", "user", "person", "guest", "member", "employee", "staff",
    "worker", "manager", "supervisor", "operator", "associate", "rep", "driver",
    "attendant", "agent", "contact", "recipient", "owner", "holder", "patient",
    "doctor", "author", "applicant", "tenant", "buyer", "seller", "passenger", "player",
}


def _mask_strategy_is_identity(ck: str) -> bool:
    """True when a column must be replaced with freshly invented values (never reusing
    the originals) because it directly identifies a person or is a sensitive credential."""
    toks = set(ck.split("_"))
    def tk(*w): return any(x in toks for x in w)
    person_name = (
        ck in {"name", "full_name", "fullname", "first_name", "firstname", "fname",
               "last_name", "lastname", "lname", "surname", "middle_name", "given_name"}
        or ("name" in toks and bool(toks & _PERSON_NAME_TOKENS))
    )
    return (
        person_name
        or tk("email", "mail", "e_mail")
        or tk("phone", "mobile", "tel", "telephone", "cell", "fax")
        or tk("ssn", "passport", "iban", "username", "login", "handle", "ip")
        or tk("license", "licence")
        or tk("card", "creditcard", "cc", "pan")
        or (tk("account", "acct") and tk("number", "no", "num", "id"))
        or tk("address", "street", "addr")
    )


def _coprime_step(m: int) -> int:
    """A stride coprime with m, so stepping `i*step % m` visits every slot before
    repeating — gives well-spread, low-collision numeric variety."""
    if m <= 2:
        return 1
    for s in (int(m * 0.618) | 1, 13, 11, 7, 3):
        if 0 < s < m and math.gcd(s, m) == 1:
            return s
    return 1


def _build_mask_strategy(col: str, ck: str, values: list) -> dict:
    """Decide how to mask a column and precompute every distinct value's replacement,
    keyed by the string form of the original (so the mapping is consistent across rows
    and tables).

    Strategy, in priority order:
      • identity   → invent fresh realistic values from large pools (names, emails…)
      • numeric    → realistic numbers within the column's OWN observed range/type
                     (e.g. a shirt-number column stays small integers)
      • categorical (short labels, limited variety) → consistently re-shuffle the
                     column's own values, so replacements are always real, on-domain
                     values (e.g. a "lineup" column keeps real lineup values)
      • fallback   → name-based realistic generator
    """
    salt = _mask_salt(ck)
    # Distinct originals, preserving first-seen order and their real (typed) value.
    seen: dict[str, object] = {}
    for v in values:
        s = str(v)
        if s not in seen:
            seen[s] = v
    distinct = list(seen.items())          # [(str_key, typed_value), ...]
    n = len(distinct)
    vmap: dict[str, object] = {}

    if not _mask_strategy_is_identity(ck) and n >= 1:
        # ── Numeric? Generate within the observed range, matching int/float. ──
        nums, is_int, all_num = [], True, True
        for _, v in distinct:
            try:
                f = float(str(v).replace(",", "").strip())
            except (TypeError, ValueError):
                all_num = False
                break
            nums.append(f)
            if f != int(f):
                is_int = False
        if all_num and nums:
            mn, mx = min(nums), max(nums)
            if is_int:
                lo, hi = int(round(mn)), int(round(mx))
                span = hi - lo
                if span <= 0:
                    for s, _ in distinct:
                        vmap[s] = lo
                else:
                    step = _coprime_step(span + 1)
                    for i, (s, _) in enumerate(distinct):
                        vmap[s] = lo + ((i * step + salt) % (span + 1))
            else:
                span = mx - mn
                for i, (s, _) in enumerate(distinct):
                    frac = (i * 0.6180339887 + salt * 0.013) % 1.0
                    vmap[s] = round(mn + frac * span, 2) if span > 0 else round(mn, 2)
            return {"vmap": vmap, "kind": "numeric"}

        # ── Categorical short labels → consistent rotation of the column's own values. ──
        short = all(len(str(v)) <= 40 for _, v in distinct)
        if 2 <= n <= 200 and short:
            off   = 1 + (salt % (n - 1))    # 1..n-1 → pure rotation, no fixed points
            typed = [v for _, v in distinct]
            for i, (s, _) in enumerate(distinct):
                vmap[s] = typed[(i + off) % n]
            return {"vmap": vmap, "kind": "shuffle"}

    # ── Identity, or high-cardinality fallback → invent realistic values. ──
    for i, (s, _) in enumerate(distinct):
        vmap[s] = _mask_fake_value(col, i, salt)
    return {"vmap": vmap, "kind": "pool"}


def _mask_dataframes(tables: dict[str, "pd.DataFrame"], mask_cols: set[str],
                     company_name: str = "") -> tuple[dict[str, "pd.DataFrame"], list[str]]:
    """Replace the selected columns with realistic fake data, leaving the rest intact.

    `mask_cols` holds the column names to mask, compared case-insensitively. Each
    column is masked according to what it actually contains (see `_build_mask_strategy`):
    numbers stay numbers in range, categorical labels stay real on-domain labels, and
    identity fields get freshly invented values. Replacement is *consistent* — an
    identical original maps to the same fake value across every row and table, so
    relationships survive — and the strategy is computed from the union of values
    across all tables so a shared column masks identically everywhere.
    """
    masked_names: list[str] = []
    out: dict[str, "pd.DataFrame"] = {}

    # Pass 1: gather each masked column's full value domain across every table.
    domain: dict[str, list]  = {}
    label:  dict[str, str]   = {}
    for df in tables.values():
        for col in df.columns:
            if str(col).strip().lower() not in mask_cols:
                continue
            ck = clean_column_name(col)
            domain.setdefault(ck, [])
            label.setdefault(ck, str(col))
            domain[ck].extend(v for v in df[col].tolist() if not _is_na(v))

    # Build one strategy (with a full original→fake map) per column.
    strat = {ck: _build_mask_strategy(label[ck], ck, vals) for ck, vals in domain.items()}

    # Pass 2: apply the maps.
    for tname, df in tables.items():
        df = df.copy()
        for col in df.columns:
            if str(col).strip().lower() not in mask_cols:
                continue
            ck = clean_column_name(col)
            if str(col) not in masked_names:
                masked_names.append(str(col))
            vmap = strat[ck]["vmap"]
            df[col] = [None if _is_na(v) else vmap.get(str(v), v) for v in df[col].tolist()]
        out[tname] = df
    return out, masked_names


@app.post("/api/inspect-columns")
async def api_inspect_columns(files: list[UploadFile] = File(...)):
    """Return each uploaded table's column names so the UI can offer them for masking."""
    result: dict[str, list[str]] = {}
    for f in files:
        stem, df = _read_upload_to_df(f.filename, await f.read())
        result[stem] = [str(c) for c in df.columns]
    if not result:
        raise HTTPException(400, "No files uploaded")
    return {"tables": result}


@app.post("/api/mask")
async def api_mask(
    files: list[UploadFile] = File(...),
    mask_columns: str = Form("[]"),
    industry: str = Form("misc_retail"),
    company_name: str = Form(""),
    company_context: str = Form(""),
    model: str = Form("claude-sonnet-4-6"),
):
    """Ingest an uploaded dataset, replace the chosen sensitive columns with realistic
    fake values (kept consistent so relationships hold), and keep everything else."""
    if industry not in INDUSTRIES:
        raise HTTPException(400, f"Unknown industry: {industry!r}")
    try:
        wanted = json.loads(mask_columns) if mask_columns else []
        if not isinstance(wanted, list):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        wanted = [c.strip() for c in mask_columns.split(",") if c.strip()]
    mask_set = {str(c).strip().lower() for c in wanted}

    tables: dict[str, pd.DataFrame] = {}
    for f in files:
        stem, df = _read_upload_to_df(f.filename, await f.read())
        tables[stem] = df
    if not tables:
        raise HTTPException(400, "No files uploaded")

    masked_tables, masked_names = _mask_dataframes(tables, mask_set, company_name.strip())

    try:
        schema, schema_t, previews, col_renames = snapshot_dfs_to_duckdb(industry, masked_tables)
    except Exception as exc:
        raise HTTPException(500, str(exc))

    co_name = company_name.strip()
    if masked_names:
        summary = (
            f"Uploaded dataset ingested with {len(masked_names)} sensitive "
            f"column(s) masked ({', '.join(masked_names)}). Every other value is preserved "
            f"exactly as provided, and identical masked values map to the same realistic "
            f"replacement so relationships across rows and tables stay intact."
        )
    else:
        summary = ("Uploaded dataset ingested unchanged — no columns were selected for masking. "
                   "Select the sensitive columns to replace them with realistic fake data.")
    _result_cache[industry] = {
        "summary":         summary,
        "schema_text":     schema_t,
        "company_name":    co_name,
        "company_context": company_context.strip(),
    }
    return {
        "industry":       industry,
        "model":          model,
        "messy":          False,
        "company_name":   co_name,
        "schema":         schema,
        "tables":         previews,
        "summary":        summary,
        "column_renames": col_renames,
        "sources":        {},
        "num_rows":       None,
        "num_cols":       None,
        "custom_columns": None,
        "masked_columns": masked_names,
    }


@app.get("/")
def index():
    html_path = pathlib.Path(__file__).parent / "demo_ui.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))
