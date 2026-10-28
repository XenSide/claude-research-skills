"""PreToolUse hook for WebSearch: notes that Reddit and YouTube are reachable through skills, not web search.

It never blocks or approves the search; it only adds context next to the result.
"""
import json
import sys

NOTE = (
    "WebSearch and WebFetch can't read Reddit threads or YouTube videos; the results only show titles and snippets. "
    "Two skills can read them in this same turn: `reddit` (first-hand reports, troubleshooting, recommendations, "
    "comparisons, \"is X worth it\") and `youtube` (tutorials, setup and repair walkthroughs, reviews, talks; "
    "it can search inside video transcripts and grab frames). They fit questions where people's experience or a "
    "video walkthrough adds to the official source."
)

json.load(sys.stdin)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": NOTE}}))
