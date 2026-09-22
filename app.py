from flask import Flask, request, jsonify, render_template, Response, session, redirect
import json
import memory, brain, config

app = Flask(__name__)
app.secret_key = "lisa-secret-key-faiz-2026"
memory.init_db()

@app.before_request
def check_login():
    if request.path in ("/login", "/static") or request.path.startswith("/static"):
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
    cid = memory.create_chat()
    return jsonify({"id": cid})

@app.route("/api/chats/<int:chat_id>/messages", methods=["GET"])
def get_messages(chat_id):
    return jsonify(memory.get_messages(chat_id))

@app.route("/api/chats/<int:chat_id>/messages/stream", methods=["POST"])
def send_message_stream(chat_id):
    text = request.json.get("text", "").strip()
    if not text:
        return jsonify({"error": "empty"}), 400

    memory.add_message(chat_id, "user", text)
    history = memory.get_messages(chat_id)
    old_msgs = [{"role": m["role"], "text": m["text"]} for m in history]
    is_first = len(history) == 1

    def generate():
        full = ""
        for chunk in brain.ask_stream(old_msgs):
            full += chunk
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        memory.add_message(chat_id, "ai", full)
        if is_first:
            memory.set_title(chat_id, text)
        yield f"data: {json.dumps({'done': True})}\n\n"

    return Response(generate(), mimetype="text/event-stream")

@app.route("/api/chats/<int:chat_id>", methods=["DELETE"])
def del_chat(chat_id):
    memory.delete_chat(chat_id)
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
