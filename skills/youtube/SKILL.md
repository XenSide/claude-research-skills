---
name: youtube
description: "Search YouTube, read video transcripts and grab frames as a research source. Videos show how people actually do things: game quests, mechanics and builds, software and setup walkthroughs, repairs and hardware procedures, cooking and crafts, exercise technique, reviews, and talks. Search it in the same turn as your first web search whenever watching someone do it would improve the answer, even when an official guide exists: videos show the physical steps, menus and gotchas that guides skip. WebSearch and WebFetch can't read YouTube videos, so use this skill instead. Skip it for facts with an authoritative source, such as specs, API references, and dates. Also use it when the user pastes a YouTube link or asks what a video says or shows."
---

# YouTube research

Run through the **Bash** tool, exactly in this form (an allow rule matches this prefix). It uses yt-dlp via `uvx` and ffmpeg; the first run of a session may take ~10 s while uvx resolves yt-dlp.

## Commands

```bash
python ~/.claude/skills/youtube/yt.py search "proxmox gpu passthrough" -n 8
python ~/.claude/skills/youtube/yt.py search-transcripts "proxmox gpu passthrough" "proxmox nvidia vfio" --grep "code 43" "vendor.?id" -n 10
python ~/.claude/skills/youtube/yt.py read https://youtu.be/VIDEO_ID
python ~/.claude/skills/youtube/yt.py frames VIDEO_ID --at 2:15 7:40
python ~/.claude/skills/youtube/yt.py frames VIDEO_ID --every 60
```

- `search` prints `url | title | channel | duration | views`. Add the year or "2026" to the query when recency matters.
- `search-transcripts` searches inside transcripts: runs each query on YouTube, fetches the top `-n` transcripts per query in parallel, and prints the paragraphs matching any `--grep` regex (case-insensitive) as `youtu.be/<id>?t=<s>` links. Videos covering more of your patterns rank first, then those whose title shares more words with your queries, then hit count. It only sees what YouTube's search returns, so give 2-3 differently worded queries that name the exact model, and grep for the specific terms you need (error codes, setting names, model numbers). Auto captions misspell jargon: grep loose variants (`vfio|v f i o`, `code.?43`) and anchor them with `\b` (`rom.?bar` hit "from Barmine"; `\brom.?bar\b` doesn't). Plain words of 3 letters or fewer (`ram`, `led`) are anchored automatically. Takes ~30-60 s for 20 new videos; already-fetched ones are cached.
- `read` prints header (title, channel, upload date YYYYMMDD, captions track used), chapters, description, then `[m:ss]` paragraphs. Long videos print only the header plus the path to the cached `.md`: Read it with offset/limit or Grep it. Prefers captions in the video's original spoken language (manual, then auto); if the captions line says "translated", no original-language track existed, so treat wording as a machine translation. If the captions line says "almost no speech", the transcript is music or silence: use the chapters, description and `frames --every` instead.
- `frames` saves 1280px JPGs and prints their paths; then Read the JPGs to see them. Max 20 per call.

Everything is cached in `%LOCALAPPDATA%\yt-skill\<id>\`, so re-running a command on the same video is free.

## How to research with it

Text sources tell; videos show. A video earns its place in the answer with what text leaves out: the steps as someone actually does them, where things are (a menu, a map location, a setting, a part), what the result should look like, and the mistakes people make along the way. Look for those, whatever the topic: a game quest, a software setup, a repair, a recipe, an exercise.

1. Pick the video about the exact thing asked (same game and patch, software version, device, dish or technique) first, by title, then by views and recency. For a specific fact, error or setting, start with `search-transcripts`; for a broad topic, `search`, then choose 1-3 candidates. Skim chapters and description first; they often answer the question or point at the timestamp.
2. `read` the chosen videos. When the transcript names concrete steps, menus or places, put them in the answer. Auto captions mangle names, model numbers and commands: treat them as approximate and confirm exact strings from a frame or another source.
3. Grab frames where something is on screen ("go into this menu", "run this command", code, diagrams), about 3-5 s after the transcript says it appears so the content is visible. Grab only frames you will Read, and Read each once.
4. Don't carry details from a different version, edition or variant into the answer (steps changed in a patch, renamed settings, other hardware revisions); say which one the video shows. When an official or authoritative source exists, keep its method as the main answer and add a video's different method only if it solves something the official one doesn't.
5. Cite only videos you read, as `https://youtu.be/<id>?t=<seconds>` with the channel name and upload date, and say when a claim comes from auto captions only.

## Troubleshooting

- `yt-dlp failed` with a sign-in/bot message: YouTube is rate limiting; wait or try another video. The helper already retries once on the latest yt-dlp.
- `captions: NONE`: the video has no captions; use description, chapters and `frames --every`.
- Age-restricted or members-only videos need cookies; not supported.
