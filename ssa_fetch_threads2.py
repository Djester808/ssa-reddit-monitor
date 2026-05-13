#!/usr/bin/env python3
"""Fetch comment threads for additional SSA-related posts (plants, snails, other complaints)."""

import urllib.request
import json
import time

UA = "ssa-mention-monitor/1.0 (operated by Superior Shrimp & Aquatics)"

# All threads that directly mention SSA and haven't been checked yet
THREADS = [
    ("Just ordered cull shrimp. Is this clado??? (24 comments, Feb 2026)", "shrimptank", "1r25etx"),
    ("Anyone have experience with this place? (13 comments, Jun 2025)", "shrimptank", "1l9789i"),
    ("I ordered blue jellies and most arrived dead (8 comments, May 2025)", "shrimptank", "1kcu5c0"),
    ("Best place to get shrimp? mentions SSA (20 comments, Dec 2024)", "shrimptank", "1hi6b5u"),
    ("What does the + mean for vendors? (8 comments, Dec 2024)", "shrimptank", "1hg4e97"),
    ("Receiving shrimp in the mail / SSA recommendation? (10 comments, Sep 2024)", "shrimptank", "1fihdji"),
    ("Finally ordered shrimp from a hobby breeder review (12 comments, Feb 2025)", "shrimptank", "1j0al1i"),
    ("Review of djester808 aka superiorshrimpaquatics (1 comment, Nov 2024)", "shrimptank", "1gqjt9l"),
]

NEG_WORDS = [
    "doa", "dead on arrival", "scam", "fraud", "ripoff", "rip off",
    "avoid", "terrible", "awful", "horrible", "worst", "beware", "warning",
    "refund", "dispute", "stolen", "ignored", "no response", "never again",
    "disappointed", "lied", "mislead", "false", "fake", "garbage",
    "trash", "do not", "don't", "bad experience", "poor quality",
    "upset", "blocked", "ghosted", "dead", "died", "never received",
    "charged", "lost", "wrong", "sick", "disease", "parasite", "clado",
    "algae", "contaminated", "mislabeled", "wrong plant", "wrong species",
    "empty shell", "missing", "short", "complaint", "rude", "unprofessional",
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

    all_comments = []
    for section in data:
        walk(section, all_comments)

    # Show ALL comments (these threads are small enough)
    all_comments.sort(key=lambda x: x[0])

    neg = [(s, a, b) for s, a, b in all_comments
           if any(w in b.lower() for w in NEG_WORDS)]
    pos = [(s, a, b) for s, a, b in all_comments
           if (s, a, b) not in neg]

    print(f"  Total comments fetched: {len(all_comments)}")

    if neg:
        print(f"\n  --- NEGATIVE-FLAGGED ({len(neg)}) ---")
        for score, author, body in sorted(neg, key=lambda x: x[0]):
            preview = body[:700] + ("..." if len(body) > 700 else "")
            print(f"\n  u/{author} | score:{score}")
            print(f"  {preview}")

    if pos:
        print(f"\n  --- OTHER COMMENTS ({len(pos)}) ---")
        for score, author, body in sorted(pos, key=lambda x: -x[0]):
            if not body:
                continue
            preview = body[:400] + ("..." if len(body) > 400 else "")
            print(f"\n  u/{author} | score:{score}")
            print(f"  {preview}")

    time.sleep(2)
