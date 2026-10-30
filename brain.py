import os
import json
import requests
import config

TIMEOUT = 120


class ProviderError(Exception):
    pass


def load_personality():
    try:
        with open("personality.txt", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "You are Lisa, a helpful AI assistant."


def system_text():
    t = load_personality()
    if config.YOUR_NAME:
        t += f"\n\nThe user's name is {config.YOUR_NAME}."
    return t


def _gemini(history):
    if not config.API_KEY:
        raise ProviderError("no key")
    contents = []
    for m in history:
        if not m["text"]:
            continue
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["text"]}]})
    body = {
        "systemInstruction": {"parts": [{"text": system_text()}]},
        "contents": contents,
        "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
    }
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config.MODEL}:streamGenerateContent?alt=sse&key={config.API_KEY}"
    )
    try:
        res = requests.post(url, json=body, stream=True, timeout=TIMEOUT)
    except requests.exceptions.RequestException:
        raise ProviderError("connection error")
    if res.status_code != 200:
        raise ProviderError(f"HTTP {res.status_code}")
    res.encoding = "utf-8"
    got = False
    for line in res.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
            parts = obj["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, json.JSONDecodeError):
            continue
        for p in parts:
            if "text" in p and p["text"]:
                got = True
                yield p["text"]
    if not got:
        raise ProviderError("empty reply")


def _openai_compat(base_url, key, model, history):
    if not key:
        raise ProviderError("no key")
    msgs = [{"role": "system", "content": system_text()}]
    for m in history:
        if not m["text"]:
            continue
        role = "user" if m["role"] == "user" else "assistant"
        msgs.append({"role": role, "content": m["text"]})
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    body = {"model": model, "messages": msgs, "stream": True}
    try:
        res = requests.post(
            base_url.rstrip("/") + "/chat/completions",
            headers=headers, json=body, stream=True, timeout=TIMEOUT,
        )
    except requests.exceptions.RequestException:
        raise ProviderError("connection error")
    if res.status_code != 200:
        raise ProviderError(f"HTTP {res.status_code}")
    res.encoding = "utf-8"
    got = False
    for line in res.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if raw == "[DONE]":
            break
        try:
            obj = json.loads(raw)
            delta = obj["choices"][0]["delta"].get("content")
        except (KeyError, IndexError, json.JSONDecodeError):
            continue
        if delta:
            got = True
            yield delta
    if not got:
        raise ProviderError("empty reply")


def _registry():
    env = os.environ.get
    return {
        "gemini": lambda h: _gemini(h),
        "groq": lambda h: _openai_compat(
            "https://api.groq.com/openai/v1",
            env("GROQ_API_KEY", ""),
            env("GROQ_MODEL", "llama-3.3-70b-versatile"), h),
        "mistral": lambda h: _openai_compat(
            "https://api.mistral.ai/v1",
            env("MISTRAL_API_KEY", ""),
            env("MISTRAL_MODEL", "mistral-small-latest"), h),
        "openrouter": lambda h: _openai_compat(
            "https://openrouter.ai/api/v1",
            env("OPENROUTER_API_KEY", ""),
            env("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"), h),
    }


def ask_stream(history):
    registry = _registry()
    order = [
        n.strip()
        for n in os.environ.get("LLM_ORDER", "gemini,groq,mistral,openrouter").split(",")
        if n.strip()
    ]
    failures = []
    for name in order:
        fn = registry.get(name)
        if not fn:
            continue
        sent = False
        try:
            for chunk in fn(history):
                sent = True
                yield chunk
            print(f"[LISA] answered by {name}", flush=True)
            return
        except (ProviderError, requests.exceptions.RequestException) as e:
            print(f"[LISA] {name} failed: {e}", flush=True)
            if sent:
                yield "\n\n(The connection dropped midway. Please resend if the answer looks cut off.)"
                return
            if str(e) != "no key":
                failures.append(f"{name}: {e}")
    if failures:
        yield "All my brains are busy or unreachable right now (" + "; ".join(failures) + "). Please try again in a moment."
    else:
        yield "No API keys are set up yet. Please add at least one key in the server settings."
