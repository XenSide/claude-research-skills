"""YouTube research helper for Claude Code: search, search-transcripts, read, frames.

Uses yt-dlp (via uvx, no install) and ffmpeg. Stdlib only.
  python yt.py search "query" [-n 8]
  python yt.py search-transcripts "query" ["query2" ...] --grep "regex" ["regex2" ...] [-n 10]
  python yt.py read <url|id>
  python yt.py frames <url|id> --at 1:23 4:56   |   --every 60
"""
import argparse, json, os, re, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CACHE = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "yt-skill"
INLINE_LIMIT = 20000  # Bash tool output truncates at 30k chars
MAX_FRAMES = 20
NON_SPEECH = re.compile(r"\[[^\]]*\]|\bthank you\b|\bforeign\b", re.I)
SPEECH_WORDS_PER_MIN = 15  # normal narration is 120-160


def ytdlp(*args):
    base = ["--from", "yt-dlp[default]", "yt-dlp", "--js-runtimes", "node", "--encoding", "utf-8", "--no-warnings"]
    for refresh in ([], ["--refresh-package", "yt-dlp"]):  # YouTube breaks old yt-dlp; retry once on latest
        r = subprocess.run(["uvx", *refresh, *base, *args], capture_output=True, encoding="utf-8", errors="replace")
        if r.returncode == 0:
            return r.stdout
    sys.exit(f"yt-dlp failed:\n{r.stderr.strip()[-2000:]}")


def video_id(s):
    m = re.search(r"(?:v=|youtu\.be/|shorts/|live/|embed/)([\w-]{11})", s) or re.fullmatch(r"([\w-]{11})", s)
    if not m:
        sys.exit(f"not a YouTube video URL or id: {s}")
    return m.group(1)


def ts(sec):
    sec = int(sec)
    return f"{sec // 3600}:{sec // 60 % 60:02}:{sec % 60:02}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02}"


def parse_ts(s):
    sec = 0
    for part in s.split(":"):
        sec = sec * 60 + float(part)
    return sec


def info(vid):
    d = CACHE / vid
    f = d / f"{vid}.info.json"
    if not f.exists():
        ytdlp("--skip-download", "--write-info-json", "-o", str(d / "%(id)s.%(ext)s"), f"https://www.youtube.com/watch?v={vid}")
    return d, json.loads(f.read_text(encoding="utf-8"))


def original_lang(meta):
    # YouTube marks the original audio track even when the video's declared language is wrong.
    for f in meta.get("formats") or []:
        if f.get("language") and "original" in (f.get("format_note") or ""):
            return f["language"].split("-")[0]
    return (meta.get("language") or "").split("-")[0]


def pick_track(meta):
    """(track, kind, translated): a track in the original language if there is one, else the best translation."""
    manual = [l for l in meta.get("subtitles") or {} if l != "live_chat"]
    auto = list(meta.get("automatic_captions") or {})
    lang = original_lang(meta)
    base = lambda l: l.split("-")[0]
    # Every auto track except "-orig" is a machine translation; AI-dubbed videos also add one "-orig" per dub language.
    for pool, pred, kind in (
        (manual, lambda l: base(l) == lang, "manual"),
        (auto, lambda l: l.endswith("-orig") and base(l) == lang, "auto"),
        (manual, lambda l: base(l) == "en", "manual"),
        (auto, lambda l: l == lang, "auto"),
        (auto, lambda l: l == "en-orig", "auto"),
        (auto, lambda l: l == "en", "auto"),
        (auto, lambda l: l.endswith("-orig"), "auto"),
        (manual, lambda l: True, "manual"),
    ):
        for l in pool:
            if pred(l):
                translated = (kind == "auto" and not l.endswith("-orig")) or bool(lang and base(l) != lang)
                return l, kind, translated
    return None, None, False


def build_md(vid):
    """Cached header + chapters + description + '[m:ss]' transcript paragraphs."""
    d, meta = info(vid)
    out = d / f"{vid}.md"
    track, kind, translated = pick_track(meta)
    note = ", translated from the original language, may be inaccurate" if translated else ""
    captions = f"captions: {track} ({kind}{note})" if track else "captions: NONE"
    # Rebuild transcripts cached by a version that picked a different track.
    if not out.exists() or captions not in out.read_text(encoding="utf-8"):
        transcript = []
        if track:
            sub = d / f"{vid}.{track}.json3"
            if not sub.exists():
                flag = "--write-subs" if kind == "manual" else "--write-auto-subs"
                ytdlp("--load-info-json", str(d / f"{vid}.info.json"), "--skip-download", flag,
                      "--sub-langs", track, "--sub-format", "json3", "-o", str(d / "%(id)s.%(ext)s"))
            transcript = paragraphs(json.loads(sub.read_text(encoding="utf-8")).get("events", []))
            # Music-only videos get auto captions like "[Music] thank you [Music] foreign" that look like a transcript.
            spoken = len(NON_SPEECH.sub(" ", " ".join(p.partition("] ")[2] for p in transcript)).split())
            if spoken < SPEECH_WORDS_PER_MIN * max(meta.get("duration") or 0, 60) / 60:
                captions += f", almost no speech ({spoken} words): likely music-only, use frames --every"
        lines = [
            f"# {meta.get('title')}",
            f"{meta.get('channel')} | {meta.get('upload_date')} | {ts(meta.get('duration') or 0)} | "
            f"{meta.get('view_count')} views | https://youtu.be/{vid}",
            captions,
        ]
        if meta.get("chapters"):
            lines += ["", "## Chapters"] + [f"[{ts(c['start_time'])}] {c['title']}" for c in meta["chapters"]]
        lines += ["", "## Description", (meta.get("description") or "")[:3000], "", "## Transcript", *transcript]
        out.write_text("\n".join(lines), encoding="utf-8")
    return out


def read(vid):
    out = build_md(vid)
    text = out.read_text(encoding="utf-8")
    if len(text) <= INLINE_LIMIT:
        print(text)
    else:
        head = text.split("## Description")[0]
        print(f"{head}\nFull transcript ({len(text.split())} words) is too long to print: {out}\n"
              "Read it with offset/limit or Grep it for keywords.")
    if "captions: NONE" in text:
        sys.exit("no captions available for this video; use frames or the description instead")


def anchor_short_words(pattern):
    """'ram|led' also hits 'program' and 'called'; wrap plain words of 3 letters or fewer in \\b."""
    parts = pattern.split("|")
    if not all(re.fullmatch(r"\w+", p) for p in parts):
        return pattern
    return "|".join(rf"\b{p}\b" if len(p) <= 3 else p for p in parts)


def search_transcripts(queries, n, patterns, shown=5):
    """Search YouTube, fetch the top transcripts in parallel, grep them, print timestamped links."""
    titles = {}
    for q in queries:
        for line in ytdlp("--flat-playlist", "--print", "%(id)s\t%(title)s | %(channel)s", f"ytsearch{n}:{q}").splitlines():
            vid, _, title = line.partition("\t")
            titles.setdefault(vid, title)
    anchored = [anchor_short_words(p) for p in patterns]
    if anchored != patterns:
        print("note: short words anchored so they don't match inside longer ones: "
              + ", ".join(a for a, p in zip(anchored, patterns) if a != p))
    rxs = [re.compile(p, re.I) for p in anchored]
    rx = re.compile("|".join(anchored), re.I)
    query_words = {w for q in queries for w in re.findall(r"\w+", q.lower())}
    with ThreadPoolExecutor(5) as pool:  # more parallel requests invite YouTube rate limiting
        futures = {vid: pool.submit(build_md, vid) for vid in titles}
    results = []
    for vid, fut in futures.items():
        try:
            text = fut.result().read_text(encoding="utf-8")
        except SystemExit as e:  # ytdlp() exits on failure; skip that video, keep the rest
            print(f"skipped {vid}: {str(e).splitlines()[-1][:200]}")
            continue
        body = text.partition("## Transcript")[2]
        lines = [l for l in body.splitlines() if l.startswith("[") and rx.search(l)]
        if lines:
            distinct = sum(any(r.search(l) for l in lines) for r in rxs)
            on_topic = len(query_words & set(re.findall(r"\w+", titles[vid].lower())))
            results.append((distinct, on_topic, len(lines), vid, lines))
    # Rank by patterns covered, then query words in the title (exact model/version), then hits:
    # one broad pattern shouldn't let a long video about a different product win.
    for distinct, _, count, vid, lines in sorted(results, reverse=True):
        print(f"\n## {titles[vid]} ({count} hits, {distinct}/{len(rxs)} patterns)")
        for l in lines[:shown]:
            stamp, _, para = l[1:].partition("] ")
            start = max(0, rx.search(para).start() - 150)
            print(f"https://youtu.be/{vid}?t={int(parse_ts(stamp))}  ...{para[start:start + 300]}...")
        if count > shown:
            print(f"  +{count - shown} more: read {vid}")
    print(f"\n{len(results)}/{len(titles)} videos matched")


def paragraphs(events, every=30):
    """json3 events -> '[m:ss] text' paragraphs of ~`every` seconds, so timestamps can feed `frames --at`."""
    paras, cur, start = [], [], None
    for e in events:
        text = "".join(s.get("utf8", "") for s in e.get("segs") or []).replace("\n", " ").strip()
        if not text:
            continue
        t = e.get("tStartMs", 0) / 1000
        if start is None or t - start >= every:
            if cur:
                paras.append(f"[{ts(start)}] {' '.join(cur)}")
            cur, start = [], t
        cur.append(text)
    if cur:
        paras.append(f"[{ts(start)}] {' '.join(cur)}")
    return paras


def frames(vid, at, every):
    _, meta = info(vid)
    duration = float(meta.get("duration") or 0)
    times = [parse_ts(t) for t in at or []]
    if every:
        step = max(every, duration / MAX_FRAMES)
        if step > every:
            print(f"--every {every} would exceed {MAX_FRAMES} frames; using every {int(step)}s")
        times += [i * step for i in range(int(duration // step) + 1)]
    times = sorted({int(t) for t in times if t < duration})[:MAX_FRAMES]
    d = CACHE / vid / "frames"
    d.mkdir(parents=True, exist_ok=True)
    todo = [t for t in times if not (d / f"{vid}_{t:05}.jpg").exists()]
    if todo:
        # yt-dlp fetches 1 s clips itself: handing the stream URL to ffmpeg gets 403 on many videos.
        sections = [arg for t in todo for arg in ("--download-sections", f"*{t}-{t + 1}")]
        ytdlp("-f", "bv*[height<=720][ext=mp4]/bv*[height<=720]/b", *sections,
              "-o", str(d / "clip_%(section_start)d.%(ext)s"), f"https://www.youtube.com/watch?v={vid}")
        for t in todo:
            for clip in d.glob(f"clip_{t}.*"):
                subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(clip), "-frames:v", "1",
                                "-vf", "scale=1280:-2", "-q:v", "3", str(d / f"{vid}_{t:05}.jpg")], check=False)
                clip.unlink()
    for t in times:
        f = d / f"{vid}_{t:05}.jpg"
        print(f"[{ts(t)}] {f}" if f.exists() else f"[{ts(t)}] FAILED")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("-n", type=int, default=8)
    t = sub.add_parser("read")
    t.add_argument("video")
    g = sub.add_parser("search-transcripts")
    g.add_argument("queries", nargs="+", help="one or more YouTube search queries")
    g.add_argument("--grep", nargs="+", required=True, help="regexes; a paragraph matches if any matches (case-insensitive)")
    g.add_argument("-n", type=int, default=10, help="results per query")
    f = sub.add_parser("frames")
    f.add_argument("video")
    f.add_argument("--at", nargs="+", help="timestamps like 1:23 or 1:02:03 or 83")
    f.add_argument("--every", type=float, help="seconds between frames (max %d frames)" % MAX_FRAMES)
    a = p.parse_args()
    if a.cmd == "search":
        out = ytdlp("--flat-playlist", "--print", "https://youtu.be/%(id)s | %(title)s | %(channel)s | "
                    "%(duration_string)s | %(view_count)s views", f"ytsearch{a.n}:{a.query}")
        print(out.strip() or "no results")
    elif a.cmd == "read":
        read(video_id(a.video))
    elif a.cmd == "search-transcripts":
        search_transcripts(a.queries, a.n, a.grep)
    else:
        if not (a.at or a.every):
            p.error("frames needs --at or --every")
        frames(video_id(a.video), a.at, a.every)


if __name__ == "__main__":
    main()
