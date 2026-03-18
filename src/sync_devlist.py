#!/usr/bin/env python3
"""
Sync Apache Airflow dev mailing list to local markdown files.
Uses Ponymail Foal API at lists.apache.org.

Usage:
    python sync_devlist.py --months 6        # Last 6 months
    python sync_devlist.py --month 2026-03   # Specific month
    python sync_devlist.py --all             # Everything (120 months, ~28k emails)
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode

VAULT_DIR = Path(__file__).parent.parent
DEVLIST_DIR = VAULT_DIR / "DevList"
PEOPLE_DIR = VAULT_DIR / "People"

API_BASE = "https://lists.apache.org/api"
LIST_NAME = "dev"
DOMAIN = "airflow.apache.org"


def api_get(endpoint, params):
    """Fetch JSON from Ponymail API."""
    url = f"{API_BASE}/{endpoint}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "airflow-kb/1.0"})
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  API error: {e}")
        return None


def fetch_full_email(email_id):
    """Fetch full email body via email.lua endpoint."""
    data = api_get("email.lua", {"id": email_id})
    if data and "body" in data:
        return data["body"]
    return None


def get_active_months():
    """Get list of months with email counts."""
    data = api_get("stats.lua", {
        "list": LIST_NAME,
        "domain": DOMAIN,
        "quick": "true",
    })
    if not data:
        return {}
    return data.get("active_months", {})


def fetch_month(month):
    """Fetch all emails for a month with threading info."""
    data = api_get("stats.lua", {
        "list": LIST_NAME,
        "domain": DOMAIN,
        "d": month,
    })
    if not data:
        return [], {}

    emails = data.get("emails", [])
    thread_struct = data.get("thread_struct", [])
    return emails, thread_struct


def clean_email(addr):
    """Extract name from email address."""
    if "<" in addr:
        name = addr.split("<")[0].strip().strip('"')
        return name if name else addr.split("<")[1].split(">")[0]
    return addr


def extract_login_from_email(email_addr):
    """Try to extract a usable login/name from email."""
    if "<" in email_addr:
        email_addr = email_addr.split("<")[1].split(">")[0]
    local = email_addr.split("@")[0]
    return re.sub(r'[^a-zA-Z0-9_-]', '', local)


def ensure_person(name, email_addr):
    """Create person note if needed."""
    login = extract_login_from_email(email_addr if email_addr else name)
    if not login:
        return "unknown"
    person_file = PEOPLE_DIR / f"{login}.md"
    if not person_file.exists():
        clean_name = clean_email(name) if name else login
        person_file.write_text(
            f"---\n"
            f"tags: [type/person]\n"
            f"name: {clean_name}\n"
            f"email: {email_addr}\n"
            f"---\n"
            f"# {clean_name}\n"
        )
    return login


def sanitize_filename(s):
    """Make a string safe for filenames."""
    s = re.sub(r'[<>:"/\\|?*\[\]]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:100]


def group_into_threads(emails):
    """Group emails into threads by normalized subject."""
    threads = {}

    for email in emails:
        # Group by normalized subject (strip Re:, Fwd:, [DISCUSS], etc.)
        raw_subject = email.get("subject", "No subject")
        normalized = re.sub(r'^(Re:\s*|Fwd?:\s*)+', '', raw_subject, flags=re.IGNORECASE).strip()
        tid = normalized.lower()

        if tid not in threads:
            threads[tid] = {
                "subject": normalized,
                "emails": [],
                "first_epoch": email.get("epoch", 0),
                "last_epoch": email.get("epoch", 0),
            }
        threads[tid]["emails"].append(email)
        epoch = email.get("epoch", 0)
        if epoch < threads[tid]["first_epoch"]:
            threads[tid]["first_epoch"] = epoch
        if epoch > threads[tid]["last_epoch"]:
            threads[tid]["last_epoch"] = epoch

    # Sort emails within each thread by time
    for tid in threads:
        threads[tid]["emails"].sort(key=lambda e: e.get("epoch", 0))

    return threads


def format_thread(thread_data, month):
    """Format a thread as markdown."""
    subject = thread_data["subject"]
    emails = thread_data["emails"]
    first_date = datetime.fromtimestamp(thread_data["first_epoch"], tz=timezone.utc)
    last_date = datetime.fromtimestamp(thread_data["last_epoch"], tz=timezone.utc)

    participants = set()
    participant_logins = []
    for e in emails:
        sender = e.get("from", "unknown")
        email_addr = e.get("from", "")
        if "<" in email_addr:
            email_addr = email_addr  # keep full for ensure_person
        login = ensure_person(sender, email_addr)
        participants.add(login)
        participant_logins.append(login)

    participants_str = ", ".join(f'"[[{p}]]"' for p in sorted(participants))

    md = f"""---
tags: [type/devlist, org/apache, project/airflow]
subject: "{subject.replace('"', "'")}"
participants: [{participants_str}]
replies: {len(emails)}
started: {first_date.strftime('%Y-%m-%d')}
last_reply: {last_date.strftime('%Y-%m-%d')}
month: {month}
---
# {subject}

"""

    for e in emails:
        sender = e.get("from", "unknown")
        login = extract_login_from_email(sender)
        epoch = e.get("epoch", 0)
        date = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        body = e.get("full_body") or e.get("body", "")
        body = body.strip()

        # Trim quoted text (lines starting with >)
        lines = body.split("\n")
        trimmed = []
        quote_count = 0
        for line in lines:
            if line.startswith(">"):
                quote_count += 1
                if quote_count <= 3:
                    trimmed.append(line)
                elif quote_count == 4:
                    trimmed.append("> ...")
            else:
                quote_count = 0
                trimmed.append(line)
        body = "\n".join(trimmed)

        md += f"## [[{login}]] ({date})\n\n{body}\n\n---\n\n"

    return md


def sync_month(month):
    """Sync a single month to vault."""
    month_dir = DEVLIST_DIR / month
    month_dir.mkdir(parents=True, exist_ok=True)

    print(f"  Fetching {month}...")
    emails, thread_struct = fetch_month(month)

    if not emails:
        print(f"  No emails for {month}")
        return 0

    print(f"  Got {len(emails)} emails, fetching full bodies...")
    for i, e in enumerate(emails):
        email_id = e.get("mid") or e.get("id")
        if email_id:
            full_body = fetch_full_email(email_id)
            if full_body:
                e["full_body"] = full_body
        if (i + 1) % 50 == 0:
            print(f"    Fetched {i + 1}/{len(emails)} full emails...")
        time.sleep(0.3)  # be nice to the API

    print(f"  Grouping into threads...")
    threads = group_into_threads(emails)

    count = 0
    for tid, thread_data in threads.items():
        subject = thread_data["subject"]
        if not subject:
            subject = "No subject"

        filename = sanitize_filename(subject)
        if not filename:
            filename = f"thread-{tid[:12]}"

        filepath = month_dir / f"{filename}.md"
        md = format_thread(thread_data, month)
        filepath.write_text(md)
        count += 1

    print(f"  Wrote {count} threads ({len(emails)} emails)")
    return count


def main():
    parser = argparse.ArgumentParser(description="Sync Apache Airflow dev mailing list")
    parser.add_argument("--months", type=int, help="Sync last N months")
    parser.add_argument("--month", type=str, help="Sync specific month (yyyy-mm)")
    parser.add_argument("--all", action="store_true", help="Sync everything")
    args = parser.parse_args()

    if not args.months and not args.month and not args.all:
        parser.print_help()
        sys.exit(1)

    DEVLIST_DIR.mkdir(exist_ok=True)
    PEOPLE_DIR.mkdir(exist_ok=True)

    active = get_active_months()
    if not active:
        print("Failed to fetch active months")
        sys.exit(1)

    all_months = sorted(active.keys())
    print(f"Available: {len(all_months)} months, {sum(active.values())} total emails")

    if args.month:
        months_to_sync = [args.month]
    elif args.months:
        months_to_sync = all_months[-args.months:]
    else:
        months_to_sync = all_months

    total_threads = 0
    for i, month in enumerate(months_to_sync):
        email_count = active.get(month, 0)
        print(f"\n[{i+1}/{len(months_to_sync)}] {month} ({email_count} emails)")
        count = sync_month(month)
        total_threads += count
        time.sleep(1)  # be nice to the API

    # Stats
    thread_count = sum(1 for _ in DEVLIST_DIR.rglob("*.md"))
    print(f"\n=== Summary ===")
    print(f"  Threads in vault: {thread_count}")
    print(f"  Synced this run: {total_threads}")


if __name__ == "__main__":
    main()
