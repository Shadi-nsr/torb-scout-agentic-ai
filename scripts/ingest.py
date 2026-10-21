#!/usr/bin/env python3
"""Build a searchable SQLite catalog from the Starcoach Tarb CSV export.

The challenge dataset is intentionally kept outside the repository because it is
large and may be updated. Run this script with --data-dir pointing at the
unzipped CSV directory.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path
from typing import Optional


def null_to_none(value: Optional[str]):
    if value is None or value == "" or value == "null":
        return None
    return value


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
        PRAGMA temp_store=MEMORY;
        DROP TABLE IF EXISTS products;
        DROP TABLE IF EXISTS shops;
        DROP TABLE IF EXISTS offers;
        DROP TABLE IF EXISTS product_fts;
        DROP TABLE IF EXISTS meta;

        CREATE TABLE products (
          product_id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          brand TEXT,
          category TEXT,
          model TEXT,
          image_urls TEXT,
          specs TEXT
        );
        CREATE TABLE shops (
          shop_id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          address TEXT,
          category_names TEXT,
          contacts TEXT,
          instagram TEXT,
          lat REAL,
          lon REAL,
          location_label TEXT,
          payment_options TEXT,
          supports_fast_delivery INTEGER,
          website_url TEXT,
          weekly_hours TEXT
        );
        CREATE TABLE offers (
          offer_id TEXT PRIMARY KEY,
          product_id TEXT NOT NULL,
          shop_id TEXT NOT NULL,
          price_toman REAL,
          seller_title TEXT,
          description TEXT,
          warranty TEXT,
          last_price_changed_at TEXT
        );
        CREATE INDEX idx_offers_product ON offers(product_id);
        CREATE INDEX idx_offers_shop ON offers(shop_id);
        CREATE INDEX idx_offers_price ON offers(price_toman);
        CREATE INDEX idx_shops_location ON shops(location_label);
        CREATE INDEX idx_products_category ON products(category);

        CREATE VIRTUAL TABLE product_fts USING fts5(
          product_id UNINDEXED,
          title,
          brand,
          category,
          model,
          tokenize='unicode61 remove_diacritics 2'
        );
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )


def load_csv(conn: sqlite3.Connection, path: Path, table: str, columns: list[str], transform):
    batch = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            batch.append(transform(row))
            if len(batch) >= 2000:
                placeholders = ",".join("?" for _ in columns)
                conn.executemany(
                    f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
                    batch,
                )
                batch.clear()
        if batch:
            placeholders = ",".join("?" for _ in columns)
            conn.executemany(
                f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
                batch,
            )


def build(data_dir: Path, db_path: Path) -> None:
    required = [data_dir / name for name in ("products.csv", "shops.csv", "offers.csv")]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("Missing CSV files: " + ", ".join(missing))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        create_schema(conn)
        load_csv(
            conn,
            data_dir / "products.csv",
            "products",
            ["product_id", "title", "brand", "category", "model", "image_urls", "specs"],
            lambda r: (
                r["product_id"],
                r.get("persian_title") or r.get("title") or "",
                null_to_none(r.get("brand_name")),
                null_to_none(r.get("category_name")),
                null_to_none(r.get("model")),
                null_to_none(r.get("image_urls")),
                null_to_none(r.get("specs")),
            ),
        )
        conn.execute(
            "INSERT INTO product_fts(product_id,title,brand,category,model) "
            "SELECT product_id,title,coalesce(brand,''),coalesce(category,''),coalesce(model,'') FROM products"
        )
        load_csv(
            conn,
            data_dir / "shops.csv",
            "shops",
            [
                "shop_id",
                "name",
                "address",
                "category_names",
                "contacts",
                "instagram",
                "lat",
                "lon",
                "location_label",
                "payment_options",
                "supports_fast_delivery",
                "website_url",
                "weekly_hours",
            ],
            lambda r: (
                r["shop_id"],
                r.get("name") or "فروشگاه بدون نام",
                null_to_none(r.get("address")),
                null_to_none(r.get("category_names")),
                null_to_none(r.get("contacts")),
                null_to_none(r.get("instagram")),
                float(r["lat"]) if r.get("lat") not in (None, "", "null") else None,
                float(r["lon"]) if r.get("lon") not in (None, "", "null") else None,
                null_to_none(r.get("location_label")),
                null_to_none(r.get("payment_options")),
                1 if r.get("supports_fast_delivery") == "true" else 0,
                null_to_none(r.get("website_url")),
                null_to_none(r.get("weekly_hours")),
            ),
        )
        load_csv(
            conn,
            data_dir / "offers.csv",
            "offers",
            [
                "offer_id",
                "product_id",
                "shop_id",
                "price_toman",
                "seller_title",
                "description",
                "warranty",
                "last_price_changed_at",
            ],
            lambda r: (
                r["offer_id"],
                r["product_id"],
                r["shop_id"],
                float(r["price_toman"]) if r.get("price_toman") not in (None, "", "null") else None,
                null_to_none(r.get("seller_title")),
                null_to_none(r.get("description")),
                null_to_none(r.get("warranty")),
                null_to_none(r.get("last_price_changed_at")),
            ),
        )
        counts = {
            "products": conn.execute("SELECT count(*) FROM products").fetchone()[0],
            "shops": conn.execute("SELECT count(*) FROM shops").fetchone()[0],
            "offers": conn.execute("SELECT count(*) FROM offers").fetchone()[0],
        }
        for key, value in counts.items():
            conn.execute("INSERT INTO meta(key,value) VALUES (?,?)", (key, str(value)))
        conn.execute(
            "INSERT INTO meta(key,value) VALUES (?,?)",
            ("dataset_note", "Starcoach v16 cap300 CSV export"),
        )
        conn.commit()
        print(json.dumps({"db": str(db_path), **counts}, ensure_ascii=False))
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--db", default=Path("data/catalog.db"), type=Path)
    args = parser.parse_args()
    build(args.data_dir, args.db)


if __name__ == "__main__":
    main()
