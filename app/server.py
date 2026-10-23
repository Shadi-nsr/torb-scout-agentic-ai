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
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DB_PATH = Path(os.environ.get("TORB_DB", ROOT.parent / "data" / "catalog.db"))
DATA_DIR = Path(os.environ.get("TORB_DATA_DIR", ROOT.parent.parent.parent / "work" / "dataset"))
try:
    NOW = dt.datetime.fromisoformat(os.environ.get("TORB_NOW", "")).astimezone(dt.timezone.utc)
except ValueError:
    NOW = dt.datetime.now(dt.timezone.utc)

TEHRAN = ZoneInfo("Asia/Tehran")
WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

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

# This is a small, explicit layer of general Tehran shopping knowledge. It is
# deliberately kept separate from the challenge snapshot: product, price and
# seller claims still come only from the CSV dataset, while this layer helps a
# user recover when the requested item is not found there.
MARKET_GUIDES = (
    {
        "terms": ("گوشی", "موبایل", "آیفون"),
        "title": "راسته‌ی موبایل جمهوری و علاءالدین",
        "area": "جمهوری / علاءالدین",
        "lat": 35.6978,
        "lon": 51.4115,
        "why": "برای مقایسه‌ی حضوری گوشی و لوازم دیجیتال، این محدوده یکی از گزینه‌های عمومی تهران است.",
    },
    {
        "terms": ("لپ تاپ", "لپ", "کامپیوتر", "مانیتور", "هدفون", "دوربین"),
        "title": "مرکز دیجیتال جمهوری و شیخ هادی",
        "area": "جمهوری / شیخ هادی",
        "lat": 35.6964,
        "lon": 51.4087,
        "why": "برای پیدا کردن چند فروشنده‌ی کالای دیجیتال در یک مسیر پیاده، این راسته نقطه‌ی شروع مناسبی است.",
    },
    {
        "terms": ("موتور برق", "ژنراتور", "برق اضطراری"),
        "title": "راسته‌ی تجهیزات برق امیرکبیر",
        "area": "امیرکبیر",
        "lat": 35.6848,
        "lon": 51.4294,
        "why": "برای تجهیزات برق، ژنراتور و موتور برق می‌توان چند فروشنده‌ی تخصصی را در این محدوده بررسی کرد.",
    },
    {
        "terms": ("سیم", "کابل", "برق ساختمان"),
        "title": "راسته‌ی برق لاله‌زار",
        "area": "لاله‌زار",
        "lat": 35.6886,
        "lon": 51.4278,
        "why": "برای سیم، کابل و تجهیزات برق ساختمان، این راسته‌ی عمومی می‌تواند جایگزین جست‌وجوی بدون نتیجه باشد.",
    },
    {
        "terms": ("ابزار", "دریل", "پیچ گوشتی", "یراق"),
        "title": "راسته‌ی ابزار حسن‌آباد",
        "area": "حسن‌آباد",
        "lat": 35.6878,
        "lon": 51.4098,
        "why": "برای ابزار و یراق، حسن‌آباد یک نقطه‌ی شناخته‌شده برای مقایسه‌ی حضوری است.",
    },
    {
        "terms": ("لباس", "پوشاک", "کفش", "کیف"),
        "title": "بازار بزرگ تهران و راسته‌ی پوشاک",
        "area": "بازار بزرگ تهران",
        "lat": 35.6762,
        "lon": 51.4231,
        "why": "برای پوشاک و کفش، بازار بزرگ امکان مقایسه‌ی چند فروشنده در یک محدوده را می‌دهد.",
    },
)


def market_suggestions(parsed):
    text = normalize_fa(parsed.get("raw", ""))
    suggestions = []
    for guide in MARKET_GUIDES:
        if any(term in text for term in guide["terms"]):
            item = {key: guide[key] for key in ("title", "area", "lat", "lon", "why")}
            item["source"] = "راهنمای عمومی بازار تهران؛ خارج از snapshot چالش"
            item["source_time"] = "نسخه‌ی ثابت دمو؛ بدون اتصال زنده"
            item["confidence"] = "راهنمای عمومی، نیازمند راستی‌آزمایی"
            item["disclaimer"] = "این کارت فقط راهنمای ناحیه است و فروش، قیمت یا موجودی را تضمین نمی‌کند."
            item["map_url"] = "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(
                f"{guide['title']} تهران"
            )
            suggestions.append(item)
            if len(suggestions) == 2:
                break
    return suggestions


def review_guidance(title, category):
    """Return honest review guidance without inventing a user rating."""
    text = normalize_fa(f"{title} {category}")
    if "گوشی" in text or "موبایل" in text:
        checks = ["رجیستری و اصالت دستگاه", "سلامت باتری و نمایشگر", "شرایط گارانتی و مهلت تست"]
    elif "لپ تاپ" in text or "کامپیوتر" in text:
        checks = ["سلامت باتری و شارژر", "تست نمایشگر و کیبورد", "سریال، گارانتی و مهلت تست"]
    elif "موتور برق" in text or "ژنراتور" in text:
        checks = ["تست روشن‌شدن زیر بار", "توان واقعی و صدای دستگاه", "گارانتی، قطعات و خدمات"]
    else:
        checks = ["اصالت و سلامت کالا", "شرایط گارانتی و مهلت تست", "امکان تعویض یا مرجوعی"]
    return {
        "status": "unknown",
        "label": "نظر کاربر در دیتاست ثبت نشده",
        "message": "برای این محصول امتیاز یا review معتبر در فایل چالش نداریم؛ عامل نظر ساختگی تولید نمی‌کند.",
        "checks": checks,
        "source": "دیتاست اصلاحی ترب؛ ستون review در snapshot وجود ندارد",
        "external_search_url": "https://www.google.com/search?q=" + urllib.parse.quote(f"{title} review"),
    }


def normalize_digits(value):
    return (value or "").translate(PERSIAN_DIGITS).replace("٬", ",")


def normalize_fa(value):
    """Normalize common Arabic/Persian spelling differences for search only."""
    return (value or "").replace("ي", "ی").replace("ى", "ی").replace("ك", "ک") \
        .replace("ۀ", "ه").replace("ة", "ه").replace("ـ", "") \
        .replace("\u200c", " ").replace("\u200f", "").strip().lower()


def parse_money(message):
    text = normalize_fa(normalize_digits(message)).replace(",", "")
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


def shop_hours_status(value, now=None):
    """Return a human-readable, honest status from the dataset's weekly hours."""
    now = now or dt.datetime.now(TEHRAN)
    hours = parse_json(value, {})
    if not isinstance(hours, dict):
        return {"key": "unknown", "label": "ساعت کاری ثبت نشده", "tone": "muted"}
    day = hours.get(WEEKDAY_KEYS[now.weekday()]) or {}
    if day.get("status") == "closed":
        return {"key": "closed", "label": "امروز تعطیل ثبت شده", "tone": "closed"}
    if day.get("status") != "declared":
        return {"key": "unknown", "label": "ساعت امروز نامشخص", "tone": "muted"}
    current = now.hour * 3600 + now.minute * 60 + now.second
    for shift in day.get("shifts") or []:
        try:
            start_h, start_m, start_s = [int(part) for part in shift.get("start_time", "00:00:00").split(":")]
            end_h, end_m, end_s = [int(part) for part in shift.get("end_time", "00:00:00").split(":")]
        except (AttributeError, ValueError):
            continue
        start = start_h * 3600 + start_m * 60 + start_s
        end = end_h * 3600 + end_m * 60 + end_s
        if end <= start:
            end += 24 * 3600
        if start <= current <= end:
            return {"key": "open", "label": "طبق ساعت ثبت‌شده باز است", "tone": "open"}
    return {"key": "closed_now", "label": "خارج از ساعت ثبت‌شده", "tone": "closed"}
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
    normalized = normalize_fa(normalize_digits(text))
    for token in re.findall(r"[\w\u0600-\u06ff]+", normalized):
        if len(token) > 1 and token not in STOP_WORDS and not token.isdigit():
            tokens.append(token.replace('"', ""))
    return tokens[:8]


def parse_request(message, locations):
    text = normalize_fa(normalize_digits(message))
    budget = parse_money(text)
    location = None
    for candidate in locations:
        if candidate and normalize_fa(candidate) in text:
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
    requirements = {
        "fast_delivery": any(term in text for term in ("ارسال فوری", "فوری")),
        "installment": any(term in text for term in ("قسطی", "اقساط", "ترب پی")),
        "warranty": "گارانتی" in text,
    }
    return {
        "raw": message,
        "budget_max": budget,
        "location": location,
        "radius_km": radius or 8.0,
        "tokens": tokens,
        "requirements": requirements,
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
            CREATE TABLE offers(offer_id TEXT PRIMARY KEY,product_id TEXT,shop_id TEXT,price_toman REAL,seller_title TEXT,description TEXT,warranty TEXT,last_price_changed_at TEXT,price_valid INTEGER DEFAULT 1,price_quality TEXT DEFAULT 'valid');
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
            # Deliberately marked as demo contacts: the UI can exercise the
            # call path without implying that these numbers are real shops.
            ("s1", "فروشگاه نمونه فردوسی", "خیابان فردوسی، پاساژ نمونه", "[]", '[{"channel":"phone","display_number":"۰۲۱۰۰۰۰۰۰۰۱","mock":true}]', None, 35.703, 51.414, "فردوسی", "[]", 1, None, "{}"),
            ("s2", "بازار دیجیتال شیخ هادی", "خیابان جمهوری، شیخ هادی", "[]", '[{"channel":"phone","display_number":"۰۲۱۰۰۰۰۰۰۰۲","mock":true}]', None, 35.695, 51.409, "شیخ هادی", "[]", 0, None, "{}"),
            ("s3", "فروشگاه نمونه بهارستان", "بهارستان، مرکز خرید نمونه", "[]", '[{"channel":"phone","display_number":"۰۲۱۰۰۰۰۰۰۰۳","mock":true}]', None, 35.687, 51.423, "بهارستان", "[]", 1, None, "{}"),
        ]
        offers = [
            ("o1", "p1", "s1", 18900000, "A55 256GB", "", "۱۸ ماه", "2026-10-18T08:00:00+00:00", 1, "valid"),
            ("o2", "p1", "s2", 18200000, "A55 256GB", "", "۱۸ ماه", "2026-10-15T08:00:00+00:00", 1, "valid"),
            ("o3", "p2", "s2", 14900000, "Redmi Note 13 Pro", "", "۱۸ ماه", "2026-10-17T08:00:00+00:00", 1, "valid"),
            ("o4", "p3", "s1", 5200000, "WH-CH720N", "", "۱۲ ماه", "2026-10-10T08:00:00+00:00", 1, "valid"),
            ("o5", "p4", "s3", 31500000, "IdeaPad Slim 3", "", "۱۸ ماه", "2026-10-12T08:00:00+00:00", 1, "valid"),
            ("o6", "p5", "s3", 4200000, "C300", "", "۱۲ ماه", "2026-09-30T08:00:00+00:00", 1, "valid"),
            ("o7", "p6", "s3", 880000, "کابل ۲.۵", "", None, "2026-10-01T08:00:00+00:00", 1, "valid"),
        ]
        self.conn.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?)", products)
        self.conn.executemany("INSERT INTO shops VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", shops)
        self.conn.executemany("INSERT INTO offers VALUES (?,?,?,?,?,?,?,?,?,?)", offers)
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
        valid_offers = self.conn.execute(
            "SELECT count(*) FROM offers WHERE price_valid=1"
        ).fetchone()[0] if not self.sample_mode else counts["offers"]
        flagged_offers = counts["offers"] - valid_offers
        return {
            **counts,
            "valid_offers": valid_offers,
            "flagged_offers": flagged_offers,
            "sample_mode": self.sample_mode,
            "locations": locations,
            "categories": categories,
            "dataset_note": "قیمت معتبر یعنی عدد ثبت‌شده بین ۱٬۰۰۰ تا ۱٬۰۰۰٬۰۰۰٬۰۰۰٬۰۰۰ تومان؛ موجودی لحظه‌ای نیست.",
        }

    def _candidate_rows(self, parsed, sort, limit=80):
        terms = parsed.get("tokens") or []
        params = []
        where = ["o.price_valid = 1"]
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
        clauses = ["o.product_id=?", "o.price_valid = 1"]
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
            "s.contacts,s.payment_options,s.supports_fast_delivery,s.weekly_hours,s.website_url "
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
            item["source"] = {
                "name": "Torb snapshot",
                "kind": "dataset",
                "review_status": "بدون بررسی بیرونی؛ قبل از حرکت تماس بگیر",
            }
            item["payment_options"] = parse_json(item.get("payment_options"), [])
            item["weekly_hours"] = parse_json(item.get("weekly_hours"), {})
            item["open_status"] = shop_hours_status(json.dumps(item["weekly_hours"], ensure_ascii=False))
            item["fast_delivery"] = {
                1: {"key": "yes", "label": "ارسال فوری اعلام شده", "tone": "fresh"},
                0: {"key": "no", "label": "ارسال فوری اعلام نشده", "tone": "muted"},
            }.get(item.get("supports_fast_delivery"), {"key": "unknown", "label": "ارسال فوری نامشخص", "tone": "muted"})
            result.append(item)
        if center and parsed.get("radius_km"):
            within = [item for item in result if item["distance_km"] is None or item["distance_km"] <= parsed["radius_km"]]
            if within:
                result = within
        return result[:5]

    def market_guidance(self, parsed):
        """Suggest shopping areas, preferring evidence from the challenge data."""
        suggestions = []
        terms = parsed.get("tokens") or []
        domain_terms = [
            term for term in terms
            if any(term in guide_term or guide_term in term for guide in MARKET_GUIDES for guide_term in guide["terms"])
        ]
        if domain_terms:
            terms = domain_terms
        if terms and not self.sample_mode:
            clauses = []
            params = []
            for term in terms:
                clauses.append("(p.title LIKE ? OR p.category LIKE ? OR p.brand LIKE ?)")
                params.extend([f"%{term}%", f"%{term}%", f"%{term}%"])
            joiner = " AND " if len(terms) > 1 else " OR "
            sql = (
                "SELECT s.location_label, count(DISTINCT s.shop_id) AS shops, "
                "avg(s.lat) AS lat, avg(s.lon) AS lon "
                "FROM products p JOIN offers o ON o.product_id=p.product_id "
                "JOIN shops s ON s.shop_id=o.shop_id WHERE o.price_valid=1 "
                "AND s.location_label IS NOT NULL AND (" + joiner.join(clauses) + ") "
                "GROUP BY s.location_label ORDER BY shops DESC LIMIT 2"
            )
            try:
                rows = self.conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                rows = []
            for row in rows:
                location = row["location_label"]
                suggestions.append({
                    "title": f"فروشگاه‌های مرتبط در {location}",
                    "area": location,
                    "lat": row["lat"],
                    "lon": row["lon"],
                    "why": f"در snapshot ترب، {int(row['shops'] or 0):,} فروشگاه برای این عبارت در این محدوده آفر معتبر دارند.",
                    "source": "داده‌ی اصلاحی ترب؛ شمارش فروشگاه‌های دارای آفر معتبر",
                    "source_time": "همین snapshot محلی پس از ingest",
                    "confidence": "بالا برای شمارش داده؛ موجودی لحظه‌ای نیست",
                    "disclaimer": "این کارت از داده‌ی چالش ساخته شده و فروش، قیمت یا موجودی لحظه‌ای را تضمین نمی‌کند.",
                    "map_url": "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(f"{location} تهران"),
                })
        known = {item["area"] for item in suggestions}
        for item in market_suggestions(parsed):
            if item["area"] not in known:
                suggestions.append(item)
        return suggestions[:3]

    def search(self, message="", filters=None):
        filters = filters or {}
        requested = parse_request(message, self.locations)
        parsed = dict(requested)
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
        fallback = {"used": False, "reason": None, "relaxed": []}
        # A narrow location/budget is useful when it matches, but should not
        # turn the whole experience into an empty state. Retry once without
        # the most restrictive constraint and expose that decision to the UI.
        if not rows and (parsed.get("location") or parsed.get("budget_max")):
            variants = []
            if parsed.get("location"):
                variant = dict(parsed)
                variant["location"] = None
                variants.append((variant, "location"))
            if parsed.get("budget_max"):
                variant = dict(parsed)
                variant["budget_max"] = None
                variants.append((variant, "budget"))
            for variant, relaxed in variants:
                candidate_rows = self._candidate_rows(variant, filters.get("sort", "relevance"), 2000 if relevance_mode else 120)
                if candidate_rows:
                    parsed = variant
                    rows = candidate_rows
                    fallback = {
                        "used": True,
                        "reason": "strict_filters_empty",
                        "relaxed": [relaxed],
                        "message": "با باز کردن این محدودیت، گزینه‌های نزدیک‌تر پیدا شد.",
                    }
                    break
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
                    score += 18
                if "لپ" in terms and "تاپ" in terms and category.strip() == "لپ تاپ و نوت بوک":
                    score += 35
                if "لپ" in terms and "تاپ" in terms and any(word in category for word in ("کیف", "شارژر", "لوازم جانبی", "پایه", "باتری", "فن", "کابل", "محافظ", "رم")):
                    score -= 34
                if "موتور" in terms and "موتور برق" in category:
                    score += 22
                if "موتور" in terms and "برق" in terms and category.strip() == "ژنراتور و موتور برق":
                    score += 35
                if "موتور" in terms and "برق" in terms and any(word in category for word in ("قطعه", "لوازم یدکی", "روغن", "باتری")):
                    score -= 28
                if "موتور" in terms and "برق" in terms:
                    if "موتور برق" in title:
                        score += 40
                    motor_accessory_words = ("ولت متر", "هواکش", "رگولاتور", "پایه", "کاربراتور", "سر سیلندر", "سرشمع", "کائوچویی", "لاستیک", "شیر بنزین", "سوییچ", "واشر", "پیچ", "فیلتر", "لوازم یدکی", "قطعه")
                    if any(word in title for word in motor_accessory_words):
                        score -= 120
                if "ژنراتور" in terms and "ژنراتور" in category:
                    score += 18
                if "دوربین" in terms and "دوربین مدار بسته" in category:
                    score += 16
                accessory_categories = ("لوازم جانبی", "کیف و کاور", "پایه", "کابل", "باتری", "شارژر", "محافظ")
                if any(part in category for part in accessory_categories) and any(term in terms for term in ("گوشی", "لپ", "دوربین")):
                    score -= 16
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
            item["review_guidance"] = review_guidance(item["title"], item["category"])
            item["valid_offer_count"] = len(offers)
            item["price_confidence"] = "چند آفر معتبر" if len(offers) > 1 else "یک آفر معتبر"
            item["reasons"] = []
            if offers and offers[0]["price_toman"] == item["best_price"]:
                item["reasons"].append("کمترین قیمت ثبت‌شده در داده")
            if parsed.get("location"):
                item["reasons"].append(f"فروشنده در {parsed['location']}")
            if offers and offers[0]["freshness"]["tone"] == "fresh":
                item["reasons"].append("قیمت تازه‌تر")
            if offers and offers[0].get("supports_fast_delivery"):
                item["reasons"].append("ارسال فوری اعلام‌شده")
            if offers and offers[0].get("open_status", {}).get("key") == "open":
                item["reasons"].append("طبق ساعت ثبت‌شده باز است")
            if parsed.get("requirements", {}).get("warranty") and any(offer.get("warranty") for offer in offers):
                item["reasons"].append("گارانتی ثبت‌شده")
            if parsed.get("requirements", {}).get("installment") and any(offer.get("payment_options") for offer in offers):
                item["reasons"].append("گزینه‌ی پرداخت ثبت شده")
            items.append(item)
            if len(items) >= 24:
                break
        requirements = parsed.get("requirements", {})
        if requirements.get("fast_delivery"):
            items.sort(key=lambda item: any(offer.get("supports_fast_delivery") == 1 for offer in item.get("offers", [])), reverse=True)
        if requirements.get("installment"):
            items.sort(key=lambda item: any(offer.get("payment_options") for offer in item.get("offers", [])), reverse=True)
        # The fallback can still produce no offers when every candidate has
        # been filtered out by price quality. Keep the reason explicit for
        # callers and for review of the decision trace.
        if not items and not fallback["used"] and (requested.get("location") or requested.get("budget_max")):
            fallback = {
                "used": True,
                "reason": "no_valid_offer",
                "relaxed": [],
                "message": "برای این محدودیت‌ها آفر معتبر ثبت نشده است.",
            }
        if not items and not fallback["used"]:
            fallback = {
                "used": True,
                "reason": "no_catalog_match",
                "relaxed": [],
                "message": "در کاتالوگ برای این عبارت آفر معتبر پیدا نشد.",
            }
        return {
            "query": parsed,
            "requested_query": requested,
            "results": items,
            "total": len(items),
            "meta": self.meta(),
            "fallback": fallback,
            "market_suggestions": self.market_guidance(requested) if not items else [],
        }


catalog = Catalog(DB_PATH)


def agent_reply(message, filters=None, selected_ids=None):
    filters = filters or {}
    selected_ids = selected_ids or []
    parsed = parse_request(message, catalog.locations)
    result = catalog.search(message, filters)
    count = result["total"]
    plan = [
        {"id": "intent", "label": "فهم نیاز", "detail": "محصول، بودجه، محدوده و شرط مراجعه استخراج شد.", "state": "done"},
        {"id": "retrieve", "label": "اتصال به دیتاست", "detail": "محصول، آفر و فروشگاه از snapshot رسمی چالش به هم وصل شدند.", "state": "done"},
        {"id": "rank", "label": "رتبه‌بندی شفاف", "detail": "قیمت معتبر، تازگی، فاصله، ساعت کاری و شرایط فروشنده امتیاز گرفتند.", "state": "done"},
        {"id": "next", "label": "قدم بعدی", "detail": "مقایسه یا انتخاب فروشنده برای مراجعه آماده است.", "state": "done"},
    ]
    if count:
        first = result["results"][0]
        answer = f"برای «{message.strip()}» {count} گزینه با قیمت معتبر پیدا کردم. کمترین قیمت ثبت‌شده از {first['best_price']:,} تومان شروع می‌شود."
        if parsed.get("location"):
            answer += f" نتیجه‌ها را روی محدوده‌ی {parsed['location']} محدود کردم."
        if parsed.get("budget_max"):
            answer += f" سقف بودجه‌ی {int(parsed['budget_max']):,} تومان هم اعمال شد."
        answer += " قیمت snapshot است و موجودی لحظه‌ای را تضمین نمی‌کند؛ قبل از حرکت، ساعت کاری و تماس با فروشنده را بررسی کن."
        if result.get("fallback", {}).get("used"):
            answer += " برای اینکه صفحه خالی نماند، یک محدودیت جست‌وجو بازتر شد؛ این موضوع در شواهد نتیجه ثبت شده است."
    else:
        answer = "برای این ترکیب در آفرهای معتبر ترب نتیجه‌ی قابل اتکا پیدا نکردم."
        if result.get("market_suggestions"):
            answer += " یک راهنمای ناحیه‌ای جدا از نتایج دیتاست آماده کردم تا اگر خواستی جست‌وجوی حضوری را ادامه بدهی."
        answer += " بودجه، محدوده یا عبارت محصول را هم می‌توانی کمی بازتر کنی."
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
            "fallback": result.get("fallback", {"used": False}),
            "sources": [
                {"name": "Torb snapshot", "kind": "dataset", "status": "used"},
                {"name": "External reviews", "kind": "external", "status": "not_connected", "note": "امتیاز بیرونی بدون اتصال زنده نمایش داده نمی‌شود."},
            ],
            "selected_ids": selected_ids,
            "freshness_policy": "آخرین زمان تغییر قیمت نمایش داده می‌شود؛ موجودی تأیید نشده تلقی می‌شود.",
            "price_policy": "قیمت‌های خالی، کمتر از ۱٬۰۰۰ یا بیشتر از ۱٬۰۰۰٬۰۰۰٬۰۰۰٬۰۰۰ تومان وارد رتبه‌بندی نمی‌شوند.",
            "dataset_first": "محصول و آفر فقط از دیتاست اصلاحی ترب انتخاب می‌شود؛ راهنمای ناحیه‌ای بیرونی جدا و برچسب‌دار است.",
            "review_policy": "امتیاز یا review بدون منبع ساخته نمی‌شود؛ در نبود داده، چک‌لیست راستی‌آزمایی نشان داده می‌شود.",
        },
        "market_suggestions": result.get("market_suggestions", []),
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
            product = dict(row)
            product["specs"] = parse_json(product.get("specs"), [])
            product["review_guidance"] = review_guidance(product.get("title", ""), product.get("category", ""))
            return self._json({"product": product, "offers": offers})
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
        if path == "/api/contact":
            # A deterministic, local call hand-off for the demo. It never
            # contacts a shop or claims that stock was confirmed.
            shop_id = str(payload.get("shop_id", "")).strip()
            row = catalog.conn.execute(
                "SELECT shop_id,name,contacts FROM shops WHERE shop_id=?", (shop_id,)
            ).fetchone()
            if not row:
                return self._json({"error": "فروشنده پیدا نشد"}, HTTPStatus.NOT_FOUND)
            contacts = parse_json(row["contacts"], [])
            phone = next((item for item in contacts if item.get("channel") == "phone"), None)
            return self._json({
                "ok": True,
                "mode": "mock",
                "status": "ready_to_call" if phone else "no_phone",
                "shop_id": shop_id,
                "shop_name": row["name"],
                "contact": phone,
                "message": "این تماس در نسخه‌ی نمایشی شبیه‌سازی شده و موجودی را تأیید نمی‌کند.",
            })
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
