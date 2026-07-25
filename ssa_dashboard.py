#!/usr/bin/env python3
"""
SSA Reddit Monitor — Desktop Dashboard
Run this to view mentions, filter results, and trigger manual scans.
"""

import difflib
import json
import os
import queue
import re
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
import urllib.request
import webbrowser
from datetime import datetime

import ssa_reddit
import ssa_shopify

_HERE        = os.path.dirname(os.path.abspath(__file__))
LOG_DIR      = os.path.join(_HERE, "ssa_monitor_logs")
RESULTS_FILE = os.path.join(LOG_DIR, "results_latest.json")
SEEN_FILE    = os.path.join(LOG_DIR, "seen_ids.json")
REPLIED_FILE = os.path.join(LOG_DIR, "replied_ids.json")
NOTIFY_SCRIPT = os.path.join(_HERE, "ssa_notify.py")
PYTHON       = os.path.join(os.environ.get("LOCALAPPDATA",""), "Microsoft", "WindowsApps", "python.exe")

def load_replied():
    if not os.path.exists(REPLIED_FILE):
        return set()
    with open(REPLIED_FILE, encoding="utf-8") as f:
        return set(json.load(f))

def save_replied(replied_set):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(REPLIED_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(replied_set), f)

def _extract_post_id(url):
    m = re.search(r'/comments/([a-z0-9]+)', url or "")
    return m.group(1) if m else None

def _walk_comments(children, username):
    for child in children:
        d = child.get("data", {})
        if d.get("author", "").lower() == username.lower():
            return True
        replies = d.get("replies", "")
        if isinstance(replies, dict):
            sub = replies.get("data", {}).get("children", [])
            if _walk_comments(sub, username):
                return True
    return False

def _check_post_replied(post_id, username="djester808"):
    """Fetch post comment tree; return True if username has any comment."""
    url = f"https://www.reddit.com/comments/{post_id}/.json?limit=500"
    req = urllib.request.Request(url, headers={"User-Agent": "ssa-monitor/1.0 by djester808"})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())
    except Exception:
        return None  # None = couldn't fetch, don't cache
    if not isinstance(data, list) or len(data) < 2:
        return False
    return _walk_comments(data[1]["data"]["children"], username)


REPLY_TEMPLATE = (
    "Hey! I run Superior Shrimp & Aquatics and we might have exactly what you're "
    "looking for. Feel free to check out our shop or DM me if you have any questions!"
)
DM_SUBJECT  = "Superior Shrimp & Aquatics — saw your post"
DM_TEMPLATE = (
    "Hey u/{author}!\n\n"
    "Saw your post in r/{subreddit} and wanted to reach out. I run Superior Shrimp & "
    "Aquatics and carry a variety of neocaridina and caridina shrimp.\n\n"
    "Let me know if you're interested or have any questions!\n\n"
    "— djester808"
)
POST_SUBREDDITS = ["AquaSwap", "shrimptank", "PlantedTank", "Aquariums", "duluth"]

_EXACT_QUERIES = {
    "superior shrimp aquatics",
    "superiorshrimpaquatics",
    "djester808",
}

DIRECT_QUERIES = _EXACT_QUERIES | {
    "superior aquatics",
    "superior shrimp",
    "ssa shrimp",
    "ssa",
}

def _is_direct(query, text):
    return _mentions_ssa(text)

EXACT_BRAND_QUERIES = {
    "superior shrimp aquatics",
    "superiorshrimpaquatics",
    "djester808",
}

AQUATICS_SUBS = {
    "shrimptank", "aquaswap", "plantedtank", "aquariums", "aquaticplants",
    "freshwater", "reeftank", "bettafish", "fishkeeping", "wetpetclassifieds",
    "nanotank", "invertebrates", "neocaridina", "caridina", "duluth",
    "minnesota",
}

BUYING_QUERIES = {
    "wtb shrimp",
    "iso shrimp",
    "looking for shrimp",
    "where to buy shrimp",
    "recommend shrimp seller",
    "wtb aquatics",
    "iso aquatics",
}

BUYING_WORDS = [
    "wtb", "[wtb]", "[lf]", "[iso]", "in search of",
    "looking for", "looking to buy", "want to buy",
    "where to buy", "where can i buy", "where can i get",
    "best place to buy", "best place to get",
    "anyone selling", "any sellers", "recommend a seller",
    "seller", "who sells", "buying shrimp", "buy shrimp",
]

AQUATICS_WORDS = [
    "shrimp", "aquatic", "neocaridina", "caridina", "planted tank",
    "fish tank", "aquarium", "reef", "freshwater", "saltwater",
    "invertebrate", "snail", "crayfish", "dwarf shrimp", "ssa",
]

def is_buying_intent(query, text):
    t = text.lower()
    return any(w in t for w in BUYING_WORDS) and any(w in t for w in AQUATICS_WORDS)

NEG_WORDS = [
    "doa", "dead on arrival", "scam", "fraud", "avoid",
    "terrible", "awful", "horrible", "worst", "beware", "warning",
    "refund", "dispute", "ignored", "no response", "never again",
    "disappointed", "lied", "fake", "garbage", "trash",
    "do not buy", "do not order", "do not recommend", "do not trust",
    "don't buy", "don't order", "don't recommend", "don't trust",
    "bad experience", "blocked", "ghosted",
    "disease", "parasite", "clado", "mislabeled",
    "wrong order", "wrong shrimp", "missing shrimp", "missing order",
    "rude", "unprofessional", "never received",
]

_SSA_RE = re.compile(
    r'superior shrimp aquatics|superiorshrimpaquatics|djester808'
    r'|superior shrimp|superior aquatics|(?<!\w)ssa(?!\w)',
    re.IGNORECASE,
)

def _mentions_ssa(text):
    return bool(_SSA_RE.search(text))

def _is_negated(text, neg_word):
    pattern = r'\b(?:without|no|not|zero|never|didn\'t|wasn\'t|weren\'t)\b(?:\s+\w+){0,2}\s+' + re.escape(neg_word)
    return bool(re.search(pattern, text, re.IGNORECASE))

def is_negative(text):
    if not _mentions_ssa(text):
        return False
    t = text.lower()
    return any(w in t and not _is_negated(t, w) for w in NEG_WORDS)

def is_positive(text):
    return _mentions_ssa(text) and not is_negative(text)

def is_own_post(author):
    return (author or "").lower() in ("djester808", "superiorshrimpaquatics")

def fmt_time(epoch):
    if not epoch:
        return ""
    is_dst = time.localtime(epoch).tm_isdst
    label = "CDT" if is_dst else "CST"
    return datetime.fromtimestamp(epoch).strftime(f"%Y-%m-%d %H:%M {label}")

def parse_order_input(text: str):
    """Parse order input like '2x jungle val' or '2X jungle val' (case-insensitive)."""
    lines = text.strip().split('\n')
    items = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Handle both uppercase and lowercase X by splitting on lowercase then checking
        parts = re.split(r'[xX]', line, maxsplit=1)
        if len(parts) == 2 and parts[0].strip().isdigit():
            # Format: "2x product name" or "2X product name"
            qty = int(parts[0].strip())
            name = parts[1].strip()
            items.append((qty, name))
        else:
            # Format: just "product name" (no quantity specified)
            items.append((1, line))
    return items

def fuzzy_match_product(product_name: str, products: list, threshold=0.5):
    """Fuzzy match product name against catalog. Returns sorted [(product, score)]."""
    matches = []
    name_lower = product_name.lower()
    name_words = name_lower.split()

    for p in products:
        title = p.get("title", "").lower()
        title_words = title.split()

        # Check if product contains all search words (word-level matching)
        contains_all_words = all(word in title for word in name_words)

        # Character-level similarity
        char_ratio = difflib.SequenceMatcher(None, name_lower, title).ratio()

        # Word-level bonus: if product title starts with any search word
        starts_with_word = any(title.startswith(word) for word in name_words)

        # Combined score: word matching + character ratio
        if contains_all_words:
            score = char_ratio + 0.5  # Boost if all words are present
        elif starts_with_word:
            score = char_ratio + 0.2  # Modest boost if starts with search word
        else:
            score = char_ratio

        if score >= threshold:
            matches.append((p, score))

    return sorted(matches, key=lambda x: x[1], reverse=True)

def load_results():
    if not os.path.exists(RESULTS_FILE):
        return [], []
    with open(RESULTS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    posts    = data.get("posts", [])
    comments = data.get("comments", [])
    return posts, comments

def reddit_url(item, kind="post"):
    p = item.get("permalink", "")
    return f"https://reddit.com{p}" if p else ""


_BG, _FG, _EB = "#1e1e2e", "#cdd6f4", "#313244"

_PRODUCT_CACHE = None  # Global cache for products (None = not cached, False = fetch failed)


class CredentialsDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Reddit API Setup")
        self.geometry("500x320")
        self.configure(bg=_BG)
        self.resizable(False, False)
        self.grab_set()
        self._build()

    def _build(self):
        tk.Label(self, text="Reddit API Setup", font=("Segoe UI", 13, "bold"),
                 bg=_BG, fg=_FG).pack(pady=(16, 2))
        tk.Label(self,
                 text="Create a 'script' app at reddit.com/prefs/apps  •  redirect: http://localhost:8080",
                 font=("Segoe UI", 8), bg=_BG, fg="#6c7086", wraplength=460).pack(pady=(0, 10))

        fields = {}
        for label, key, show in [("Client ID", "client_id", ""),
                                  ("Client Secret", "client_secret", "•"),
                                  ("Reddit Password", "password", "•")]:
            row = tk.Frame(self, bg=_BG)
            row.pack(fill="x", padx=20, pady=4)
            tk.Label(row, text=label, width=16, anchor="w",
                     bg=_BG, fg=_FG, font=("Segoe UI", 9)).pack(side="left")
            var = tk.StringVar()
            tk.Entry(row, textvariable=var, show=show, bg=_EB, fg=_FG,
                     insertbackground=_FG, relief="flat",
                     font=("Segoe UI", 9)).pack(side="left", fill="x", expand=True)
            fields[key] = var

        creds = ssa_reddit.load_creds()
        if creds:
            for k, v in creds.items():
                if k in fields:
                    fields[k].set(v)
        self._fields = fields

        self._status = tk.Label(self, text="", bg=_BG, fg="#f38ba8", font=("Segoe UI", 9))
        self._status.pack(pady=6)

        tk.Button(self, text="Save & Test", command=self._save,
                  bg="#89b4fa", fg=_BG, font=("Segoe UI", 9, "bold"),
                  relief="flat", padx=16, pady=5).pack()

    def _save(self):
        cid = self._fields["client_id"].get().strip()
        sec = self._fields["client_secret"].get().strip()
        pwd = self._fields["password"].get().strip()
        if not all([cid, sec, pwd]):
            self._status.config(text="All fields are required.", fg="#f38ba8")
            return
        ssa_reddit.save_creds(cid, sec, pwd)
        self._status.config(text="Testing…", fg="#89b4fa")
        self.update()
        try:
            name = ssa_reddit.test_auth()
            self._status.config(text=f"✓ Connected as u/{name}", fg="#a6e3a1")
        except Exception as e:
            self._status.config(text=f"Error: {e}", fg="#f38ba8")


class ReplyDialog(tk.Toplevel):
    """Opens the Reddit post in the browser and lets the user copy a pre-filled reply."""

    def __init__(self, parent, row):
        super().__init__(parent)
        self.row = row
        self.title("Reply")
        self.geometry("640x400")
        self.configure(bg=_BG)
        self.resizable(True, True)
        self.grab_set()
        self._build()
        # Open Reddit in browser immediately
        url = row.get("url", "")
        if url:
            webbrowser.open(url)

    def _build(self):
        if self.row.get("title"):
            tk.Label(self, text=f"Re: {self.row['title'][:90]}",
                     font=("Segoe UI", 8), bg="#181825", fg="#6c7086",
                     anchor="w", padx=12, pady=5).pack(fill="x")

        tk.Label(self, text="Edit your reply, then click Copy — paste it into Reddit.",
                 font=("Segoe UI", 9), bg=_BG, fg="#6c7086",
                 anchor="w", padx=14).pack(fill="x", pady=(8, 2))

        inner = tk.Frame(self, bg=_BG)
        inner.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        self._txt = tk.Text(inner, bg=_EB, fg=_FG, insertbackground=_FG,
                            relief="flat", font=("Segoe UI", 9), wrap="word")
        self._txt.insert("1.0", REPLY_TEMPLATE)
        self._txt.pack(fill="both", expand=True)
        self._txt.focus_set()
        self._txt.mark_set("insert", "end")

        self._status = tk.Label(self, text="", bg=_BG, fg="#a6e3a1", font=("Segoe UI", 9))
        self._status.pack(pady=(0, 2))

        bf = tk.Frame(self, bg=_BG)
        bf.pack(fill="x", padx=14, pady=(0, 10))
        tk.Button(bf, text="Close", command=self.destroy,
                  bg=_EB, fg=_FG, font=("Segoe UI", 9),
                  relief="flat", padx=10, pady=4).pack(side="right", padx=4)
        tk.Button(bf, text="Open in Reddit", command=self._open,
                  bg=_EB, fg=_FG, font=("Segoe UI", 9),
                  relief="flat", padx=10, pady=4).pack(side="right", padx=4)
        tk.Button(bf, text="Copy Text", command=self._copy,
                  bg="#89b4fa", fg=_BG, font=("Segoe UI", 9, "bold"),
                  relief="flat", padx=14, pady=4).pack(side="right")

    def _copy(self):
        text = self._txt.get("1.0", "end").strip()
        self.clipboard_clear()
        self.clipboard_append(text)
        self._status.config(text="✓ Copied — paste into Reddit's reply box.")

    def _open(self):
        url = self.row.get("url", "")
        if url:
            webbrowser.open(url)


class ComposeDialog(tk.Toplevel):
    def __init__(self, parent, mode, row=None):
        super().__init__(parent)
        self.mode = mode   # "dm" | "post"
        self.row  = row or {}
        self.configure(bg=_BG)
        self.resizable(True, True)
        self.grab_set()
        self._fields = {}
        self._build()

    def _build(self):
        titles = {"dm": "Send DM", "post": "New Post"}
        sizes  = {"dm": "640x460", "post": "640x500"}
        self.title(titles[self.mode])
        self.geometry(sizes[self.mode])

        if self.mode == "dm" and self.row.get("title"):
            tk.Label(self, text=f"Re: {self.row['title'][:90]}",
                     font=("Segoe UI", 8), bg="#181825", fg="#6c7086",
                     anchor="w", padx=12, pady=5).pack(fill="x")

        inner = tk.Frame(self, bg=_BG)
        inner.pack(fill="both", expand=True, padx=14, pady=8)

        if self.mode == "dm":
            author = self.row.get("author", "").lstrip("u/")
            sub    = self.row.get("subreddit", "").lstrip("r/")
            self._field(inner, "To", author, readonly=True)
            self._field(inner, "Subject", DM_SUBJECT)
            self._body(inner, DM_TEMPLATE.format(author=author, subreddit=sub))

        else:
            sf = tk.Frame(inner, bg=_BG)
            sf.pack(fill="x", pady=3)
            tk.Label(sf, text="Subreddit", width=10, anchor="w",
                     bg=_BG, fg=_FG, font=("Segoe UI", 9)).pack(side="left")
            sub_var = tk.StringVar(value=POST_SUBREDDITS[0])
            ttk.Combobox(sf, textvariable=sub_var, values=POST_SUBREDDITS,
                         state="readonly", width=22).pack(side="left")
            self._fields["subreddit"] = sub_var
            self._field(inner, "Title", "")
            self._body(inner, "")

        self._status = tk.Label(self, text="", bg=_BG, fg="#f38ba8", font=("Segoe UI", 9))
        self._status.pack(pady=(0, 4))

        bf = tk.Frame(self, bg=_BG)
        bf.pack(fill="x", padx=14, pady=(0, 10))
        tk.Button(bf, text="Cancel", command=self.destroy,
                  bg=_EB, fg=_FG, font=("Segoe UI", 9),
                  relief="flat", padx=10, pady=4).pack(side="right", padx=4)
        tk.Button(bf, text="Send", command=self._send,
                  bg="#89b4fa", fg=_BG, font=("Segoe UI", 9, "bold"),
                  relief="flat", padx=14, pady=4).pack(side="right")

    def _field(self, parent, label, default, readonly=False):
        row = tk.Frame(parent, bg=_BG)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label, width=10, anchor="w",
                 bg=_BG, fg=_FG, font=("Segoe UI", 9)).pack(side="left")
        var = tk.StringVar(value=default)
        tk.Entry(row, textvariable=var, bg=_EB, fg=_FG, insertbackground=_FG,
                 relief="flat", font=("Segoe UI", 9),
                 state="readonly" if readonly else "normal").pack(side="left", fill="x", expand=True)
        self._fields[label.lower()] = var

    def _body(self, parent, default):
        tk.Label(parent, text="Body", anchor="w",
                 bg=_BG, fg=_FG, font=("Segoe UI", 9)).pack(fill="x", pady=(6, 2))
        txt = tk.Text(parent, bg=_EB, fg=_FG, insertbackground=_FG,
                      relief="flat", font=("Segoe UI", 9), wrap="word", height=10)
        txt.insert("1.0", default)
        txt.pack(fill="both", expand=True)
        self._fields["body"] = txt

    def _send(self):
        body_w = self._fields.get("body")
        body   = body_w.get("1.0", "end").strip() if body_w else ""

        if self.mode == "post":
            title = self._fields.get("title", tk.StringVar()).get().strip()
            if not title:
                self._status.config(text="Title is required.")
                return

        self._status.config(text="Sending…", fg="#89b4fa")
        self.update()

        result = {"err": None, "done": False}

        def _do():
            try:
                if self.mode == "dm":
                    author  = self.row.get("author", "").lstrip("u/")
                    subject = self._fields.get("subject", tk.StringVar()).get()
                    ssa_reddit.send_dm(author, subject, body)
                else:
                    sub   = self._fields.get("subreddit", tk.StringVar()).get()
                    title = self._fields.get("title", tk.StringVar()).get().strip()
                    ssa_reddit.submit_post(sub, title, body)
                result["done"] = True
            except Exception as e:
                result["err"] = str(e)

        t = threading.Thread(target=_do, daemon=True)
        t.start()

        def _wait(elapsed=0):
            if result["done"]:
                self.destroy()
            elif result["err"]:
                self._status.config(text=result["err"], fg="#f38ba8")
            elif elapsed >= 30000:
                self._status.config(text="Timed out — check credentials and try again.", fg="#f38ba8")
            else:
                self.after(200, lambda: _wait(elapsed + 200))

        self.after(200, lambda: _wait(200))


class ShopifySetupDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Shopify API Setup")
        self.geometry("500x280")
        self.configure(bg=_BG)
        self.resizable(False, False)
        self.grab_set()
        self._build()

    def _build(self):
        tk.Label(self, text="Shopify API Setup", font=("Segoe UI", 13, "bold"),
                 bg=_BG, fg=_FG).pack(pady=(16, 2))
        tk.Label(self,
                 text="Get your API credentials from Shopify admin • Apps and integrations • Develop apps",
                 font=("Segoe UI", 8), bg=_BG, fg="#6c7086", wraplength=460).pack(pady=(0, 10))

        fields = {}
        for label, key, show in [("Shop URL", "shopify_shop_url", ""),
                                  ("Access Token", "shopify_access_token", "•")]:
            row = tk.Frame(self, bg=_BG)
            row.pack(fill="x", padx=20, pady=4)
            tk.Label(row, text=label, width=16, anchor="w",
                     bg=_BG, fg=_FG, font=("Segoe UI", 9)).pack(side="left")
            var = tk.StringVar()
            tk.Entry(row, textvariable=var, show=show, bg=_EB, fg=_FG,
                     insertbackground=_FG, relief="flat",
                     font=("Segoe UI", 9)).pack(side="left", fill="x", expand=True)
            fields[key] = var

        creds = ssa_shopify.load_creds() or {}
        if creds:
            for k, v in creds.items():
                if k in fields:
                    fields[k].set(v or "")
        self._fields = fields

        self._status = tk.Label(self, text="", bg=_BG, fg="#f38ba8", font=("Segoe UI", 9))
        self._status.pack(pady=6)

        tk.Button(self, text="Save & Test", command=self._save,
                  bg="#89b4fa", fg=_BG, font=("Segoe UI", 9, "bold"),
                  relief="flat", padx=16, pady=5).pack()

    def _save(self):
        shop_url = self._fields["shopify_shop_url"].get().strip()
        token = self._fields["shopify_access_token"].get().strip()
        if not all([shop_url, token]):
            self._status.config(text="All fields are required.", fg="#f38ba8")
            return
        ssa_shopify.save_creds({
            "shopify_shop_url": shop_url,
            "shopify_access_token": token,
        })
        self._status.config(text="Testing…", fg="#89b4fa")
        self.update()
        try:
            result = ssa_shopify.create_draft_order([])
            if result["success"] or "No draft order ID" in result.get("error", ""):
                self._status.config(text="✓ Connected to Shopify", fg="#a6e3a1")
            else:
                self._status.config(text=f"Error: {result.get('error', 'Unknown')}", fg="#f38ba8")
        except Exception as e:
            self._status.config(text=f"Error: {e}", fg="#f38ba8")


class OrderFormDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Create Order")
        self.geometry("700x600")
        self.configure(bg=_BG)
        self.resizable(True, True)
        self.grab_set()
        self.products = []
        self.parsed_items = []
        self._queue = queue.Queue()
        self._build()
        self._check_queue()
        self._fetch_products_async()

    def _build(self):
        tk.Label(self, text="Create Order from Text", font=("Segoe UI", 13, "bold"),
                 bg=_BG, fg=_FG).pack(pady=(12, 8), padx=14)

        tk.Label(self, text="Paste order (e.g., '2x red cherry\\n1x java moss'):",
                 font=("Segoe UI", 9), bg=_BG, fg="#6c7086", anchor="w").pack(fill="x", padx=14, pady=(0, 4))

        input_frame = tk.Frame(self, bg=_BG)
        input_frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        self._input_txt = tk.Text(input_frame, bg=_EB, fg=_FG, insertbackground=_FG,
                                   relief="flat", font=("Segoe UI", 9), wrap="word", height=8)
        self._input_txt.pack(fill="both", expand=True)

        btn_frame = tk.Frame(self, bg=_BG)
        btn_frame.pack(fill="x", padx=14, pady=(0, 8))
        self._parse_btn = tk.Button(btn_frame, text="Parse Order", command=self._parse,
                  bg="#89b4fa", fg=_BG, font=("Segoe UI", 9, "bold"),
                  relief="flat", padx=14, pady=4, state="disabled")
        self._parse_btn.pack(side="left", padx=4)

        self._status = tk.Label(self, text="Loading products...", bg=_BG, fg="#89b4fa", font=("Segoe UI", 9))
        self._status.pack(pady=4)

        self._list_frame = tk.Frame(self, bg=_BG)
        self._list_frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        tk.Label(self, text="Matched Products:", font=("Segoe UI", 9),
                 bg=_BG, fg="#6c7086", anchor="w").pack(fill="x", padx=14, pady=(0, 4))

        self._match_frame = tk.Frame(self, bg=_BG)
        self._match_frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        footer = tk.Frame(self, bg=_BG)
        footer.pack(fill="x", padx=14, pady=(0, 10))
        tk.Button(footer, text="Cancel", command=self.destroy,
                  bg=_EB, fg=_FG, font=("Segoe UI", 9),
                  relief="flat", padx=10, pady=4).pack(side="right", padx=4)
        tk.Button(footer, text="Create Draft Order", command=self._create_order,
                  bg="#a6e3a1", fg=_BG, font=("Segoe UI", 9, "bold"),
                  relief="flat", padx=14, pady=4).pack(side="right")

    def _check_queue(self):
        """Check for messages from fetch thread and update UI."""
        try:
            while True:
                msg_type, data = self._queue.get_nowait()
                if msg_type == "success":
                    self._products_loaded(data)
                elif msg_type == "error":
                    self._products_failed(data)
        except queue.Empty:
            pass
        # Schedule next check
        self.after(100, self._check_queue)

    def _fetch_products_async(self):
        """Use cached products or fetch if not cached."""
        global _PRODUCT_CACHE

        # If cache has valid products, use it
        if isinstance(_PRODUCT_CACHE, list) and _PRODUCT_CACHE:
            self._products_loaded(_PRODUCT_CACHE)
            return

        def _do():
            global _PRODUCT_CACHE
            try:
                products = ssa_shopify.fetch_products_from_store()
                if products:
                    _PRODUCT_CACHE = products
                    self._queue.put(("success", products))
                else:
                    _PRODUCT_CACHE = False
                    self._queue.put(("error", "Shopify API returned no products"))
            except Exception as e:
                _PRODUCT_CACHE = False
                self._queue.put(("error", str(e)))

        t = threading.Thread(target=_do, daemon=True)
        t.start()

    def _products_loaded(self, products):
        """Callback when products finish loading."""
        if products:
            self.products = products
            self._status.config(text=f"Ready ({len(self.products)} products loaded)", fg="#a6e3a1")
            self._parse_btn.config(state="normal")
        else:
            self._status.config(text="No products found in store", fg="#f38ba8")
            self.products = []

    def _products_failed(self, error):
        """Callback when product fetch fails."""
        self._status.config(text=f"Error loading products: {error}", fg="#f38ba8")
        self.products = []

    def _parse(self):
        """Parse order input."""
        text = self._input_txt.get("1.0", "end").strip()
        if not text:
            self._status.config(text="No order text entered.", fg="#f38ba8")
            return

        self.parsed_items = parse_order_input(text)
        if not self.parsed_items:
            self._status.config(text="Could not parse order. Format: '2x product name'", fg="#f38ba8")
            return

        self._show_matches()
        self._status.config(text=f"✓ Parsed {len(self.parsed_items)} items", fg="#a6e3a1")

    def _show_matches(self):
        """Display parsed items with product selection UI."""
        for w in self._match_frame.winfo_children():
            w.destroy()

        if not self.products:
            tk.Label(self._match_frame, text="No products loaded", bg=_BG, fg="#f38ba8",
                     font=("Segoe UI", 9)).pack(pady=10)
            return

        product_lookup = {p["title"]: p for p in self.products}

        for qty, name in self.parsed_items:
            row = tk.Frame(self._match_frame, bg=_EB, relief="flat")
            row.pack(fill="x", pady=4, padx=0)

            tk.Label(row, text=f"{qty}x", width=4, bg=_EB, fg=_FG,
                     font=("Segoe UI", 9, "bold")).pack(side="left", padx=8, pady=4)

            # Fuzzy match the product name to available products
            matches = fuzzy_match_product(name, self.products, threshold=0.35)
            matched_products = [p for p, _ in matches]
            matched_names = [p["title"] for p in matched_products]

            def _on_product_change(event, row_ref=row, product_lookup=product_lookup):
                selected = event.widget.get()
                if selected in product_lookup:
                    new_product = product_lookup[selected]
                    row_ref._product_id = new_product["id"]
                    new_variants = [v for v in new_product.get("variants", [])]
                    if new_variants:
                        row_ref._variant_id.set(new_variants[0]["id"])
                        if len(new_variants) > 1:
                            variant_names = [v["title"] for v in new_variants]
                            if hasattr(row_ref, "_variant_combo"):
                                row_ref._variant_combo.destroy()
                            row_ref._variant_combo = ttk.Combobox(row_ref, values=variant_names, state="readonly", width=15)
                            row_ref._variant_combo.set(new_variants[0]["title"])
                            row_ref._variant_combo.pack(side="left", padx=4, pady=4)
                        else:
                            if hasattr(row_ref, "_variant_combo"):
                                row_ref._variant_combo.destroy()
                            row_ref._variant_label = tk.Label(row_ref, text=new_variants[0]["title"], bg=_EB, fg="#6c7086",
                                                               font=("Segoe UI", 8))
                            row_ref._variant_label.pack(side="left", padx=4, pady=4)

            row._variant_id = tk.StringVar()
            row._product_id = None
            row._quantity = qty

            combo = ttk.Combobox(row, values=matched_names, state="readonly", width=40)
            combo.pack(side="left", padx=4, pady=4)
            combo.bind("<<ComboboxSelected>>", _on_product_change)

            # Auto-select the best match if available
            if matched_names:
                combo.set(matched_names[0])
                combo.event_generate("<<ComboboxSelected>>")

    def _create_order(self):
        """Create draft order from matched products."""
        if not self.parsed_items:
            self._status.config(text="Parse order first.", fg="#f38ba8")
            return

        line_items = []
        for row in self._match_frame.winfo_children():
            if hasattr(row, "_product_id") and row._product_id:
                variant_id = row._variant_id.get()
                if variant_id:
                    line_items.append({
                        "product_id": row._product_id,
                        "variant_id": variant_id,
                        "quantity": row._quantity,
                    })

        if not line_items:
            self._status.config(text="No matched products to order.", fg="#f38ba8")
            return

        self._status.config(text="Creating draft order…", fg="#89b4fa")
        self.update()

        def _do():
            result = ssa_shopify.create_draft_order(line_items)
            self.after(0, lambda: self._order_done(result))

        threading.Thread(target=_do, daemon=True).start()

    def _order_done(self, result):
        """Handle draft order creation result."""
        if result["success"]:
            self._status.config(
                text=f"✓ Draft order created: {result['url']}", fg="#a6e3a1"
            )
            import webbrowser
            webbrowser.open(result["url"])
            self.after(2000, self.destroy)
        else:
            self._status.config(
                text=f"Error: {result['error']}", fg="#f38ba8"
            )


class Dashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SSA Order Manager")
        self.geometry("800x400")
        self.configure(bg="#1e1e2e")
        self.resizable(True, True)
        self._build_ui()

    # ── UI BUILD ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._style()

        # ── Header ──
        hdr = tk.Frame(self, bg="#181825", pady=10)
        hdr.pack(fill="x")

        tk.Label(hdr, text="SSA Reddit Monitor", font=("Segoe UI", 16, "bold"),
                 bg="#181825", fg="#cdd6f4").pack(side="left", padx=16)

        self.status_lbl = tk.Label(hdr, text="", font=("Segoe UI", 9),
                                   bg="#181825", fg="#6c7086")
        self.status_lbl.pack(side="left", padx=8)

        # Run Now button
        self.run_btn = tk.Button(hdr, text="▶  Run Now", command=self._run_now,
                                 bg="#89b4fa", fg="#1e1e2e",
                                 font=("Segoe UI", 9, "bold"),
                                 relief="flat", padx=12, pady=4, cursor="hand2")
        self.run_btn.pack(side="right", padx=16)

        # Clear & re-scan button
        tk.Button(hdr, text="↺  Full Rescan", command=self._full_rescan,
                  bg="#313244", fg="#cdd6f4",
                  font=("Segoe UI", 9), relief="flat",
                  padx=12, pady=4, cursor="hand2").pack(side="right", padx=4)

        # ── Progress bar (hidden until scan runs) ──
        self.progress = ttk.Progressbar(self, mode="indeterminate",
                                        style="Scan.Horizontal.TProgressbar")

        # ── Action toolbar ──
        act = tk.Frame(self, bg="#181825", pady=5)
        act.pack(fill="x", padx=12)

        btn_kw = dict(font=("Segoe UI", 9), relief="flat", padx=10, pady=3, cursor="hand2")
        self.reply_btn = tk.Button(act, text="💬 Reply", command=self._reply,
                                   bg=_EB, fg=_FG, state="disabled", **btn_kw)
        self.reply_btn.pack(side="left", padx=4)

        self.dm_btn = tk.Button(act, text="📨 DM Author", command=self._dm,
                                bg=_EB, fg=_FG, state="disabled", **btn_kw)
        self.dm_btn.pack(side="left", padx=4)

        tk.Button(act, text="📝 New Post", command=self._new_post,
                  bg=_EB, fg=_FG, **btn_kw).pack(side="left", padx=4)

        tk.Button(act, text="📋 Weekly Post", command=self._weekly_post,
                  bg="#313244", fg="#cba6f7", **btn_kw).pack(side="left", padx=4)

        tk.Button(act, text="📦 Create Order", command=self._create_order,
                  bg=_EB, fg=_FG, **btn_kw).pack(side="left", padx=4)

        tk.Button(act, text="⚙ Reddit Setup", command=self._setup,
                  bg=_EB, fg="#6c7086", **btn_kw).pack(side="right", padx=4)

        tk.Button(act, text="⚙ Shopify Setup", command=self._shopify_setup,
                  bg=_EB, fg="#6c7086", **btn_kw).pack(side="right", padx=4)

        # ── Filter bar ──
        bar = tk.Frame(self, bg="#1e1e2e", pady=6)
        bar.pack(fill="x", padx=12)

        tk.Label(bar, text="Filter:", bg="#1e1e2e", fg="#6c7086",
                 font=("Segoe UI", 9)).pack(side="left")

        for label, value in [("All", "all"), ("🎯 Direct SSA", "direct"),
                              ("🛒 Leads", "leads"), ("⚠ Negative", "neg"),
                              ("✓ Positive", "pos"), ("My Posts", "own")]:
            tk.Radiobutton(bar, text=label, variable=self._filter, value=value,
                           command=self.refresh_table,
                           bg="#1e1e2e", fg="#cdd6f4", selectcolor="#313244",
                           activebackground="#1e1e2e", activeforeground="#cdd6f4",
                           font=("Segoe UI", 9)).pack(side="left", padx=8)

        # Search box
        tk.Label(bar, text="Search:", bg="#1e1e2e", fg="#6c7086",
                 font=("Segoe UI", 9)).pack(side="left", padx=(20, 4))
        tk.Entry(bar, textvariable=self._search_var, bg="#313244", fg="#cdd6f4",
                 insertbackground="#cdd6f4", relief="flat", width=24,
                 font=("Segoe UI", 9)).pack(side="left")

        # ── Table ──
        cols = ("type", "date", "subreddit", "author", "title", "score", "url")
        frame = tk.Frame(self, bg="#1e1e2e")
        frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        self.tree = ttk.Treeview(frame, columns=cols, show="headings",
                                 selectmode="browse")

        self.tree.heading("type",      text="Type")
        self.tree.heading("date",      text="Date (CDT)")
        self.tree.heading("subreddit", text="Subreddit")
        self.tree.heading("author",    text="Author")
        self.tree.heading("title",     text="Title / Content")
        self.tree.heading("score",     text="Score")
        self.tree.heading("url",       text="URL")

        self.tree.column("type",      width=70,  stretch=False)
        self.tree.column("date",      width=155, stretch=False)
        self.tree.column("subreddit", width=110, stretch=False)
        self.tree.column("author",    width=110, stretch=False)
        self.tree.column("title",     width=460)
        self.tree.column("score",     width=55,  stretch=False)
        self.tree.column("url",       width=0,   stretch=False)  # hidden

        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)

        self.tree.bind("<Double-1>",        self._open_url)
        self.tree.bind("<Return>",          self._open_url)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # ── Footer ──
        ft = tk.Frame(self, bg="#181825", pady=5)
        ft.pack(fill="x")
        self.count_lbl = tk.Label(ft, text="", bg="#181825", fg="#6c7086",
                                  font=("Segoe UI", 9))
        self.count_lbl.pack(side="left", padx=16)
        tk.Label(ft, text="Double-click any row to open in browser",
                 bg="#181825", fg="#45475a",
                 font=("Segoe UI", 8)).pack(side="right", padx=16)

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Treeview",
                         background="#1e1e2e", foreground="#cdd6f4",
                         fieldbackground="#1e1e2e", rowheight=24,
                         font=("Segoe UI", 9))
        style.configure("Treeview.Heading",
                         background="#313244", foreground="#cdd6f4",
                         font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", "#45475a")])
        style.configure("Scan.Horizontal.TProgressbar",
                         troughcolor="#313244", background="#89b4fa",
                         thickness=4)

    # ── DATA ─────────────────────────────────────────────────────────────────

    def _all_rows(self):
        posts, comments = load_results()
        rows = []
        for p in posts:
            query  = p.get("_query", "")
            if query.lower() not in EXACT_BRAND_QUERIES:
                if p.get("subreddit", "").lower() not in AQUATICS_SUBS:
                    continue
            title     = (p.get("title") or "").replace("&amp;", "&")
            selftext  = (p.get("selftext") or "").replace("&amp;", "&")
            full_text = title + " " + selftext
            author    = p.get("author", "")
            own       = is_own_post(author)
            rows.append({
                "kind":      "post",
                "epoch":     p.get("created_utc", 0),
                "subreddit": p.get("subreddit", ""),
                "author":    author,
                "title":     title,
                "score":     p.get("score", 0),
                "url":       reddit_url(p),
                "neg":       not own and is_negative(full_text),
                "pos":       not own and is_positive(full_text),
                "own":       own,
                "direct":    _is_direct(query, full_text),
                "buying":    is_buying_intent(query, title),
                "query":     query,
            })
        for c in comments:
            query  = c.get("_query", "")
            if query.lower() not in EXACT_BRAND_QUERIES:
                if c.get("subreddit", "").lower() not in AQUATICS_SUBS:
                    continue
            body       = (c.get("body") or "").replace("&amp;", "&")
            link_title = (c.get("link_title") or "").replace("&amp;", "&")
            full_text  = body + " " + link_title
            display    = body[:120] or link_title[:120] or reddit_url(c)
            author     = c.get("author", "")
            own        = is_own_post(author)
            rows.append({
                "kind":      "comment",
                "epoch":     c.get("created_utc", 0),
                "subreddit": c.get("subreddit", ""),
                "author":    author,
                "title":     display,
                "score":     c.get("score", 0),
                "url":       reddit_url(c, "comment"),
                "neg":       not own and is_negative(full_text),
                "pos":       not own and is_positive(full_text),
                "own":       own,
                "direct":    _is_direct(query, full_text),
                "buying":    is_buying_intent(query, full_text),
                "query":     query,
            })
        rows.sort(key=lambda r: r["epoch"], reverse=True)
        return rows

    def refresh_table(self, *_):
        filt   = self._filter.get()
        query  = self._search_var.get().lower()
        rows   = self._all_rows()
        self.tree.delete(*self.tree.get_children())

        shown = 0
        for r in rows:
            if filt == "direct" and not r["direct"]:
                continue
            if filt == "leads" and not r["buying"]:
                continue
            if filt == "neg" and not r["neg"]:
                continue
            if filt == "pos" and not r["pos"]:
                continue
            if filt == "own" and not r["own"]:
                continue
            if query and query not in (r["title"] + r["subreddit"] + r["author"]).lower():
                continue

            post_id = _extract_post_id(r["url"])
            if post_id and post_id in self._replied:
                continue
            if r["neg"]:
                tag = "neg"
            elif r["own"]:
                tag = "own"
            elif r["buying"]:
                tag = "lead"
            else:
                tag = "normal"
            self.tree.insert("", "end", values=(
                r["kind"].upper(),
                fmt_time(r["epoch"]),
                "r/" + r["subreddit"],
                "u/" + r["author"],
                r["title"],
                r["score"],
                r["url"],
            ), tags=(tag,))
            shown += 1

        self.tree.tag_configure("neg",  foreground="#f38ba8")
        self.tree.tag_configure("own",     foreground="#a6e3a1")
        self.tree.tag_configure("lead",    foreground="#f9e2af")
        self.tree.tag_configure("normal",  foreground="#cdd6f4")

        mtime = ""
        if os.path.exists(RESULTS_FILE):
            t = os.path.getmtime(RESULTS_FILE)
            mtime = f"  •  Last scan: {fmt_time(t)}"
        self.status_lbl.config(text=mtime)
        self.count_lbl.config(text=f"Showing {shown} of {len(rows)} results")

    # ── ACTIONS ──────────────────────────────────────────────────────────────

    def _open_url(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        url = self.tree.item(sel[0], "values")[6]
        if url:
            webbrowser.open(url)

    def _run_now(self):
        if self._running:
            return
        self._running = True
        self.run_btn.config(text="Running…", state="disabled", bg="#6c7086")
        self.progress.pack(fill="x")
        self.progress.start(12)
        self.after(100, self._do_run)

    def _do_run(self):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        subprocess.Popen([PYTHON, NOTIFY_SCRIPT], env=env,
                         creationflags=subprocess.CREATE_NO_WINDOW)
        self.after(35000, self._run_done)

    def _run_done(self):
        self._running = False
        self.progress.stop()
        self.progress.pack_forget()
        self.run_btn.config(text="▶  Run Now", state="normal", bg="#89b4fa")
        self.refresh_table()
        self.after(1000, self._check_replies)

    def _full_rescan(self):
        if os.path.exists(SEEN_FILE):
            os.remove(SEEN_FILE)
        self._run_now()

    def _schedule_auto_refresh(self):
        self.refresh_table()
        self.after(60_000, self._schedule_auto_refresh)

    # ── REDDIT ACTIONS ────────────────────────────────────────────────────────

    def _on_select(self, _=None):
        has = bool(self.tree.selection())
        self.reply_btn.config(state="normal" if has else "disabled")
        self.dm_btn.config(state="normal" if has else "disabled")

    def _get_selected(self):
        sel = self.tree.selection()
        if not sel:
            return None
        v = self.tree.item(sel[0], "values")
        return {"kind": v[0], "subreddit": v[2], "author": v[3],
                "title": v[4], "url": v[6]}

    def _reply(self):
        row = self._get_selected()
        if row:
            ReplyDialog(self, row)

    def _dm(self):
        row = self._get_selected()
        if row:
            ComposeDialog(self, "dm", row)

    def _new_post(self):
        ComposeDialog(self, "post")

    def _weekly_post(self):
        script = os.path.join(_HERE, "ssa_weekly_post.py")
        self.status_lbl.config(text="Opening weekly post preview…", fg="#cba6f7")
        def _run():
            subprocess.Popen([PYTHON, script])
            self.after(2000, lambda: self.status_lbl.config(text="", fg="#6c7086"))
        threading.Thread(target=_run, daemon=True).start()

    def _check_replies(self):
        if self._checking:
            return
        rows = self._all_rows()
        post_ids = list({_extract_post_id(r["url"]) for r in rows
                         if _extract_post_id(r["url"]) and _extract_post_id(r["url"]) not in self._replied})
        if not post_ids:
            return
        self._checking = True

        def _run():
            for pid in post_ids:
                result = _check_post_replied(pid)
                if result is True:
                    self._replied.add(pid)
                    save_replied(self._replied)
                    self.after(0, self.refresh_table)
                time.sleep(1.1)
            self.after(0, _done)

        def _done():
            self._checking = False
            self.refresh_table()

        threading.Thread(target=_run, daemon=True).start()

    def _setup(self):
        CredentialsDialog(self)

    def _shopify_setup(self):
        ShopifySetupDialog(self)

    def _create_order(self):
        OrderFormDialog(self)


if __name__ == "__main__":
    app = Dashboard()
    app.mainloop()
