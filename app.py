import os
import json
from flask import Flask, request, jsonify, render_template, Response, session, redirect
import memory, brain, config

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "lisa-secret-key-faiz-2026")
memory.init_db()


def sse(obj):
    return "data: " + json.dumps(obj) + "\n\n"


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
    return jsonify(memory.get_messages(chat_id))


def stream_reply(chat_id, user_msg_id, is_first, first_text):
    history = memory.get_messages(chat_id)
    msgs = [{"role": m["role"], "text": m["text"]} for m in history]

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
    text = (request.get_json(silent=True) or {}).get("text", "").strip()
    if not text:
        return jsonify({"error": "empty"}), 400
    uid = memory.add_message(chat_id, "user", text)
    is_first = len(memory.get_messages(chat_id)) == 1
    return stream_reply(chat_id, uid, is_first, text)


@app.route("/api/chats/<int:chat_id>/messages/<int:msg_id>/edit", methods=["POST"])
def edit_message(chat_id, msg_id):
    text = (request.get_json(silent=True) or {}).get("text", "").strip()
    if not text:
        return jsonify({"error": "empty"}), 400
    msg = memory.get_message(chat_id, msg_id)
    if not msg or msg["role"] != "user":
        return jsonify({"error": "not found"}), 404
    memory.delete_messages_after(chat_id, msg_id)
    memory.update_message(msg_id, text)
    is_first = len(memory.get_messages(chat_id)) == 1
    return stream_reply(chat_id, msg_id, is_first, text)


@app.route("/api/chats/<int:chat_id>", methods=["DELETE"])
def del_chat(chat_id):
    memory.delete_chat(chat_id)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
