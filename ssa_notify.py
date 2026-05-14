#!/usr/bin/env python3
"""
SSA Reddit Monitor - with change detection and Windows toast notifications.
Runs the same searches as ssa_reddit_monitor.py but only notifies on new results.
Persists seen IDs between runs to avoid repeat alerts.
"""

import urllib.request
import urllib.parse
import urllib.error
import json
import time
import os
import subprocess
from datetime import datetime

USER_AGENT = "ssa-mention-monitor/1.0 (operated by Superior Shrimp & Aquatics)"

PYTHON    = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "python.exe")
_HERE     = os.path.dirname(os.path.abspath(__file__))
DASHBOARD = os.path.join(_HERE, "ssa_dashboard.py")
PROTOCOL  = "ssa-monitor"

QUERIES = [
    # Exact brand name
    ("superior shrimp aquatics", None),
    ("superiorshrimpaquatics",   None),
    # Username
    ("djester808",               None),
    # "superior shrimp" in targeted subs
    ("superior shrimp",          "AquaSwap"),
    ("superior shrimp",          "shrimptank"),
    ("superior shrimp",          "PlantedTank"),
    ("superior shrimp",          "Aquariums"),
    ("superior shrimp",          "duluth"),
    # "superior aquatics" in targeted subs
    ("superior aquatics",        "AquaSwap"),
    ("superior aquatics",        "shrimptank"),
    ("superior aquatics",        "Aquariums"),
    ("superior aquatics",        "PlantedTank"),
    # SSA abbreviation in shrimp-specific subs only (too noisy globally)
    ("SSA shrimp",               None),
    ("SSA",                      "shrimptank"),
    ("SSA",                      "AquaSwap"),
]

DISTINCTIVE = ["superior shrimp aquatics", "superiorshrimpaquatics", "djester808"]

# Only alert on results from these high-signal queries (avoids false positives)
HIGH_SIGNAL_QUERIES = {
    "superior shrimp aquatics",
    "superiorshrimpaquatics",
    "djester808",
    "superior aquatics",
    "superior shrimp",
    "ssa shrimp",
    "ssa",
}

OUTPUT_DIR  = _HERE
LOG_DIR     = os.path.join(_HERE, "ssa_monitor_logs")
SEEN_FILE   = os.path.join(LOG_DIR, "seen_ids.json")
RESULTS_FILE = os.path.join(LOG_DIR, "results_latest.json")
LOG_FILE    = os.path.join(LOG_DIR, "log_latest.txt")


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return json.load(f)
    return {"posts": [], "comments": []}


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f)


def register_protocol():
    """Register ssa-monitor:// URI scheme in HKCU so toast clicks open the dashboard."""
    cmd = f'"{PYTHON}" "{DASHBOARD}"'
    ps = f"""
$base = 'HKCU:\\Software\\Classes\\{PROTOCOL}'
New-Item -Path $base -Force | Out-Null
Set-ItemProperty -Path $base -Name '(Default)' -Value 'SSA Monitor'
New-ItemProperty -Path $base -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
New-Item -Path "$base\\shell\\open\\command" -Force | Out-Null
Set-ItemProperty -Path "$base\\shell\\open\\command" -Name '(Default)' -Value '{cmd}'
"""
    subprocess.run(
        ["powershell", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps],
        capture_output=True,
    )


def toast(title, body):
    """Fire a Windows toast notification that opens the dashboard on click."""
    xml = f"""<toast activationType="protocol" launch="{PROTOCOL}://">
  <visual><binding template="ToastGeneric">
    <text>{title}</text>
    <text>{body}</text>
  </binding></visual>
</toast>"""
    ps = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = [Windows.Data.Xml.Dom.XmlDocument]::new()
$xml.LoadXml('{xml}')
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('SSA Reddit Monitor').Show($toast)
"""
    subprocess.run(
        ["powershell", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps],
        capture_output=True,
    )


def fetch_json(url, retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep((attempt + 1) * 5)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(2)
                continue
            raise
    return None


def search_posts(query, subreddit=None, sort="new", limit=25, t="all"):
    q = urllib.parse.quote(query)
    if subreddit:
        url = (f"https://www.reddit.com/r/{subreddit}/search.json?"
               f"q={q}&restrict_sr=on&sort={sort}&limit={limit}&t={t}")
    else:
        url = (f"https://www.reddit.com/search.json?"
               f"q={q}&sort={sort}&limit={limit}&t={t}")
    data = fetch_json(url)
    return [c["data"] for c in data.get("data", {}).get("children", [])] if data else []


def search_comments(query, limit=25, sort="new", t="all"):
    q = urllib.parse.quote(query)
    url = (f"https://www.reddit.com/search.json?"
           f"q={q}&type=comment&sort={sort}&limit={limit}&t={t}")
    data = fetch_json(url)
    return [c["data"] for c in data.get("data", {}).get("children", [])] if data else []


def format_dt(epoch):
    dt = datetime.fromtimestamp(epoch).astimezone()
    is_dst = time.localtime(epoch).tm_isdst
    label = "CDT" if is_dst else "CST"
    return dt.strftime(f"%Y-%m-%d %H:%M {label}")


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    register_protocol()

    seen = load_seen()
    seen_post_ids    = set(seen["posts"])
    seen_comment_ids = set(seen["comments"])

    new_posts    = []  # (item, query) tuples for high-signal queries
    new_comments = []
    all_results  = {"posts": [], "comments": []}
    log_lines    = []

    def log(msg=""):
        print(msg)
        log_lines.append(msg)

    log(f"=== SSA Reddit Monitor run: {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")

    for query, sub in QUERIES:
        label = f"r/{sub}" if sub else "ALL"
        log(f"Searching posts: \"{query}\" in {label}")
        try:
            posts = search_posts(query, subreddit=sub, sort="new", limit=25)
        except Exception as e:
            log(f"  ERROR: {e}")
            time.sleep(2)
            continue

        for p in posts:
            pid = p.get("id")
            if not pid or pid in seen_post_ids:
                continue
            seen_post_ids.add(pid)
            p["_query"] = query
            all_results["posts"].append(p)
            if query in HIGH_SIGNAL_QUERIES:
                new_posts.append((p, query))
            dt = format_dt(p['created_utc']) if p.get('created_utc') else '?'
            log(f"  NEW: [{p.get('subreddit')}] {dt} — {p.get('title', '')[:80]}")

        time.sleep(2)

    for query in DISTINCTIVE:
        log(f"Searching comments: \"{query}\"")
        try:
            comments = search_comments(query, limit=25, sort="new")
        except Exception as e:
            log(f"  ERROR: {e}")
            time.sleep(2)
            continue

        for c in comments:
            cid = c.get("id")
            if not cid or cid in seen_comment_ids:
                continue
            seen_comment_ids.add(cid)
            c["_query"] = query
            all_results["comments"].append(c)
            if query in HIGH_SIGNAL_QUERIES:
                new_comments.append((c, query))
            link = (c.get('link_title') or c.get('body', '')[:60].replace('\n', ' ')
                    or f"https://reddit.com{c.get('permalink','')}")
            dt = format_dt(c['created_utc']) if c.get('created_utc') else '?'
            log(f"  NEW COMMENT: [{c.get('subreddit')}] {dt} — {link}")

        time.sleep(2)

    # Persist updated seen IDs
    save_seen({"posts": list(seen_post_ids), "comments": list(seen_comment_ids)})

    # Save results
    with open(RESULTS_FILE, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    total_new = len(new_posts) + len(new_comments)
    log(f"\nDone. {total_new} new high-signal results, "
        f"{len(all_results['posts'])} total posts, "
        f"{len(all_results['comments'])} total comments.")

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))

    # Notify if anything new
    if total_new == 0:
        return

    lines = []
    for p, q in new_posts[:5]:
        sub   = p.get("subreddit", "?")
        title = (p.get("title") or "")[:60]
        lines.append(f"r/{sub}: {title}")
    for c, q in new_comments[:3]:
        sub   = c.get("subreddit", "?")
        link  = (c.get("link_title") or c.get("body", "")[:50].replace('\n', ' '))
        lines.append(f"r/{sub} comment in: {link}")

    body = "\n".join(lines) if lines else f"{total_new} new mention(s) found"
    title = f"SSA Reddit — {total_new} new mention{'s' if total_new != 1 else ''}"

    # Escape quotes for PowerShell
    body  = body.replace('"', "'").replace('\n', ' | ')
    toast(title, body)


if __name__ == "__main__":
    main()
