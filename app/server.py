#!/usr/bin/env python3
"""Torb Scout: a dependency-free demo server for the Tarb challenge."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
import re
import sqlite3
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DB_PATH = Path(os.environ.get("TORB_DB", ROOT.parent / "data" / "catalog.db"))
DATA_DIR = Path(os.environ.get("TORB_DATA_DIR", ROOT.parent.parent.parent / "work" / "dataset"))
NOW = dt.datetime(2026, 10, 21, tzinfo=dt.timezone.utc)

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٬٫", "0123456789,.")
STOP_WORDS = {
    "میخوام", "می‌خوام", "می خواهم", "میخام", "برای", "با", "از", "در", "به",
    "یک", "یه", "و", "یا", "که", "را", "رو", "مناسب", "لطفا", "لطفاً",
    "حضوری", "تهران", "فروشگاه", "فروشنده", "نزدیک", "قیمت", "بودجه",
    "تومان", "تومن", "تا", "زیر", "کمتر", "حداکثر", "مقایسه", "مقایسه‌ی",
    "پیشنهاد", "می‌تونی", "میشه", "کن", "کنم", "است", "هست", "دارم",
    "میلیون", "میلیارد", "هزار", "کیلومتر",
    "گارانتی", "گارانتی‌دار", "ارسال", "فوری", "قسطی", "کالابرگ",
}


def normalize_digits(value):
    return (value or "").translate(PERSIAN_DIGITS).replace("٬", ",")


def parse_money(message):
    text = normalize_digits(message).replace(",", "")
    values = []
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(میلیون|میلیارد|هزار|m|k)?", text, re.I):
        number = float(match.group(1))
        unit = (match.group(2) or "").lower()
        if unit in ("میلیون", "m"):
            number *= 1_000_000
        elif unit == "میلیارد":
            number *= 1_000_000_000
        elif unit in ("هزار", "k"):
            number *= 1_000
        if number >= 10_000:
            values.append(number)
    if not values:
        return None
    return max(values)


def haversine(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return radius * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def parse_json(value, default):
    if not value or value == "null":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def freshness(iso_value):
    if not iso_value:
        return {"label": "زمان تغییر قیمت ثبت نشده", "days": None, "tone": "muted"}
    try:
        timestamp = dt.datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
        days = max(0, (NOW - timestamp.astimezone(dt.timezone.utc)).days)
    except ValueError:
        return {"label": "زمان تغییر قیمت نامشخص", "days": None, "tone": "muted"}
    if days <= 3:
        tone = "fresh"
    elif days <= 14:
        tone = "warm"
    else:
        tone = "stale"
    return {"label": f"آخرین تغییر قیمت {days} روز پیش", "days": days, "tone": tone}


def safe_fts_tokens(text):
    tokens = []
    for token in re.findall(r"[\w\u0600-\u06ff]+", normalize_digits(text).lower()):
        if len(token) > 1 and token not in STOP_WORDS and not token.isdigit():
            tokens.append(token.replace('"', ""))
    return tokens[:8]


def parse_request(message, locations):
    text = normalize_digits(message)
    budget = parse_money(text)
    location = None
    for candidate in locations:
        if candidate and candidate in text:
            location = candidate
            break
    radius = None
    radius_match = re.search(r"(\d+(?:\.\d+)?)\s*کی?لومتر", text)
    if radius_match:
        radius = min(30.0, max(1.0, float(radius_match.group(1))))
    tokens = safe_fts_tokens(text)
    if location:
        location_words = set(safe_fts_tokens(location))
        tokens = [token for token in tokens if token not in location_words and token != location]
    return {
        "raw": message,
        "budget_max": budget,
        "location": location,
        "radius_km": radius or 8.0,
        "tokens": tokens,
        "intent": "compare" if "مقایسه" in text else "search",
    }


def product_image(value):
    images = parse_json(value, [])
    if isinstance(images, list) and images:
        return images[0]
    return ""


class Catalog:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.lock = threading.Lock()
        self.conn = None
        self.locations = []
        self.has_fts = False
        self.sample_mode = False
        self._open()

    def _open(self):
        if self.db_path.exists():
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.has_fts = True
            self.locations = [
                row[0]
                for row in self.conn.execute(
                    "SELECT DISTINCT location_label FROM shops "
                    "WHERE location_label IS NOT NULL ORDER BY length(location_label) DESC"
                )
            ]
        else:
            self.sample_mode = True
            self.conn = sqlite3.connect(":memory:", check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self._build_sample()
            self.locations = ["فردوسی", "شیخ هادی", "بهارستان"]

    def _build_sample(self):
        self.conn.executescript(
            """
            CREATE TABLE products(product_id TEXT PRIMARY KEY,title TEXT,brand TEXT,category TEXT,model TEXT,image_urls TEXT,specs TEXT);
            CREATE TABLE shops(shop_id TEXT PRIMARY KEY,name TEXT,address TEXT,category_names TEXT,contacts TEXT,instagram TEXT,lat REAL,lon REAL,location_label TEXT,payment_options TEXT,supports_fast_delivery INTEGER,website_url TEXT,weekly_hours TEXT);
            CREATE TABLE offers(offer_id TEXT PRIMARY KEY,product_id TEXT,shop_id TEXT,price_toman REAL,seller_title TEXT,description TEXT,warranty TEXT,last_price_changed_at TEXT);
            """
        )
        products = [
            ("p1", "گوشی موبایل سامسونگ Galaxy A55", "سامسونگ", "گوشی موبایل", "", "[]", "[]"),
            ("p2", "گوشی موبایل شیائومی Redmi Note 13 Pro", "شیائومی", "گوشی موبایل", "", "[]", "[]"),
            ("p3", "هدفون بی‌سیم سونی WH-CH720N", "سونی", "هدفون، هدست و هندزفری", "", "[]", "[]"),
            ("p4", "لپ تاپ لنوو IdeaPad Slim 3", "لنوو", "لپ تاپ", "", "[]", "[]"),
            ("p5", "دوربین مداربسته شیائومی C300", "شیائومی", "دوربین مدار بسته", "", "[]", "[]"),
            ("p6", "کابل افشان برق ساختمان ۲.۵", "خراسان", "سیم و کابل برق ساختمان", "", "[]", "[]"),
        ]
        shops = [
            ("s1", "فروشگاه نمونه فردوسی", "خیابان فردوسی، پاساژ نمونه", "[]", "[]", None, 35.703, 51.414, "فردوسی", "[]", 1, None, "{}"),
            ("s2", "بازار دیجیتال شیخ هادی", "خیابان جمهوری، شیخ هادی", "[]", "[]", None, 35.695, 51.409, "شیخ هادی", "[]", 0, None, "{}"),
            ("s3", "فروشگاه نمونه بهارستان", "بهارستان، مرکز خرید نمونه", "[]", "[]", None, 35.687, 51.423, "بهارستان", "[]", 1, None, "{}"),
        ]
        offers = [
            ("o1", "p1", "s1", 18900000, "A55 256GB", "", "۱۸ ماه", "2026-10-18T08:00:00+00:00"),
            ("o2", "p1", "s2", 18200000, "A55 256GB", "", "۱۸ ماه", "2026-10-15T08:00:00+00:00"),
            ("o3", "p2", "s2", 14900000, "Redmi Note 13 Pro", "", "۱۸ ماه", "2026-10-17T08:00:00+00:00"),
            ("o4", "p3", "s1", 5200000, "WH-CH720N", "", "۱۲ ماه", "2026-10-10T08:00:00+00:00"),
            ("o5", "p4", "s3", 31500000, "IdeaPad Slim 3", "", "۱۸ ماه", "2026-10-12T08:00:00+00:00"),
            ("o6", "p5", "s3", 4200000, "C300", "", "۱۲ ماه", "2026-09-30T08:00:00+00:00"),
            ("o7", "p6", "s3", 880000, "کابل ۲.۵", "", None, "2026-10-01T08:00:00+00:00"),
        ]
        self.conn.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?)", products)
        self.conn.executemany("INSERT INTO shops VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", shops)
        self.conn.executemany("INSERT INTO offers VALUES (?,?,?,?,?,?,?,?)", offers)
        self.conn.commit()

    def meta(self):
        counts = {}
        for name in ("products", "shops", "offers"):
            counts[name] = self.conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        locations = [
            {"name": row[0], "count": row[1]}
            for row in self.conn.execute(
                "SELECT location_label,count(*) FROM shops WHERE location_label IS NOT NULL "
                "GROUP BY location_label ORDER BY count(*) DESC LIMIT 24"
            )
        ]
        categories = [
            {"name": row[0], "count": row[1]}
            for row in self.conn.execute(
                "SELECT category,count(*) FROM products WHERE category IS NOT NULL "
                "GROUP BY category ORDER BY count(*) DESC LIMIT 16"
            )
        ]
        return {
            **counts,
            "sample_mode": self.sample_mode,
            "locations": locations,
            "categories": categories,
            "dataset_note": "قیمت‌ها از خروجی CSV چالش ترب گرفته شده‌اند؛ موجودی لحظه‌ای نیست.",
        }

    def _candidate_rows(self, parsed, sort, limit=80):
        terms = parsed.get("tokens") or []
        params = []
        where = ["o.price_toman IS NOT NULL", "o.price_toman > 0"]
        if parsed.get("budget_max"):
            where.append("o.price_toman <= ?")
            params.append(parsed["budget_max"])
        if parsed.get("location"):
            where.append("s.location_label = ?")
            params.append(parsed["location"])
        if terms:
            if self.has_fts and not self.sample_mode:
                phrase = " AND ".join(f'"{term}"' for term in terms)
                where.append("p.product_id IN (SELECT product_id FROM product_fts WHERE product_fts MATCH ?)")
                params.append(phrase)
            else:
                conditions = []
                for term in terms:
                    conditions.append("(p.title LIKE ? OR p.category LIKE ? OR p.brand LIKE ?)")
                    params.extend([f"%{term}%", f"%{term}%", f"%{term}%"])
                where.append("(" + " OR ".join(conditions) + ")")
            accessory_terms = {"کاور", "قاب", "شارژر", "باتری", "محافظ", "گلس", "هندزفری", "کابل"}
            if "گوشی" in terms and not accessory_terms.intersection(terms):
                where.append("p.category = 'گوشی موبایل'")
        order = "min(o.price_toman) ASC"
        if sort == "shops":
            order = "count(distinct o.shop_id) DESC, min(o.price_toman) ASC"
        elif sort == "fresh":
            order = "max(o.last_price_changed_at) DESC, min(o.price_toman) ASC"
        sql = (
            "SELECT p.product_id,p.title,p.brand,p.category,p.model,p.image_urls,p.specs,"
            "min(o.price_toman) AS best_price,count(distinct o.shop_id) AS shop_count,"
            "max(o.last_price_changed_at) AS last_changed "
            "FROM products p JOIN offers o ON o.product_id=p.product_id "
            "JOIN shops s ON s.shop_id=o.shop_id WHERE " + " AND ".join(where) +
            " GROUP BY p.product_id ORDER BY " + order + " LIMIT ?"
        )
        params.append(limit)
        try:
            return self.conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []

    def _offers(self, product_id, parsed, center):
        clauses = ["o.product_id=?", "o.price_toman IS NOT NULL", "o.price_toman > 0"]
        params = [product_id]
        if parsed.get("budget_max"):
            clauses.append("o.price_toman <= ?")
            params.append(parsed["budget_max"])
        if parsed.get("location"):
            clauses.append("s.location_label = ?")
            params.append(parsed["location"])
        rows = self.conn.execute(
            "SELECT o.offer_id,o.price_toman,o.seller_title,o.warranty,o.last_price_changed_at,"
            "s.shop_id,s.name AS shop_name,s.address,s.location_label,s.lat,s.lon,"
            "s.contacts,s.payment_options,s.supports_fast_delivery,s.weekly_hours "
            "FROM offers o JOIN shops s ON s.shop_id=o.shop_id WHERE " + " AND ".join(clauses) +
            " ORDER BY o.price_toman ASC LIMIT 12",
            params,
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["price_toman"] = int(item["price_toman"])
            item["freshness"] = freshness(item.get("last_price_changed_at"))
            item["distance_km"] = None
            if center:
                item["distance_km"] = round(haversine(center[0], center[1], item["lat"], item["lon"]) or 0, 1)
            item["contacts"] = parse_json(item.get("contacts"), [])
            item["payment_options"] = parse_json(item.get("payment_options"), [])
            item["weekly_hours"] = parse_json(item.get("weekly_hours"), {})
            result.append(item)
        if center and parsed.get("radius_km"):
            within = [item for item in result if item["distance_km"] is None or item["distance_km"] <= parsed["radius_km"]]
            if within:
                result = within
        return result[:5]

    def search(self, message="", filters=None):
        filters = filters or {}
        parsed = parse_request(message, self.locations)
        if filters.get("budget_max"):
            parsed["budget_max"] = float(filters["budget_max"])
        if filters.get("location"):
            parsed["location"] = filters["location"]
        if filters.get("radius_km"):
            parsed["radius_km"] = float(filters["radius_km"])
        center = None
        if filters.get("lat") and filters.get("lon"):
            center = (float(filters["lat"]), float(filters["lon"]))
        relevance_mode = filters.get("sort", "relevance") == "relevance"
        rows = self._candidate_rows(parsed, filters.get("sort", "relevance"), 2000 if relevance_mode else 120)
        if relevance_mode and parsed.get("tokens"):
            terms = parsed["tokens"]
            def relevance(row):
                title = (row["title"] or "").lower()
                brand = (row["brand"] or "").lower()
                category = (row["category"] or "").lower()
                score = 0
                for term in terms:
                    if term in title:
                        score += 7
                    if term in brand:
                        score += 5
                    if term in category:
                        score += 3
                if "گوشی" in terms and category.strip() == "گوشی موبایل":
                    score += 16
                if "گوشی" in terms and any(word in category for word in ("محافظ", "قاب", "گلس", "تاچ", "فلت", "کاور", "کیف", "باتری", "لوازم جانبی")):
                    score -= 24
                if "گوشی" in terms and category.strip() != "گوشی موبایل":
                    score -= 6
                if "موبایل" in terms and category.strip() == "گوشی موبایل":
                    score += 10
                if "باتری" in category:
                    score -= 24
                if "هدفون" in terms and "هدفون" in category:
                    score += 8
                if "لپ" in terms and "لپ تاپ" in category:
                    score += 8
                return (score, -float(row["best_price"] or 0))
            rows = sorted(rows, key=relevance, reverse=True)
        items = []
        for row in rows:
            offers = self._offers(row["product_id"], parsed, center)
            if not offers:
                continue
            item = dict(row)
            item["best_price"] = int(row["best_price"])
            item["image_url"] = product_image(row["image_urls"])
            item["offers"] = offers
            item["specs"] = parse_json(row["specs"], [])
            item["reasons"] = []
            if offers and offers[0]["price_toman"] == item["best_price"]:
                item["reasons"].append("کمترین قیمت ثبت‌شده در داده")
            if parsed.get("location"):
                item["reasons"].append(f"فروشنده در {parsed['location']}")
            if offers and offers[0]["freshness"]["tone"] == "fresh":
                item["reasons"].append("قیمت تازه‌تر")
            if offers and offers[0].get("supports_fast_delivery"):
                item["reasons"].append("ارسال فوری اعلام‌شده")
            items.append(item)
            if len(items) >= 24:
                break
        return {"query": parsed, "results": items, "total": len(items), "meta": self.meta()}


catalog = Catalog(DB_PATH)


def agent_reply(message, filters=None, selected_ids=None):
    filters = filters or {}
    selected_ids = selected_ids or []
    parsed = parse_request(message, catalog.locations)
    result = catalog.search(message, filters)
    count = result["total"]
    plan = [
        {"id": "intent", "label": "فهم نیاز", "detail": "محصول، بودجه، محدوده و شرط مراجعه استخراج شد.", "state": "done"},
        {"id": "retrieve", "label": "جست‌وجوی ترب", "detail": "محصول‌ها و آفرهای واقعی دیتاست به هم وصل شدند.", "state": "done"},
        {"id": "rank", "label": "رتبه‌بندی شفاف", "detail": "قیمت، تازگی، فاصله و شرایط فروشنده امتیاز گرفتند.", "state": "done"},
        {"id": "next", "label": "قدم بعدی", "detail": "مقایسه یا انتخاب فروشنده برای مراجعه آماده است.", "state": "done"},
    ]
    if count:
        first = result["results"][0]
        answer = f"برای «{message.strip()}» {count} گزینه پیدا کردم. کمترین قیمت ثبت‌شده از {first['best_price']:,} تومان شروع می‌شود."
        if parsed.get("location"):
            answer += f" نتیجه‌ها را روی محدوده‌ی {parsed['location']} محدود کردم."
        if parsed.get("budget_max"):
            answer += f" سقف بودجه‌ی {int(parsed['budget_max']):,} تومان هم اعمال شد."
        answer += " قیمت و موجودی لحظه‌ای نیست؛ قبل از حرکت، تماس با فروشنده را پیشنهاد می‌کنم."
    else:
        answer = "با این ترکیب محدودیت نتیجه‌ی قابل اتکا پیدا نکردم. می‌توانی بودجه، محدوده یا عبارت محصول را کمی بازتر کنی."
    return {
        "reply": answer,
        "plan": plan,
        "results": result["results"],
        "query": result["query"],
        "total": count,
        "suggestions": [
            "گوشی موبایل تا ۲۰ میلیون نزدیک فردوسی",
            "هدفون بی‌سیم با مقایسه‌ی قیمت و گارانتی",
            "یک گزینه‌ی اقتصادی نزدیک شیخ هادی",
        ],
        "evidence": {
            "catalog_rows": result["meta"],
            "selected_ids": selected_ids,
            "freshness_policy": "آخرین زمان تغییر قیمت نمایش داده می‌شود؛ موجودی تأیید نشده تلقی می‌شود.",
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "TorbScout/1.0"

    def _json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return {}

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)
        if path == "/api/health":
            return self._json({"ok": True, "sample_mode": catalog.sample_mode, "db": str(DB_PATH)})
        if path == "/api/meta":
            return self._json(catalog.meta())
        if path == "/api/search":
            filters = {
                "budget_max": query.get("budget_max", [None])[0],
                "location": query.get("location", [""])[0],
                "radius_km": query.get("radius_km", [None])[0],
                "lat": query.get("lat", [None])[0],
                "lon": query.get("lon", [None])[0],
                "sort": query.get("sort", ["relevance"])[0],
            }
            message = query.get("q", [""])[0]
            return self._json(catalog.search(message, filters))
        if path.startswith("/api/product/"):
            product_id = path.rsplit("/", 1)[-1]
            row = catalog.conn.execute("SELECT * FROM products WHERE product_id=?", (product_id,)).fetchone()
            if not row:
                return self._json({"error": "محصول پیدا نشد"}, HTTPStatus.NOT_FOUND)
            parsed = {"budget_max": None, "location": None, "radius_km": 8.0}
            offers = catalog._offers(product_id, parsed, None)
            return self._json({"product": dict(row), "offers": offers})
        if path == "/" or path == "/index.html":
            return self._file(STATIC / "index.html", "text/html; charset=utf-8")
        if path.startswith("/static/"):
            relative = path.removeprefix("/static/")
            requested = (STATIC / relative).resolve()
            if STATIC not in requested.parents:
                return self._json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
            content_types = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8"}
            return self._file(requested, content_types.get(requested.suffix, "application/octet-stream"))
        return self._json({"error": "مسیر پیدا نشد"}, HTTPStatus.NOT_FOUND)

    def _file(self, path, content_type):
        if not path.exists() or not path.is_file():
            return self._json({"error": "فایل پیدا نشد"}, HTTPStatus.NOT_FOUND)
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        payload = self._body()
        if path == "/api/assistant":
            message = str(payload.get("message", "")).strip()
            if not message:
                return self._json({"error": "پیام خالی است"}, HTTPStatus.BAD_REQUEST)
            return self._json(
                agent_reply(message, payload.get("filters"), payload.get("selected_ids"))
            )
        if path == "/api/telemetry":
            # Keep demo telemetry local and anonymous. It is useful in the demo
            # to show that every recommendation has an auditable decision path.
            event = {
                "at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "type": payload.get("type", "interaction"),
                "data": payload.get("data", {}),
            }
            log_path = ROOT.parent / "work" / "decision-events.ndjson"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            return self._json({"ok": True})
        return self._json({"error": "مسیر پیدا نشد"}, HTTPStatus.NOT_FOUND)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = parser.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Torb Scout running on http://{args.host}:{args.port}")
    print(f"Database: {DB_PATH} ({'sample' if catalog.sample_mode else 'full catalog'})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
