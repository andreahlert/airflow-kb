#!/usr/bin/env python3
"""
Sync Apache Airflow Slack channels to local markdown files.
Uses postcli-slack CLI.

Usage:
    python sync_slack.py --channel new-contributors --days 30
    python sync_slack.py --channel internal-airflow-ci-cd --days 7
    python sync_slack.py --search "uv.lock"
    python sync_slack.py --all-channels --days 14
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT_DIR = Path(__file__).parent.parent
SLACK_DIR = VAULT_DIR / "Slack"
PEOPLE_DIR = VAULT_DIR / "People"

KEY_CHANNELS = [
    "new-contributors",
    "internal-airflow-ci-cd",
    "announcements",
    "airflow-creative",
    "issue-triage",
    "user-troubleshooting",
]


def run_postcli(args):
    """Run postcli-slack command and return output."""
    cmd = ["postcli-slack", "--json"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        # Try without --json
        cmd = ["postcli-slack"] + args
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return result.stdout
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout


def get_channel_history(channel, limit=100):
    """Get recent messages from a channel."""
    result = subprocess.run(
        ["postcli-slack", "messages", "history", channel],
        capture_output=True, text=True, timeout=120,
    )
    return parse_text_messages(result.stdout)


def get_thread(channel, ts):
    """Get thread replies."""
    result = subprocess.run(
        ["postcli-slack", "--json", "messages", "thread", channel, ts],
        capture_output=True, text=True, timeout=60,
    )
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, Exception):
        return None


def search_messages(query):
    """Search Slack messages."""
    result = subprocess.run(
        ["postcli-slack", "search", "messages", query],
        capture_output=True, text=True, timeout=60,
    )
    return result.stdout


def parse_text_messages(text):
    """Parse postcli-slack text output into structured messages."""
    messages = []
    for line in text.strip().split("\n"):
        if not line.strip():
            continue
        # Format: 2026-03-16 23:09 UCWJQGY1J: text
        match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) (\S+): (.+)", line)
        if match:
            messages.append({
                "date": match.group(1),
                "user_id": match.group(2),
                "text": match.group(3),
            })
    return messages


def resolve_user(user_id, user_cache):
    """Resolve user ID to name."""
    if user_id in user_cache:
        return user_cache[user_id]
    # Extract display name from message format if available
    user_cache[user_id] = user_id
    return user_id


def format_channel_note(channel, messages, date_str):
    """Format channel messages as a markdown note."""
    if not messages:
        return None

    # Group by day
    md = f"""---
tags: [type/slack, org/apache, project/airflow]
channel: "#{channel}"
date: {date_str}
messages: {len(messages)}
---
# #{channel} - {date_str}

"""

    for msg in messages:
        if isinstance(msg, dict):
            date = msg.get("date", msg.get("ts", "?"))
            user = msg.get("user_id", msg.get("user", "?"))
            text = msg.get("text", "")
            replies = msg.get("reply_count", 0)

            # Clean up Slack formatting
            text = re.sub(r'<@(\w+)>', r'@\1', text)
            text = re.sub(r'<(https?://[^|>]+)\|([^>]+)>', r'[\2](\1)', text)
            text = re.sub(r'<(https?://[^>]+)>', r'\1', text)

            reply_note = f" [{replies} replies]" if replies else ""
            md += f"### {user} ({date}){reply_note}\n\n{text}\n\n---\n\n"
        else:
            md += f"{msg}\n\n"

    return md


def sync_channel(channel, days=30):
    """Sync a channel's recent messages to vault."""
    channel_dir = SLACK_DIR / channel
    channel_dir.mkdir(parents=True, exist_ok=True)

    print(f"  Fetching #{channel}...")
    messages = get_channel_history(channel, limit=200)

    if isinstance(messages, str):
        messages = parse_text_messages(messages)

    if not messages:
        print(f"  No messages for #{channel}")
        return 0

    print(f"  Got {len(messages)} messages")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    md = format_channel_note(channel, messages, today)
    if md:
        filepath = channel_dir / f"{today}.md"
        filepath.write_text(md)
        print(f"  Wrote {filepath.name}")

    return len(messages)


def sync_search(query):
    """Sync search results to vault."""
    search_dir = SLACK_DIR / "searches"
    search_dir.mkdir(parents=True, exist_ok=True)

    print(f"  Searching: {query}")
    results = search_messages(query)

    if not results.strip():
        print("  No results")
        return 0

    safe_query = re.sub(r'[^a-zA-Z0-9_-]', '_', query)[:50]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filepath = search_dir / f"{safe_query}_{today}.md"

    md = f"""---
tags: [type/slack, org/apache, project/airflow]
query: "{query}"
date: {today}
---
# Slack Search: {query}

{results}
"""
    filepath.write_text(md)
    lines = results.strip().split("\n")
    print(f"  Wrote {len(lines)} results to {filepath.name}")
    return len(lines)


def main():
    parser = argparse.ArgumentParser(description="Sync Airflow Slack to AirflowKB vault")
    parser.add_argument("--channel", type=str, help="Sync a specific channel")
    parser.add_argument("--all-channels", action="store_true", help="Sync all key channels")
    parser.add_argument("--search", type=str, help="Search and save results")
    parser.add_argument("--days", type=int, default=30, help="Days of history (default: 30)")
    args = parser.parse_args()

    if not args.channel and not args.all_channels and not args.search:
        parser.print_help()
        sys.exit(1)

    SLACK_DIR.mkdir(exist_ok=True)

    total = 0

    if args.search:
        total += sync_search(args.search)

    if args.channel:
        total += sync_channel(args.channel, args.days)

    if args.all_channels:
        for ch in KEY_CHANNELS:
            total += sync_channel(ch, args.days)

    print(f"\n=== Summary ===")
    print(f"  Total messages/results synced: {total}")


if __name__ == "__main__":
    main()
