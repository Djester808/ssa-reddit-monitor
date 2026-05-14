#!/usr/bin/env python3
"""
SSA Reddit Monitor — Desktop Dashboard
Run this to view mentions, filter results, and trigger manual scans.
"""

import json
import os
import re
import subprocess
import time
import tkinter as tk
from tkinter import ttk
import webbrowser
from datetime import datetime

_HERE        = os.path.dirname(os.path.abspath(__file__))
LOG_DIR      = os.path.join(_HERE, "ssa_monitor_logs")
RESULTS_FILE = os.path.join(LOG_DIR, "results_latest.json")
SEEN_FILE    = os.path.join(LOG_DIR, "seen_ids.json")
NOTIFY_SCRIPT = os.path.join(_HERE, "ssa_notify.py")
PYTHON       = os.path.join(os.environ.get("LOCALAPPDATA",""), "Microsoft", "WindowsApps", "python.exe")

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
    if query in _EXACT_QUERIES:
        return True
    return bool(re.search(r'(?<!\w)' + re.escape(query) + r'(?!\w)', text, re.IGNORECASE))

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
    "wtb", " iso ", "where to buy", "looking to buy", "want to buy",
    "looking for shrimp", "anyone selling", "recommend a seller",
    "best place to buy", "good seller", "shrimp seller",
    "where can i buy", "where can i get", "in search of",
    "who sells", "any sellers", "buying shrimp",
]

AQUATICS_WORDS = [
    "shrimp", "aquatic", "neocaridina", "caridina", "planted tank",
    "fish tank", "aquarium", "reef", "freshwater", "saltwater",
    "invertebrate", "snail", "crayfish", "dwarf shrimp", "ssa",
]

def is_buying_intent(query, text):
    if query in BUYING_QUERIES:
        return True
    t = text.lower()
    return any(w in t for w in BUYING_WORDS) and any(w in t for w in AQUATICS_WORDS)

NEG_WORDS = [
    "doa", "dead", "scam", "fraud", "avoid", "terrible", "awful", "horrible",
    "worst", "beware", "warning", "refund", "dispute", "ignored", "no response",
    "never again", "disappointed", "lied", "fake", "garbage", "trash",
    "do not", "don't", "bad experience", "poor", "blocked", "ghosted",
    "sick", "disease", "parasite", "clado", "mislabeled", "missing",
    "rude", "unprofessional", "never received", "wrong",
]

def is_negative(text):
    t = text.lower()
    return any(w in t for w in NEG_WORDS)

def is_own_post(author):
    return (author or "").lower() in ("djester808", "superiorshrimpaquatics")

def fmt_time(epoch):
    if not epoch:
        return ""
    is_dst = time.localtime(epoch).tm_isdst
    label = "CDT" if is_dst else "CST"
    return datetime.fromtimestamp(epoch).strftime(f"%Y-%m-%d %H:%M {label}")

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


class Dashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SSA Reddit Monitor")
        self.geometry("1100x680")
        self.configure(bg="#1e1e2e")
        self.resizable(True, True)
        self._running = False
        self._filter  = tk.StringVar(value="all")
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self.refresh_table())
        self._build_ui()
        self.refresh_table()
        self._schedule_auto_refresh()

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

        self.tree.bind("<Double-1>", self._open_url)
        self.tree.bind("<Return>",   self._open_url)

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
            title  = (p.get("title") or "").replace("&amp;", "&")
            author = p.get("author", "")
            neg    = is_negative(title)
            own    = is_own_post(author)
            query  = p.get("_query", "")
            rows.append({
                "kind":      "post",
                "epoch":     p.get("created_utc", 0),
                "subreddit": p.get("subreddit", ""),
                "author":    author,
                "title":     title,
                "score":     p.get("score", 0),
                "url":       reddit_url(p),
                "neg":       neg,
                "own":       own,
                "direct":    _is_direct(query, title),
                "buying":    is_buying_intent(query, title),
                "query":     query,
            })
        for c in comments:
            body   = (c.get("body") or c.get("link_title") or "").replace("&amp;", "&")
            author = c.get("author", "")
            neg    = is_negative(body)
            own    = is_own_post(author)
            query  = c.get("_query", "")
            rows.append({
                "kind":      "comment",
                "epoch":     c.get("created_utc", 0),
                "subreddit": c.get("subreddit", ""),
                "author":    author,
                "title":     body[:120] or reddit_url(c),
                "score":     c.get("score", 0),
                "url":       reddit_url(c, "comment"),
                "neg":       neg,
                "own":       own,
                "direct":    _is_direct(query, body),
                "buying":    is_buying_intent(query, body),
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
            if filt == "pos" and r["neg"]:
                continue
            if filt == "own" and not r["own"]:
                continue
            if query and query not in (r["title"] + r["subreddit"] + r["author"]).lower():
                continue

            tag = "neg" if r["neg"] else ("own" if r["own"] else ("lead" if r["buying"] else "normal"))
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

        self.tree.tag_configure("neg",    foreground="#f38ba8")
        self.tree.tag_configure("own",    foreground="#a6e3a1")
        self.tree.tag_configure("lead",   foreground="#f9e2af")
        self.tree.tag_configure("normal", foreground="#cdd6f4")

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

    def _full_rescan(self):
        if os.path.exists(SEEN_FILE):
            os.remove(SEEN_FILE)
        self._run_now()

    def _schedule_auto_refresh(self):
        self.refresh_table()
        self.after(60_000, self._schedule_auto_refresh)


if __name__ == "__main__":
    app = Dashboard()
    app.mainloop()
