# claude-research-skills

Two [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skills that let Claude read Reddit threads and YouTube videos while it researches, plus an optional hook that reminds it they exist. Windows only.

Claude's built-in WebSearch and WebFetch only see titles and snippets from Reddit and YouTube. That misses a lot: workarounds for bugs and stuck quests, owner reports, niche community knowledge, problems too new for any guide, and anything a video shows instead of writing down.

| Skill | What Claude can do with it |
|---|---|
| `reddit` | Search Reddit and read threads (post plus top comments) with your own logged-in session |
| `youtube` | Search YouTube, read transcripts, search inside the transcripts of the top results, and grab frames to look at |

The optional hook adds a short note next to every web search result saying the two skills exist. It's there because the skill descriptions alone often weren't enough for Claude to think of them.

## Requirements

- Windows, Claude Code, and Python 3.10+ on PATH as `python`
- `reddit`: Firefox, logged in to reddit.com. Chrome and Edge lock their cookies with app-bound encryption, so they can't be read.
- `youtube`: [uv](https://docs.astral.sh/uv/) (for `uvx`), Node.js and ffmpeg

The installer tells you what's missing and the `winget` command to get it.

## Install

```
git clone https://github.com/XenSide/claude-research-skills
cd claude-research-skills
python install.py
```

Use `python install.py --no-hook` to skip the reminder hook. Run the same command again to update.

What the installer changes:

- copies the skills to `~/.claude/skills/reddit` and `~/.claude/skills/youtube`, and the hook to `~/.claude/hooks/`
- installs `curl_cffi` with `pip install --user` if it's missing
- backs up `~/.claude/settings.json`, then adds:
  - allow rules for the two scripts, so they run without permission prompts
  - a deny rule so Claude can't read the saved Reddit session file
  - the WebSearch hook (unless `--no-hook`)

Start a new Claude Code session afterwards to load the skills.

## How the Reddit session works

Reddit blocks logged-out access to its data, so the skill uses your own session:

1. It reads your reddit.com cookies from Firefox's cookie database and checks them against `/api/me.json`.
2. It saves them encrypted with Windows DPAPI in `~/.claude/skills/reddit/cookie.enc`. Only your Windows account can decrypt that file.
3. When the session expires, it refreshes from Firefox on its own. If Firefox isn't logged in, it opens the Reddit login page there and waits up to 75 seconds.

Requests go only to old.reddit.com, through `curl_cffi` with a Firefox TLS fingerprint, because Reddit rejects plain HTTP clients. Everything runs on your account, so the skill tells Claude to keep it to a handful of requests per question. Many sessions searching Reddit at the same time can trip Reddit's bot defence ("You've been blocked by network security"); the script then stops and tells Claude not to retry. Whether this kind of access fits Reddit's terms is your call.

## YouTube details

The skill runs the latest yt-dlp through `uvx`, with no install. Transcripts, metadata and frames are cached in `%LOCALAPPDATA%\yt-skill`, so repeat lookups are free. Age-restricted and members-only videos aren't supported.

## Uninstall

```
python install.py --uninstall
```

This removes both skills (including the saved Reddit session), the hook, and the settings entries the installer added. The YouTube cache stays; the uninstaller prints where it is.

## Credits

The Firefox cookie reader is adapted from [yt-dlp](https://github.com/yt-dlp/yt-dlp) (public domain).

## License

[MIT](LICENSE)
