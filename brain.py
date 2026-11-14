import os
import json
import time
import requests
import config

TIMEOUT = 180
MAX_MESSAGES = 16
SKIP_PREFIXES = ("All my brains are busy", "No API keys are set up")
HINTS = (
    "explain", "why", "how", "calculate", "compare", "plan", "analy",
    "solve", "step by step", "strategy", "business", "debug", "code",
    "prove", "samjha", "kaise", "kyun", "kyu ", "hisab", "margin", "profit",
)


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


def clean_history(history):
    out = []
    for m in history:
        text = (m.get("text") or "").strip()
        if not text:
            continue
        if m["role"] != "user" and text.startswith(SKIP_PREFIXES):
            continue
        role = "user" if m["role"] == "user" else "ai"
        if out and out[-1]["role"] == role:
            out[-1]["text"] += "\n\n" + text
        else:
            out.append({"role": role, "text": text})
    out = out[-MAX_MESSAGES:]
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def needs_thinking(history):
    mode = os.environ.get("THINK_MODE", "auto").lower()
    if mode == "on":
        return True
    if mode == "off":
        return False
    last = history[-1]["text"] if history else ""
    low = last.lower()
    return len(last) > 150 or any(h in low for h in HINTS)


def _gemini(history):
    if not config.API_KEY:
        raise ProviderError("no key")
    contents = []
    for m in history:
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["text"]}]})
    body = {
        "systemInstruction": {"parts": [{"text": system_text()}]},
        "contents": contents,
    }
    if not needs_thinking(history):
        body["generationConfig"] = {"thinkingConfig": {"thinkingBudget": 0}}
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


def _openai(h):
    env = os.environ.get
    key = env("OPENAI_API_KEY", "") or env("CHATGPT_API_KEY", "")
    return _openai_compat(
        "https://api.openai.com/v1", key,
        env("OPENAI_MODEL", "gpt-4o-mini"), h)


def _registry():
    env = os.environ.get
    return {
        "gemini": lambda h: _gemini(h),
        "openai": _openai,
        "chatgpt": _openai,
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


LABELS = {
    "gemini": "Gemini", "openai": "ChatGPT", "chatgpt": "ChatGPT",
    "groq": "Groq", "mistral": "Mistral", "openrouter": "OpenRouter",
}


def _why(e):
    s = str(e)
    if "429" in s:
        return "limit reached"
    if "connection" in s:
        return "no connection"
    if "empty" in s:
        return "empty reply"
    return s


def _has_key(name):
    env = os.environ.get
    if name == "gemini":
        return bool(config.API_KEY)
    if name in ("openai", "chatgpt"):
        return bool(env("OPENAI_API_KEY") or env("CHATGPT_API_KEY"))
    return bool(env(name.upper() + "_API_KEY"))


def ask_stream(history):
    yield ("status", "Reading our conversation")
    history = clean_history(history)
    if not history:
        yield ("text", "Please send a message first.")
        return
    registry = _registry()
    order = [
        n.strip().lower()
        for n in os.environ.get("LLM_ORDER", "gemini,mistral").split(",")
        if n.strip()
    ]
    failures = []
    for name in order:
        fn = registry.get(name)
        if not fn:
            print(f"[LISA] unknown provider in LLM_ORDER: {name}", flush=True)
            continue
        if not _has_key(name):
            print(f"[LISA] {name} skipped: no key", flush=True)
            continue
        label = LABELS.get(name, name)
        deep = name == "gemini" and needs_thinking(history)
        yield ("status", f"Thinking deeply with {label}" if deep else f"Asking {label}")
        sent = False
        t0 = time.time()
        try:
            for chunk in fn(history):
                sent = True
                yield ("text", chunk)
            print(f"[LISA] answered by {name} in {time.time() - t0:.1f}s", flush=True)
            return
        except (ProviderError, requests.exceptions.RequestException) as e:
            print(f"[LISA] {name} failed after {time.time() - t0:.1f}s: {e}", flush=True)
            if sent:
                yield ("text", "\n\n(The connection dropped midway. Please resend if the answer looks cut off.)")
                return
            failures.append(f"{name}: {e}")
            yield ("status", f"{label} unavailable ({_why(e)}), switching brain")
    if failures:
        yield ("text", "All my brains are busy or unreachable right now (" + "; ".join(failures) + "). Please try again in a moment.")
    else:
        yield ("text", "No API keys are set up yet. Please add at least one key in the server settings.")
