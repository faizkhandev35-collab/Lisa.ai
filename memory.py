import os
import time
import sqlite3

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_PG = bool(DATABASE_URL)
DB_FILE = "memory.db"

if USE_PG:
    import psycopg
    from psycopg.rows import dict_row


def _conn():
    if USE_PG:
        return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=15)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _sql(s):
    return s.replace("?", "%s") if USE_PG else s


def _exec(sql, params=(), fetch=None):
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(_sql(sql), params)
        result = None
        if fetch == "all":
            result = [dict(r) for r in cur.fetchall()]
        elif fetch == "one":
            r = cur.fetchone()
            result = dict(r) if r else None
        conn.commit()
        return result
    finally:
        conn.close()


def init_db():
    if USE_PG:
        _exec("CREATE TABLE IF NOT EXISTS chats("
              "id BIGSERIAL PRIMARY KEY, "
              "title TEXT DEFAULT 'New chat', "
              "created DOUBLE PRECISION)")
        _exec("CREATE TABLE IF NOT EXISTS messages("
              "id BIGSERIAL PRIMARY KEY, "
              "chat_id BIGINT, role TEXT, text TEXT, "
              "created DOUBLE PRECISION)")
        _exec("CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id)")
    else:
        _exec("CREATE TABLE IF NOT EXISTS chats("
              "id INTEGER PRIMARY KEY AUTOINCREMENT, "
              "title TEXT DEFAULT 'New chat', created REAL)")
        _exec("CREATE TABLE IF NOT EXISTS messages("
              "id INTEGER PRIMARY KEY AUTOINCREMENT, "
              "chat_id INTEGER, role TEXT, text TEXT, created REAL)")


def create_chat():
    if USE_PG:
        r = _exec("INSERT INTO chats(title, created) VALUES (?, ?) RETURNING id",
                  ("New chat", time.time()), fetch="one")
        return r["id"]
    conn = _conn()
    try:
        cur = conn.execute("INSERT INTO chats(title, created) VALUES (?, ?)",
                           ("New chat", time.time()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_chats():
    return _exec("SELECT * FROM chats ORDER BY id DESC", fetch="all")


def get_messages(chat_id):
    return _exec("SELECT * FROM messages WHERE chat_id=? ORDER BY id ASC",
                 (chat_id,), fetch="all")


def add_message(chat_id, role, text):
    if USE_PG:
        r = _exec("INSERT INTO messages(chat_id, role, text, created) "
                  "VALUES (?,?,?,?) RETURNING id",
                  (chat_id, role, text, time.time()), fetch="one")
        return r["id"]
    conn = _conn()
    try:
        cur = conn.execute("INSERT INTO messages(chat_id, role, text, created) "
                           "VALUES (?,?,?,?)",
                           (chat_id, role, text, time.time()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_message(chat_id, msg_id):
    return _exec("SELECT * FROM messages WHERE id=? AND chat_id=?",
                 (msg_id, chat_id), fetch="one")


def update_message(msg_id, text):
    _exec("UPDATE messages SET text=? WHERE id=?", (text, msg_id))


def delete_messages_after(chat_id, msg_id):
    _exec("DELETE FROM messages WHERE chat_id=? AND id>?", (chat_id, msg_id))


def set_title(chat_id, title):
    _exec("UPDATE chats SET title=? WHERE id=?", (title[:40], chat_id))


def delete_chat(chat_id):
    _exec("DELETE FROM messages WHERE chat_id=?", (chat_id,))
    _exec("DELETE FROM chats WHERE id=?", (chat_id,))
