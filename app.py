import os
import json
from flask import Flask, request, jsonify, render_template, Response, session, redirect
import memory, brain, config

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "lisa-secret-key-faiz-2026")
app.config["MAX_CONTENT_LENGTH"] = 24 * 1024 * 1024
memory.init_db()

MAX_FILES = 4
MAX_TOTAL = 10 * 1024 * 1024
MAX_TEXT_CHARS = 60000
IMAGE_MIME = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "webp": "image/webp", "heic": "image/heic", "heif": "image/heif",
}
TEXT_EXT = {
    "txt", "md", "csv", "json", "py", "js", "ts", "html", "css", "xml",
    "log", "yml", "yaml", "ini", "sql", "java", "c", "cpp", "h", "sh", "tsv",
}


def sse(obj):
    return "data: " + json.dumps(obj) + "\n\n"


def classify(name, mime):
    mime = (mime or "").lower()
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if mime in ("image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"):
        return "image", mime
    if ext in IMAGE_MIME:
        return "image", IMAGE_MIME[ext]
    if mime == "application/pdf" or ext == "pdf":
        return "pdf", "application/pdf"
    if mime.startswith("text/") or ext in TEXT_EXT:
        return "text", "text/plain"
    return None, None


def read_uploads(files):
    items = []
    total = 0
    for f in files[:MAX_FILES]:
        name = (f.filename or "file").strip()[:120] or "file"
        data = f.read()
        if not data:
            continue
        total += len(data)
        if total > MAX_TOTAL:
            return None, "Attachments are too large (the limit is about 10 MB in total)."
        kind, mime = classify(name, f.mimetype)
        if not kind:
            return None, f"I can't read {name} yet. I can read photos, PDFs and text files."
        items.append((name, mime, kind, data))
    return items, None


def build_msgs(chat_id):
    history = memory.get_messages(chat_id)
    by_msg = {}
    for a in memory.list_attachments(chat_id):
        by_msg.setdefault(a["message_id"], []).append(a)
    window = {m["id"] for m in history[-24:]}
    last_binary = None
    for m in history[-24:]:
        if any(a["kind"] in ("image", "pdf") for a in by_msg.get(m["id"], [])):
            last_binary = m["id"]
    msgs = []
    for m in history:
        text = m["text"] or ""
        atts = []
        notes = []
        for a in by_msg.get(m["id"], []):
            if a["kind"] == "text":
                if m["id"] in window:
                    row = memory.get_attachment(a["id"])
                    content = row["data"].decode("utf-8", errors="replace")[:MAX_TEXT_CHARS]
                    text += f"\n\n[Attached file: {a['name']}]\n{content}"
                else:
                    notes.append(a["name"])
            elif m["id"] == last_binary:
                row = memory.get_attachment(a["id"])
                atts.append({"kind": a["kind"], "mime": a["mime"],
                             "name": a["name"], "data": row["data"]})
            else:
                notes.append(a["name"])
        if notes:
            text += "\n\n[Earlier attachment(s) not shown again: " + ", ".join(notes) + "]"
        msgs.append({"role": m["role"], "text": text, "atts": atts})
    return msgs


@app.before_request
def check_login():
    if request.path == "/login" or request.path.startswith("/static"):
        return
    if not session.get("ok"):
        return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == config.APP_PASSWORD:
            session["ok"] = True
            return redirect("/")
        return render_template("login.html", error="Wrong password, try again.")
    return render_template("login.html")


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/chats", methods=["GET"])
def get_chats():
    return jsonify(memory.list_chats())


@app.route("/api/chats", methods=["POST"])
def new_chat():
    return jsonify({"id": memory.create_chat()})


@app.route("/api/chats/<int:chat_id>/messages", methods=["GET"])
def get_messages(chat_id):
    msgs = memory.get_messages(chat_id)
    by_msg = {}
    for a in memory.list_attachments(chat_id):
        by_msg.setdefault(a["message_id"], []).append(a)
    for m in msgs:
        m["atts"] = by_msg.get(m["id"], [])
    return jsonify(msgs)


@app.route("/api/attachments/<int:att_id>")
def get_attachment(att_id):
    a = memory.get_attachment(att_id)
    if not a:
        return "", 404
    return Response(a["data"], mimetype=a["mime"],
                    headers={"Cache-Control": "private, max-age=3600"})


def stream_reply(chat_id, user_msg_id, is_first, first_text):
    msgs = build_msgs(chat_id)

    def generate():
        yield sse({"user_id": user_msg_id})
        full = ""
        for kind, value in brain.ask_stream(msgs):
            if kind == "status":
                yield sse({"status": value})
            else:
                full += value
                yield sse({"chunk": value})
        ai_id = memory.add_message(chat_id, "ai", full)
        if is_first:
            memory.set_title(chat_id, first_text)
        yield sse({"done": True, "ai_id": ai_id})

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/chats/<int:chat_id>/messages/stream", methods=["POST"])
def send_message_stream(chat_id):
    if request.form or request.files:
        text = (request.form.get("text") or "").strip()
        files = request.files.getlist("files")
    else:
        text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
        files = []
    items, err = read_uploads(files)
    if err:
        return jsonify({"error": err}), 400
    if not text and not items:
        return jsonify({"error": "empty"}), 400
    uid = memory.add_message(chat_id, "user", text)
    for name, mime, kind, data in items:
        memory.add_attachment(uid, chat_id, name, mime, kind, data)
    is_first = len(memory.get_messages(chat_id)) == 1
    title = text or (items[0][0] if items else "New chat")
    return stream_reply(chat_id, uid, is_first, title)


@app.route("/api/chats/<int:chat_id>/messages/<int:msg_id>/edit", methods=["POST"])
def edit_message(chat_id, msg_id):
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    msg = memory.get_message(chat_id, msg_id)
    if not msg or msg["role"] != "user":
        return jsonify({"error": "not found"}), 404
    has_att = any(a["message_id"] == msg_id for a in memory.list_attachments(chat_id))
    if not text and not has_att:
        return jsonify({"error": "empty"}), 400
    memory.delete_messages_after(chat_id, msg_id)
    memory.update_message(msg_id, text)
    is_first = len(memory.get_messages(chat_id)) == 1
    return stream_reply(chat_id, msg_id, is_first, text or "Attachment")


@app.route("/api/chats/<int:chat_id>", methods=["DELETE"])
def del_chat(chat_id):
    memory.delete_chat(chat_id)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
