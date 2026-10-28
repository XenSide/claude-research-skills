"""Install the reddit and youtube research skills for Claude Code (Windows).

  python install.py              install or update
  python install.py --no-hook    install without the WebSearch reminder hook
  python install.py --uninstall  remove the skills, the hook, their settings and the saved Reddit session
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
CLAUDE = Path.home() / ".claude"
SETTINGS = CLAUDE / "settings.json"
SKILLS = ("reddit", "youtube")
HOOK_NAME = "research_reminder.py"
HOOK_PATH = CLAUDE / "hooks" / HOOK_NAME

# The skills tell Claude to run these exact command prefixes, so the rules match them literally.
ALLOW = [
    "Bash(python ~/.claude/skills/reddit/reddit.py:*)",
    "Bash(python ~/.claude/skills/youtube/yt.py:*)",
]
DENY = ["Read(~/.claude/skills/reddit/cookie.enc)"]
AUTO_ALLOW = [
    "Running python ~/.claude/skills/reddit/reddit.py (search/read/refresh) is allowed: the user installed it to "
    "read Reddit on demand with their own logged-in session, and it only talks to reddit.com.",
    "Running python ~/.claude/skills/youtube/yt.py (search/search-transcripts/read/frames) is allowed: the user "
    "installed it to research YouTube videos via yt-dlp, and it writes only to its own cache folder.",
]
TOOLS = {  # command: (needed by, winget package)
    "uvx": ("youtube", "astral-sh.uv"),
    "node": ("youtube", "OpenJS.NodeJS.LTS"),
    "ffmpeg": ("youtube frames", "Gyan.FFmpeg"),
}


def load_settings() -> dict:
    if not SETTINGS.exists() or not SETTINGS.read_text(encoding="utf-8").strip():
        return {}
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"{SETTINGS} isn't valid JSON ({e}); fix it first, nothing was changed.")


def save_settings(settings: dict) -> None:
    if SETTINGS.exists():
        backup = SETTINGS.with_name(f"settings.json.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(SETTINGS, backup)
        print(f"  backed up settings to {backup.name}")
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def is_our_hook(entry: dict) -> bool:
    return any(HOOK_NAME in h.get("command", "") for h in entry.get("hooks", []))


def merge_settings(settings: dict, with_hook: bool) -> None:
    perms = settings.setdefault("permissions", {})
    for key, rules in (("allow", ALLOW), ("deny", DENY)):
        lst = perms.setdefault(key, [])
        lst += [r for r in rules if r not in lst]
    # Without "$defaults", custom autoMode.allow entries replace the built-in ones.
    auto = settings.setdefault("autoMode", {}).setdefault("allow", ["$defaults"])
    auto += [r for r in AUTO_ALLOW if r not in auto]

    pre = settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
    pre[:] = [e for e in pre if not is_our_hook(e)]
    if with_hook:
        command = f'python "{HOOK_PATH.as_posix()}"'
        pre.append({"matcher": "WebSearch", "hooks": [{"type": "command", "command": command, "timeout": 10}]})


def unmerge_settings(settings: dict) -> None:
    perms = settings.get("permissions", {})
    for key, rules in (("allow", ALLOW), ("deny", DENY)):
        if key in perms:
            perms[key] = [r for r in perms[key] if r not in rules]
    auto = settings.get("autoMode", {})
    if "allow" in auto:
        auto["allow"] = [r for r in auto["allow"] if r not in AUTO_ALLOW]
    pre = settings.get("hooks", {}).get("PreToolUse")
    if pre is not None:
        pre[:] = [e for e in pre if not is_our_hook(e)]


def ensure_curl_cffi() -> None:
    # The skills run as plain `python`, so check and install with the python on PATH, not necessarily this one.
    python = shutil.which("python")
    if not python:
        print("  ! `python` isn't on PATH; the skills call it by that name. Install Python 3.10+ from python.org.")
        return
    if subprocess.run([python, "-c", "import curl_cffi"], capture_output=True).returncode == 0:
        print("  curl_cffi already installed")
        return
    print("  installing curl_cffi (needed by the reddit skill)...")
    r = subprocess.run([python, "-m", "pip", "install", "--user", "curl_cffi"], capture_output=True, text=True)
    print("  curl_cffi installed" if r.returncode == 0 else f"  ! pip failed:\n{r.stderr[-800:]}")


def check_tools() -> None:
    missing = [(cmd, need, pkg) for cmd, (need, pkg) in TOOLS.items() if not shutil.which(cmd)]
    profiles = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox" / "Profiles"
    if not profiles.is_dir():
        missing.append(("Firefox", "reddit (log in to reddit.com there)", "Mozilla.Firefox"))
    for cmd, need, pkg in missing:
        print(f"  ! {cmd} not found (needed by {need}): winget install {pkg}")
    if not missing:
        print("  uv, node, ffmpeg and a Firefox profile found")


def install(with_hook: bool) -> None:
    print("Copying files")
    for name in SKILLS:
        dst = CLAUDE / "skills" / name
        dst.mkdir(parents=True, exist_ok=True)
        for f in (REPO / "skills" / name).iterdir():
            if f.is_file():
                shutil.copy2(f, dst / f.name)  # cookie.enc isn't in the repo, so a saved session survives updates
        print(f"  {dst}")
    if with_hook:
        HOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / "hooks" / HOOK_NAME, HOOK_PATH)
        print(f"  {HOOK_PATH}")
    elif HOOK_PATH.exists():
        HOOK_PATH.unlink()

    print("Dependencies")
    ensure_curl_cffi()
    check_tools()

    print("Settings")
    settings = load_settings()
    merge_settings(settings, with_hook)
    save_settings(settings)
    print(f"  added permissions, auto mode rules{' and the WebSearch hook' if with_hook else ''} to {SETTINGS}")

    print("\nDone. Start a new Claude Code session to load the skills.")
    print("Reddit: log in to reddit.com in Firefox; the first Reddit search saves your session (DPAPI-encrypted).")


def uninstall() -> None:
    for name in SKILLS:
        d = CLAUDE / "skills" / name
        if d.exists():
            shutil.rmtree(d)  # includes cookie.enc: don't leave a session token behind
            print(f"removed {d}")
    if HOOK_PATH.exists():
        HOOK_PATH.unlink()
        print(f"removed {HOOK_PATH}")
    if SETTINGS.exists():
        settings = load_settings()
        unmerge_settings(settings)
        save_settings(settings)
        print(f"removed the skills' entries from {SETTINGS}")
    cache = Path(os.environ.get("LOCALAPPDATA", "")) / "yt-skill"
    if cache.exists():
        print(f"The YouTube cache is still at {cache}; delete it if you want the space back.")


def main() -> None:
    if os.name != "nt":
        sys.exit("These skills are Windows-only for now (the Reddit session is encrypted with Windows DPAPI).")
    if sys.version_info < (3, 10):
        sys.exit("Python 3.10 or newer is required.")
    ap = argparse.ArgumentParser(description="Install the reddit and youtube research skills for Claude Code.")
    ap.add_argument("--no-hook", action="store_true", help="skip the WebSearch reminder hook")
    ap.add_argument("--uninstall", action="store_true", help="remove everything this installer added")
    a = ap.parse_args()
    uninstall() if a.uninstall else install(with_hook=not a.no_hook)


if __name__ == "__main__":
    main()
