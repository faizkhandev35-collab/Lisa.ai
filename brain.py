import requests
import json
import time
import config

def load_personality():
    try:
        with open("personality.txt", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "You are Lisa, a helpful AI assistant."

def build_body(history):
    personality = load_personality()
    sys_text = personality
    if config.YOUR_NAME:
        sys_text += f"\n\nThe user's name is {config.YOUR_NAME}."

    contents = []
    for m in history:
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["text"]}]})

    return {
        "systemInstruction": {"parts": [{"text": sys_text}]},
        "contents": contents,
        "generationConfig": {
            "thinkingConfig": {"thinkingBudget": 0}
        }
    }

def _try_stream(history):
    body = build_body(history)
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config.MODEL}:streamGenerateContent?alt=sse&key={config.API_KEY}"
    )
    res = requests.post(url, json=body, stream=True, timeout=120)
    return res

def ask_stream(history):
    try:
        res = _try_stream(history)
    except requests.exceptions.RequestException as e:
        yield f"[DEBUG] Connection error: {e}"
        return

    if res.status_code == 200:
        got_any = False
        for line in res.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            raw = line[len("data:"):].strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
                parts = obj["candidates"][0]["content"]["parts"]
                for p in parts:
                    if "text" in p:
                        got_any = True
                        yield p["text"]
            except (KeyError, IndexError, json.JSONDecodeError):
                continue
        if not got_any:
            yield "[DEBUG] Got 200 OK but no text came back."
        return

    yield f"[DEBUG] Status code: {res.status_code} | Body: {res.text[:500]}"
