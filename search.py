import os
import re
import time
import requests

URL = "https://api.tavily.com/search"
TIMEOUT = 15
MAX_RESULTS = 5
SNIPPET_CHARS = 600

TRIGGERS = (
    "latest", "news", "headlines", "weather", "live score", "match score",
    "cricket score", "price of", "prices of", "market price", "current price",
    "current rate", "exchange rate", "how much does", "how much is",
    "release date", "just launched", "who won", "who is the current",
    "trending", "search the web", "search for", "search online", "search:",
    "look up", "google it", "on the internet", "on the web",
    "kimat", "bhav", "khabar", "samachar", "mausam", "search karo",
    "search kar ", "dhundh", "net pe", "internet pe", "google karo",
    "kitne ka", "kitne mein", "kitne ki", "aaj ka rate", "aaj ka price",
    "aaj ki news",
)
# things whose value changes every day (money, metals, fuel, crypto, markets)
TOPICS = (
    "dollar", "usd", "euro", "eur ", "pound", "gbp", "yen", "dirham", "inr",
    "gold", "silver", "sona ", "sone ", "chandi", "petrol", "diesel", "lpg",
    "bitcoin", "btc", "ethereum", "crypto", "sensex", "nifty", "share price", "stock price",
)
TOPIC_CUES = (
    "rate", "price", "kimat", "bhav", "cost", "value", "kitne", "kitna", "how much",
    " to inr", " in inr", " to rupee", " in rupee", "rupees", "convert", "today", "aaj",
    "abhi", "current", "live", "now", "kya hai", "kaisa", "chal raha", "=",
)
# "right now" words only count together with a fact word (so "aaj ka study plan" does not search)
FRESH = ("aaj", "abhi", "today", "current", "currently", "right now", "live", "this week",
         "this month", "tonight")
FACT = ("rate", "price", "kimat", "bhav", "cost", "score", "result", "news", "weather",
        "mausam", "value of", "kya chal", "who is", "kaun hai")
NEWS_WORDS = ("news", "headlines", "khabar", "samachar", "just launched")

_usage = {"day": "", "n": 0}


def _key():
    return os.environ.get("TAVILY_API_KEY", "").strip()


def _mode():
    return os.environ.get("SEARCH_MODE", "auto").lower()


def _cap():
    try:
        return int(os.environ.get("SEARCH_MAX_PER_DAY", "25"))
    except ValueError:
        return 25


def _reason(history):
    """Returns (should_search, reason)."""
    mode = _mode()
    if mode == "off":
        return False, "SEARCH_MODE is off"
    if not _key():
        return False, "TAVILY_API_KEY is not set on the server"
    if not history or history[-1].get("role") != "user":
        return False, "no user message"
    last = (history[-1].get("text") or "")[:500].strip()
    if not last:
        return False, "empty message"
    if mode == "on":
        return True, "SEARCH_MODE is on"
    low = last.lower()
    if any(t in low for t in TRIGGERS):
        return True, "trigger word"
    if any(t in low for t in TOPICS) and any(c in low for c in TOPIC_CUES):
        return True, "changing-value topic"
    if any(f in low for f in FRESH) and any(f in low for f in FACT):
        return True, "fresh + fact words"
    return False, "no search needed"


def should_search(history):
    ok, why = _reason(history)
    print(f"[LISA] search {'on' if ok else 'skipped'}: {why}", flush=True)
    return ok


def build_query(history):
    users = [m for m in history if m.get("role") == "user" and m.get("text")]
    last = users[-1]["text"].strip()[:300]
    q = last
    if len(last) < 40 and len(users) > 1:
        q = users[-2]["text"].strip()[:200] + " " + last
    q = re.sub(r"^\s*(/search|search:)\s*", "", q, flags=re.I)
    return re.sub(r"\s+", " ", q)[:380]


def _note(text):
    return {"ok": False, "count": 0, "context": "[SYSTEM NOTE: " + text + "]"}


def run(history):
    key = _key()
    today = time.strftime("%Y-%m-%d")
    if _usage["day"] != today:
        _usage["day"], _usage["n"] = today, 0
    if _usage["n"] >= _cap():
        return _note("The daily web-search limit has been reached. Tell the user briefly that you "
                     "could not check the web, then answer from your own knowledge and say it may be outdated.")
    _usage["n"] += 1
    query = build_query(history)
    body = {
        "query": query,
        "search_depth": "basic",
        "max_results": MAX_RESULTS,
        "include_answer": False,
    }
    if any(w in query.lower() for w in NEWS_WORDS):
        body["topic"] = "news"
    try:
        res = requests.post(
            URL, json=body, timeout=TIMEOUT,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
    except requests.exceptions.RequestException:
        print("[LISA] web search failed: connection error", flush=True)
        return _note("A web search was attempted but could not connect. Tell the user briefly that you "
                     "could not check the web right now, then answer from your own knowledge and say it may be outdated.")
    if res.status_code != 200:
        print(f"[LISA] web search failed: HTTP {res.status_code}", flush=True)
        return _note(f"A web search was attempted but failed (HTTP {res.status_code}). Tell the user briefly "
                     "that you could not check the web right now, then answer from your own knowledge and say it may be outdated.")
    try:
        results = res.json().get("results") or []
    except ValueError:
        results = []
    lines = [f'[WEB SEARCH RESULTS for "{query}", fetched just now]']
    count = 0
    for r in results[:MAX_RESULTS]:
        snippet = re.sub(r"\s+", " ", (r.get("content") or "")).strip()[:SNIPPET_CHARS]
        if not snippet:
            continue
        count += 1
        lines.append(f"{count}. {(r.get('title') or 'Untitled').strip()} - {r.get('url', '')}\n   {snippet}")
    if not count:
        return _note("A web search returned no usable results. Tell the user briefly, then answer from your "
                     "own knowledge and say it may be outdated.")
    lines.append("[END OF WEB SEARCH RESULTS]")
    lines.append("Use these results to answer the user's latest message. Name the sources you rely on "
                 "(site name or link). If the results do not contain the answer, say so plainly instead of "
                 "guessing. Never invent prices, dates or facts.")
    print(f"[LISA] web search ok: {count} sources", flush=True)
    return {"ok": True, "count": count, "context": "\n".join(lines)}


def attach(history, result):
    if not history or history[-1].get("role") != "user":
        return history
    last = history[-1]
    last["q"] = last["text"]
    last["text"] = (last["text"] + "\n\n" + result["context"]).strip()
    return history
