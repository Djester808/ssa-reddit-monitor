#!/usr/bin/env python3
"""Reddit API wrapper for SSA Monitor — comments, DMs, posts."""

import json
import os

_HERE      = os.path.dirname(os.path.abspath(__file__))
CREDS_FILE = os.path.join(_HERE, "ssa_creds.json")
USERNAME   = "djester808"

def load_creds():
    if not os.path.exists(CREDS_FILE):
        return None
    with open(CREDS_FILE) as f:
        return json.load(f)

def save_creds(client_id, client_secret, password):
    with open(CREDS_FILE, "w") as f:
        json.dump({
            "client_id":     client_id,
            "client_secret": client_secret,
            "password":      password,
        }, f, indent=2)

def has_creds():
    return os.path.exists(CREDS_FILE)

def _get_reddit():
    try:
        import praw
    except ImportError:
        raise RuntimeError("praw not installed — run: pip install praw")
    creds = load_creds()
    if not creds:
        raise RuntimeError("No Reddit credentials. Use ⚙ Reddit Setup in the dashboard.")
    return praw.Reddit(
        client_id     = creds["client_id"],
        client_secret = creds["client_secret"],
        username      = USERNAME,
        password      = creds["password"],
        user_agent    = "ssa-monitor/1.0 by djester808",
    )

def test_auth():
    r = _get_reddit()
    return r.user.me().name

def post_comment(post_url, body):
    r = _get_reddit()
    return r.submission(url=post_url).reply(body)

def send_dm(to_user, subject, body):
    r = _get_reddit()
    r.redditor(to_user).message(subject, body)

def submit_post(subreddit, title, body):
    r = _get_reddit()
    return r.subreddit(subreddit).submit(title, selftext=body)
