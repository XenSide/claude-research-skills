"""
On-demand Reddit reader for Claude Code.
Uses curl_cffi with browser impersonation to read public Reddit pages.

  python reddit.py search "query" [--sub NAME] [--sort relevance|hot|top|new|comments] [--time all|year|month|week|day|hour] [--limit N]
  python reddit.py read URL
  python reddit.py refresh
"""
import argparse
import ctypes
import ctypes.wintypes
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

from curl_cffi import requests as cffi_requests

IMPERSONATE = "chrome124"
HEADERS = {"Accept": "application/json", "Accept-Language": "en-US,en;q=0.9"}
MAX_COMMENTS = 40
MAX_REPLY_DEPTH = 2
MAX_REPLIES = 3
COOKIE_ENC = Path(__file__).with_name("cookie.enc")
LOGIN_URL = "https://old.reddit.com/login"
LOGIN_WAIT = 75
FIREFOX_PROFILE_ROOTS = (
    r"%APPDATA%\Mozilla\Firefox\Profiles",
    r"%LOCALAPPDATA%\Packages\Mozilla.Firefox_n80bbvh6b1yt2\LocalCache\Roaming\Mozilla\Firefox\Profiles",
)
# Cookie hosts a browser would send to old.reddit.com.
COOKIE_HOSTS = (".reddit.com", "old.reddit.com", ".old.reddit.com")
_refresh_attempted = False

# --- DPAPI encrypt/decrypt (Windows only, tied to current user) ---

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]

_crypt32 = ctypes.windll.crypt32
_kernel32 = ctypes.windll.kernel32


def _dpapi_encrypt(data: bytes) -> bytes:
    inp = _DATA_BLOB(len(data), ctypes.create_string_buffer(data, len(data)))
    out = _DATA_BLOB()
    if not _crypt32.CryptProtectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("CryptProtectData failed")
    result = ctypes.string_at(out.pbData, out.cbData)
    _kernel32.LocalFree(out.pbData)
    return result


def _dpapi_decrypt(data: bytes) -> bytes:
    inp = _DATA_BLOB(len(data), ctypes.create_string_buffer(data, len(data)))
    out = _DATA_BLOB()
    if not _crypt32.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("CryptUnprotectData failed")
    result = ctypes.string_at(out.pbData, out.cbData)
    _kernel32.LocalFree(out.pbData)
    return result


# --- Session refresh from Firefox ---
# Firefox only: Chrome/Edge lock cookies with app-bound encryption that outside tools can't decrypt.

def _stop_if_blocked(resp) -> None:
    # Reddit's bot defence. Refreshing the session or retrying only makes it worse, so stop and let the user decide.
    text = resp.text.lower() if "html" in resp.headers.get("content-type", "") else ""
    if resp.status_code == 429 or (resp.status_code == 403 and
                                   ("blocked by network security" in text or "captcha" in text)):
        sys.exit("Reddit is blocking these requests (rate limit, network-security block or CAPTCHA). "
                 "Stop using the reddit skill for now and tell the user; don't retry or work around it. "
                 "Blocks like this usually lift after a while.")


def _logged_in(cookie: str) -> bool:
    resp = cffi_requests.get("https://old.reddit.com/api/me.json", impersonate=IMPERSONATE,
                             headers={**HEADERS, "Cookie": cookie}, timeout=15)
    _stop_if_blocked(resp)
    try:
        return resp.status_code == 200 and "name" in resp.json().get("data", {})
    except ValueError:
        return False


def _firefox_cookie_db() -> Path:
    # Profile discovery adapted from yt-dlp (public domain).
    # shortcut: picks the most recently written profile; add a --profile flag if someone uses several at once.
    dbs = [db for root in FIREFOX_PROFILE_ROOTS for db in Path(os.path.expandvars(root)).glob("*/cookies.sqlite")]
    if not dbs:
        sys.exit("Couldn't find a Firefox profile. Install Firefox and log in to Reddit there.")

    def last_write(db: Path) -> float:
        return max(p.stat().st_mtime for p in (db, db.with_name(db.name + "-wal")) if p.exists())

    return max(dbs, key=last_write)


def _firefox_reddit_cookies() -> dict[str, str]:
    db = _firefox_cookie_db()
    with tempfile.TemporaryDirectory() as tmp:
        # Firefox locks the database and keeps recent writes (like a fresh login) in the -wal file, so copy both.
        for suffix in ("", "-wal"):
            src = db.with_name(db.name + suffix)
            if src.exists():
                shutil.copy(src, Path(tmp) / f"cookies.sqlite{suffix}")
        conn = sqlite3.connect(Path(tmp) / "cookies.sqlite")
        try:
            schema = conn.execute("PRAGMA user_version").fetchone()[0]
            rows = conn.execute(
                "SELECT name, value, expiry FROM moz_cookies WHERE host IN (?, ?, ?) "
                "AND NOT INSTR(originAttributes, 'userContextId=')", COOKIE_HOSTS).fetchall()
        finally:
            conn.close()
    # Firefox 142+ (schema 16) stores expiry in milliseconds.
    scale = 1000 if schema >= 16 else 1
    now = time.time()
    return {name: value for name, value, expiry in rows if not expiry or expiry / scale > now}


def _firefox_session() -> str | None:
    """Cookie header for Firefox's Reddit session, or None if it isn't logged in."""
    try:
        cookies = _firefox_reddit_cookies()
    except sqlite3.DatabaseError:
        return None  # copied while Firefox was mid-write; the next poll retries
    if "reddit_session" not in cookies:
        return None
    cookie = "; ".join(f"{name}={value}" for name, value in cookies.items())
    return cookie if _logged_in(cookie) else None


def refresh() -> str:
    cookie = _firefox_session()
    if not cookie:
        # "start firefox" resolves through App Paths, so this opens Firefox even if it isn't the default browser.
        subprocess.Popen(["cmd", "/c", "start", "", "firefox", LOGIN_URL])
        print(f"Not logged in to Reddit in Firefox. Opened the login page; waiting up to {LOGIN_WAIT}s...",
              file=sys.stderr)
        deadline = time.time() + LOGIN_WAIT
        while not cookie and time.time() < deadline:
            time.sleep(5)
            cookie = _firefox_session()
        if not cookie:
            sys.exit("No logged-in Reddit session in Firefox. Log in there, then run: python reddit.py refresh")

    COOKIE_ENC.write_bytes(_dpapi_encrypt(cookie.encode("utf-8")))
    return "OK: Reddit session from Firefox saved (DPAPI-encrypted)"


# --- HTTP ---

def _headers() -> dict:
    if not COOKIE_ENC.exists():
        print(refresh(), file=sys.stderr)
    try:
        cookie = _dpapi_decrypt(COOKIE_ENC.read_bytes()).decode("utf-8")
    except OSError:
        sys.exit("Cannot decrypt cookie.enc (saved by another Windows user?). Run: python reddit.py refresh")
    return {**HEADERS, "Cookie": cookie}


def _session_rejected(resp) -> bool:
    # A missing session redirects to /login; an invalid or expired one gets 401/403.
    return "/login" in resp.url or resp.status_code in (401, 403)


def _get(url: str, **kwargs):
    global _refresh_attempted
    resp = cffi_requests.get(url, impersonate=IMPERSONATE, headers=_headers(), timeout=15, **kwargs)
    _stop_if_blocked(resp)
    if _session_rejected(resp) and not _refresh_attempted:
        _refresh_attempted = True
        print("Reddit rejected the saved session, refreshing from Firefox...", file=sys.stderr)
        print(refresh(), file=sys.stderr)
        resp = cffi_requests.get(url, impersonate=IMPERSONATE, headers=_headers(), timeout=15, **kwargs)
        _stop_if_blocked(resp)
    if _session_rejected(resp):
        sys.exit(f"Reddit still rejects the session after refresh (HTTP {resp.status_code}). "
                 f"Log in to Reddit in Firefox and retry.")
    if resp.status_code != 200:
        sys.exit(f"Reddit returned HTTP {resp.status_code} for {resp.url}")
    return resp.json()


def _clean(text: str | None) -> str:
    if not text:
        return ""
    # Reddit sometimes double-escapes entities (a literal "&amp;#x200B;" in snippets).
    text = unescape(unescape(text)).replace("​", "")
    if "mass deleted and anonymized with Redact" in text or text.strip() in ("[deleted]", "[removed]"):
        return "[deleted]"
    text = re.sub(r"!\[gif\]\([^)]*\)", "", text)
    text = re.sub(r"!\[img\]\([^)]*\)", "[image]", text)
    text = re.sub(r"\[[^\]]*\]\(https?://(?:preview|i)\.redd\.it/[^)]*\)", "[image]", text)
    text = re.sub(r"https?://(?:preview|i)\.redd\.it/[^\s)]+", "[image]", text)
    return text.strip()


def _date(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


# --- Commands ---

def search(query: str, sub: str, sort: str, time_filter: str, limit: int) -> str:
    params = {"q": query, "sort": sort, "t": time_filter, "limit": str(max(1, min(25, limit)))}
    if sub:
        url = f"https://old.reddit.com/r/{sub}/search.json"
        params["restrict_sr"] = "on"
    else:
        url = "https://old.reddit.com/search.json"

    children = _get(url, params=params).get("data", {}).get("children", [])
    if not children:
        return "No results."

    out = []
    for i, child in enumerate(children, 1):
        d = child["data"]
        out.append(f"{i}. {_clean(d.get('title'))}")
        out.append(f"   r/{d.get('subreddit', '')} | {d.get('score', 0)} pts | "
                   f"{d.get('num_comments', 0)} comments | {_date(d.get('created_utc', 0))}")
        out.append(f"   https://old.reddit.com{d.get('permalink', '')}")
        snippet = _clean(d.get("selftext"))[:300].replace("\n", " ")
        if snippet:
            out.append(f"   {snippet}")
        elif not d.get("is_self"):
            out.append(f"   link: {d.get('url', '')}")
        out.append("")
    return "\n".join(out)


def _flatten(node: dict, depth: int = 0) -> list[dict]:
    if node.get("kind") != "t1":
        return []
    d = node["data"]
    body = _clean(d.get("body"))
    out = []
    if body not in ("", "[deleted]"):
        out.append({"author": d.get("author", "[deleted]"), "score": d.get("score", 0),
                    "depth": depth, "body": body})
    replies = d.get("replies")
    # Cap reply chains so one long argument doesn't use up the comment budget meant for distinct opinions.
    if isinstance(replies, dict) and depth < MAX_REPLY_DEPTH:
        kids = [c for c in replies.get("data", {}).get("children", []) if c.get("kind") == "t1"]
        for child in kids[:MAX_REPLIES]:
            out.extend(_flatten(child, depth + 1))
    return out


def to_json_url(url: str) -> str:
    url = re.sub(r"^https?://(www\.|new\.|old\.)?reddit\.com", "https://old.reddit.com", url.strip())
    url = url.split("?")[0].rstrip("/")
    if not url.endswith(".json"):
        url += ".json"
    return url


def read(url: str) -> str:
    data = _get(to_json_url(url), params={"sort": "top", "limit": "200"})
    p = data[0]["data"]["children"][0]["data"]
    comments = []
    for child in data[1]["data"]["children"]:
        comments.extend(_flatten(child))
    comments = comments[:MAX_COMMENTS]

    out = [f"# {_clean(p.get('title'))}",
           f"r/{p.get('subreddit', '')} | u/{p.get('author', '[deleted]')} | {p.get('score', 0)} pts | "
           f"{p.get('num_comments', 0)} comments | {_date(p.get('created_utc', 0))}", ""]
    selftext = _clean(p.get("selftext"))
    if selftext:
        out += [selftext, ""]
    elif not p.get("is_self"):
        out += [f"link: {p.get('url', '')}", ""]
    out += ["---", f"## Top comments ({len(comments)})", ""]
    for c in comments:
        pad = "  " * c["depth"]
        out.append(f"{pad}u/{c['author']} ({c['score']} pts)")
        out.append(pad + "  " + c["body"].replace("\n", "\n" + pad + "  "))
        out.append("")
    return "\n".join(out)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Search and read public Reddit threads.")
    sp = ap.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("search")
    s.add_argument("query")
    s.add_argument("--sub", default="")
    s.add_argument("--sort", default="relevance", choices=["relevance", "hot", "top", "new", "comments"])
    s.add_argument("--time", default="all", choices=["all", "year", "month", "week", "day", "hour"])
    s.add_argument("--limit", type=int, default=10)

    r = sp.add_parser("read")
    r.add_argument("url")

    sp.add_parser("refresh")

    a = ap.parse_args()
    if a.cmd == "search":
        print(search(a.query, a.sub, a.sort, a.time, a.limit))
    elif a.cmd == "read":
        print(read(a.url))
    else:
        print(refresh())


if __name__ == "__main__":
    main()
