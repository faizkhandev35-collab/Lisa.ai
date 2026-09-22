import sqlite3, time

DB = "memory.db"

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    db = get_db()
    db.execute("""CREATE TABLE IF NOT EXISTS chats(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT DEFAULT 'Nayi chat',
        created REAL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        role TEXT,
        text TEXT,
        created REAL)""")
    db.commit()
    db.close()

def create_chat():
    db = get_db()
    cur = db.execute("INSERT INTO chats(title, created) VALUES (?, ?)", ("Nayi chat", time.time()))
    db.commit()
    cid = cur.lastrowid
    db.close()
    return cid

def list_chats():
    db = get_db()
    rows = db.execute("SELECT * FROM chats ORDER BY id DESC").fetchall()
    db.close()
    return [dict(r) for r in rows]

def get_messages(chat_id):
    db = get_db()
    rows = db.execute("SELECT * FROM messages WHERE chat_id=? ORDER BY id ASC", (chat_id,)).fetchall()
    db.close()
    return [dict(r) for r in rows]

def add_message(chat_id, role, text):
    db = get_db()
    db.execute("INSERT INTO messages(chat_id, role, text, created) VALUES (?,?,?,?)",
               (chat_id, role, text, time.time()))
    db.commit()
    db.close()

def set_title(chat_id, title):
    db = get_db()
    db.execute("UPDATE chats SET title=? WHERE id=?", (title[:40], chat_id))
    db.commit()
    db.close()

def delete_chat(chat_id):
    db = get_db()
    db.execute("DELETE FROM chats WHERE id=?", (chat_id,))
    db.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
    db.commit()
    db.close()
