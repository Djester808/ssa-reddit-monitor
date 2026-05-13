#!/usr/bin/env python3
"""Fetch and scan comment threads of known SSA posts for negative comments."""

import urllib.request
import json
import time

UA = "ssa-mention-monitor/1.0 (operated by Superior Shrimp & Aquatics)"

THREADS = [
    ("Purchase gone bad! (89 comments)", "shrimptank", "1oq87i8"),
    ("Do not buy from superior! (14 comments)", "shrimptank", "1oq89ob"),
    ("Superior Shrimp & Aquatics - (131 comments)", "shrimptank", "1mprqiq"),
]

NEG_WORDS = [
    "doa", "dead on arrival", "scam", "fraud", "ripoff", "rip off",
    "avoid", "terrible", "awful", "horrible", "worst", "beware", "warning",
    "refund", "dispute", "stolen", "ignored", "no response", "never again",
    "disappointed", "lied", "mislead", "false", "fake", "garbage",
    "trash", "do not", "don't", "bad experience", "poor quality",
    "upset", "blocked", "ghosted", "dead", "died", "never received",
    "charged", "lost", "wrong", "sick", "disease",
]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def walk(node, out):
    if not isinstance(node, dict):
        return
    kind = node.get("kind")
    data = node.get("data", {})
    if kind == "Listing":
        for child in data.get("children", []):
            walk(child, out)
    elif kind == "t1":
        body = (data.get("body") or "").strip()
        score = data.get("score", 0)
        author = data.get("author", "?")
        out.append((score, author, body))
        replies = data.get("replies")
        if replies and isinstance(replies, dict):
            walk(replies, out)


for title, sub, post_id in THREADS:
    print(f"\n{'='*72}")
    print(f"THREAD: {title}")
    print(f"URL: https://reddit.com/r/{sub}/comments/{post_id}/")
    print("=" * 72)
    url = f"https://www.reddit.com/r/{sub}/comments/{post_id}.json?limit=500&depth=10"
    try:
        data = fetch(url)
    except Exception as e:
        print(f"  ERROR: {e}")
        time.sleep(2)
        continue

    comments = []
    for section in data:
        walk(section, comments)

    # flag comments containing negative keywords
    neg = []
    for score, author, body in comments:
        bl = body.lower()
        if any(w in bl for w in NEG_WORDS):
            neg.append((score, author, body))

    # sort lowest score (most downvoted/controversial) first
    neg.sort(key=lambda x: x[0])

    if not neg:
        print("  (no negative-flagged comments found)")
    else:
        print(f"  {len(neg)} comments with negative signals:\n")
        for score, author, body in neg:
            preview = body[:600] + ("..." if len(body) > 600 else "")
            print(f"  u/{author} | score:{score}")
            print(f"  {preview}")
            print()

    time.sleep(2)
