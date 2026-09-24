"""Local, persistent notes and print history. No network services are used."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    root = Path(os.environ.get("NOTE_PRINTER_DATA_DIR", "/data"))
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "note-printer.sqlite3", timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS print_log (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL,
            detail TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    return db


def list_items(table, limit=100):
    if table not in ("templates", "notes", "print_log"):
        raise ValueError("Invalid table")
    with connect() as db:
        rows = db.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def get_item(table, item_id):
    if table not in ("templates", "notes", "print_log"):
        raise ValueError("Invalid table")
    with connect() as db:
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (item_id,)).fetchone()
    return dict(row) if row else None


def save_item(table, title, payload, item_id=None):
    if table not in ("templates", "notes"):
        raise ValueError("Invalid table")
    with connect() as db:
        if item_id is None:
            cursor = db.execute(
                f"INSERT INTO {table} ({'name' if table == 'templates' else 'title'},payload,updated_at) VALUES (?,?,?)",
                (title, json.dumps(payload, ensure_ascii=False), now()),
            )
            return cursor.lastrowid
        column = "name" if table == "templates" else "title"
        result = db.execute(
            f"UPDATE {table} SET {column}=?,payload=?,updated_at=? WHERE id=?",
            (title, json.dumps(payload, ensure_ascii=False), now(), item_id),
        )
        return item_id if result.rowcount else None


def delete_item(table, item_id):
    if table not in ("templates", "notes", "print_log"):
        raise ValueError("Invalid table")
    with connect() as db:
        result = db.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))
        return bool(result.rowcount)


def record_print(note, status, detail):
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO print_log (title,payload,status,detail,created_at) VALUES (?,?,?,?,?)",
            (note.get("title") or "Notitie", json.dumps(note, ensure_ascii=False), status, detail[:500], now()),
        )
        return cursor.lastrowid
