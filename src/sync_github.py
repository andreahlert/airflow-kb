#!/usr/bin/env python3
"""
Sync GitHub PRs and Issues from apache/airflow to local markdown files.
Uses GraphQL API for efficiency (100 items per query).

Usage:
    python sync_github.py --mode prs-open      # Sync all open PRs
    python sync_github.py --mode prs-recent     # Sync PRs updated in last N days
    python sync_github.py --mode issues-open    # Sync all open issues
    python sync_github.py --mode issues-recent  # Sync issues updated in last N days
    python sync_github.py --mode all            # Sync everything
    python sync_github.py --pr 12345            # Sync a specific PR
    python sync_github.py --issue 12345         # Sync a specific issue

Requires: GITHUB_TOKEN env var or gh CLI authenticated.
"""

import argparse
import json
import os
import subprocess
import sys
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

VAULT_DIR = Path(__file__).parent.parent
PRS_DIR = VAULT_DIR / "PRs"
ISSUES_DIR = VAULT_DIR / "Issues"
PEOPLE_DIR = VAULT_DIR / "People"
DIFFS_DIR = VAULT_DIR / "PRs" / "diffs"
STATE_FILE = VAULT_DIR / "Scripts" / ".sync_state.json"

REPO_OWNER = "apache"
REPO_NAME = "airflow"


def get_token():
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: No GITHUB_TOKEN and gh CLI not authenticated.")
        sys.exit(1)


def graphql(query, variables, token):
    payload = json.dumps({"query": query, "variables": variables})
    result = subprocess.run(
        ["gh", "api", "graphql", "--input", "-"],
        input=payload,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"GraphQL error: {result.stderr}")
        sys.exit(1)
    data = json.loads(result.stdout)
    if "errors" in data:
        print(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")
        sys.exit(1)
    return data["data"]


PR_QUERY = """
query($owner: String!, $name: String!, $cursor: String, $states: [PullRequestState!]) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: 50, after: $cursor, states: $states, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      totalCount
      nodes {
        number title body state createdAt updatedAt mergedAt closedAt
        author { login }
        labels(first: 20) { nodes { name } }
        files(first: 100) { nodes { path } }
        reviewRequests(first: 10) { nodes { requestedReviewer { ... on User { login } } } }
        reviews(first: 50) {
          nodes {
            author { login }
            body state submittedAt
            comments(first: 50) {
              nodes { path line body createdAt author { login } }
            }
          }
        }
        comments(first: 100) {
          nodes { author { login } body createdAt }
        }
      }
    }
  }
}
"""

ISSUE_QUERY = """
query($owner: String!, $name: String!, $cursor: String, $states: [IssueState!]) {
  repository(owner: $owner, name: $name) {
    issues(first: 50, after: $cursor, states: $states, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      totalCount
      nodes {
        number title body state createdAt updatedAt closedAt
        author { login }
        labels(first: 20) { nodes { name } }
        comments(first: 100) {
          nodes { author { login } body createdAt }
        }
      }
    }
  }
}
"""

SINGLE_PR_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      number title body state createdAt updatedAt mergedAt closedAt
      author { login }
      labels(first: 20) { nodes { name } }
      files(first: 100) { nodes { path } }
      reviewRequests(first: 10) { nodes { requestedReviewer { ... on User { login } } } }
      reviews(first: 50) {
        nodes {
          author { login }
          body state submittedAt
          comments(first: 50) {
            nodes { path line body createdAt author { login } }
          }
        }
      }
      comments(first: 100) {
        nodes { author { login } body createdAt }
      }
    }
  }
}
"""

SINGLE_ISSUE_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      number title body state createdAt updatedAt closedAt
      author { login }
      labels(first: 20) { nodes { name } }
      comments(first: 100) {
        nodes { author { login } body createdAt }
      }
    }
  }
}
"""


def fetch_diff(pr_number):
    """Fetch the unified diff for a PR and save as separate file."""
    DIFFS_DIR.mkdir(exist_ok=True)
    diff_file = DIFFS_DIR / f"PR-{pr_number}.diff"
    result = subprocess.run(
        [
            "gh", "api",
            f"repos/{REPO_OWNER}/{REPO_NAME}/pulls/{pr_number}",
            "-H", "Accept: application/vnd.github.v3.diff",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout:
        diff_file.write_text(result.stdout)
        return len(result.stdout)
    return 0


def safe_login(node):
    if node and node.get("author") and node["author"].get("login"):
        return node["author"]["login"]
    return "ghost"


def sanitize_filename(s):
    return re.sub(r'[<>:"/\\|?*]', '', s)[:80]


def ensure_person(login):
    person_file = PEOPLE_DIR / f"{login}.md"
    if not person_file.exists():
        person_file.write_text(
            f"---\n"
            f"tags: [type/person]\n"
            f"github: {login}\n"
            f"---\n"
            f"# {login}\n\n"
            f"- [GitHub](https://github.com/{login})\n"
        )
    return login


def format_pr(pr):
    number = pr["number"]
    title = pr["title"]
    body = pr["body"] or ""
    state = pr["state"].lower()
    author = safe_login(pr)
    ensure_person(author)

    labels = [l["name"] for l in pr.get("labels", {}).get("nodes", [])]
    files = [f["path"] for f in pr.get("files", {}).get("nodes", [])]
    reviewers = set()

    for review in pr.get("reviews", {}).get("nodes", []):
        reviewer = safe_login(review)
        if reviewer != "ghost":
            ensure_person(reviewer)
            reviewers.add(reviewer)

    for rr in pr.get("reviewRequests", {}).get("nodes", []):
        rr_reviewer = rr.get("requestedReviewer", {})
        if rr_reviewer and rr_reviewer.get("login"):
            ensure_person(rr_reviewer["login"])
            reviewers.add(rr_reviewer["login"])

    reviewers_str = ", ".join(f'"[[{r}]]"' for r in sorted(reviewers))
    labels_str = ", ".join(labels)
    created = pr["createdAt"][:10]
    updated = pr["updatedAt"][:10]
    merged = pr["mergedAt"][:10] if pr.get("mergedAt") else ""
    closed = pr["closedAt"][:10] if pr.get("closedAt") else ""

    md = f"""---
tags: [type/pr, org/apache, project/airflow, status/{state}]
pr: {number}
url: https://github.com/{REPO_OWNER}/{REPO_NAME}/pull/{number}
status: {state}
author: "[[{author}]]"
reviewers: [{reviewers_str}]
labels: [{labels_str}]
created: {created}
updated: {updated}
merged: {merged}
closed: {closed}
files_changed: {len(files)}
diff: "[[diffs/PR-{number}.diff]]"
---
# PR-{number}: {title}

## Description

{body}

## Files Changed

"""
    for f in files[:50]:
        md += f"- `{f}`\n"
    if len(files) > 50:
        md += f"- ... and {len(files) - 50} more\n"

    # Comments
    comments = pr.get("comments", {}).get("nodes", [])
    if comments:
        md += "\n## Comments\n\n"
        for c in comments:
            c_author = safe_login(c)
            ensure_person(c_author)
            c_date = c["createdAt"][:10]
            c_body = c.get("body", "")
            md += f"### [[{c_author}]] ({c_date})\n\n{c_body}\n\n"

    # Reviews
    reviews = pr.get("reviews", {}).get("nodes", [])
    if reviews:
        md += "\n## Reviews\n\n"
        for r in reviews:
            r_author = safe_login(r)
            r_state = r.get("state", "")
            r_date = (r.get("submittedAt") or "")[:10]
            r_body = r.get("body", "")
            md += f"### [[{r_author}]] - {r_state} ({r_date})\n\n"
            if r_body:
                md += f"{r_body}\n\n"
            # Inline review comments
            for ic in r.get("comments", {}).get("nodes", []):
                ic_author = safe_login(ic)
                ic_path = ic.get("path", "")
                ic_line = ic.get("line", "")
                ic_body = ic.get("body", "")
                md += f"> **[[{ic_author}]]** on `{ic_path}:{ic_line}`\n"
                md += f"> {ic_body}\n\n"

    return md


def format_issue(issue):
    number = issue["number"]
    title = issue["title"]
    body = issue["body"] or ""
    state = issue["state"].lower()
    author = safe_login(issue)
    ensure_person(author)

    labels = [l["name"] for l in issue.get("labels", {}).get("nodes", [])]
    labels_str = ", ".join(labels)
    created = issue["createdAt"][:10]
    updated = issue["updatedAt"][:10]
    closed = issue["closedAt"][:10] if issue.get("closedAt") else ""

    md = f"""---
tags: [type/issue, org/apache, project/airflow, status/{state}]
issue: {number}
url: https://github.com/{REPO_OWNER}/{REPO_NAME}/issues/{number}
status: {state}
author: "[[{author}]]"
labels: [{labels_str}]
created: {created}
updated: {updated}
closed: {closed}
---
# ISSUE-{number}: {title}

## Description

{body}

"""
    comments = issue.get("comments", {}).get("nodes", [])
    if comments:
        md += "## Comments\n\n"
        for c in comments:
            c_author = safe_login(c)
            ensure_person(c_author)
            c_date = c["createdAt"][:10]
            c_body = c.get("body", "")
            md += f"### [[{c_author}]] ({c_date})\n\n{c_body}\n\n"

    return md


def sync_prs(states, max_pages=None, since_date=None, with_diffs=False):
    cursor = None
    page = 0
    total_synced = 0
    while True:
        page += 1
        variables = {
            "owner": REPO_OWNER,
            "name": REPO_NAME,
            "states": states,
        }
        if cursor:
            variables["cursor"] = cursor

        print(f"  Fetching PRs page {page}...")
        data = graphql(PR_QUERY, variables, None)
        prs_data = data["repository"]["pullRequests"]
        total = prs_data["totalCount"]

        if page == 1:
            print(f"  Total PRs matching: {total}")

        for pr in prs_data["nodes"]:
            if since_date:
                updated = datetime.fromisoformat(pr["updatedAt"].replace("Z", "+00:00"))
                if updated < since_date:
                    print(f"  Reached PRs older than cutoff. Stopping.")
                    return total_synced

            number = pr["number"]
            md = format_pr(pr)
            filepath = PRS_DIR / f"PR-{number}.md"
            filepath.write_text(md)
            if with_diffs:
                diff_size = fetch_diff(number)
                if diff_size and total_synced % 10 == 0:
                    print(f"    (diff: {diff_size // 1024}KB)")
            total_synced += 1

            if total_synced % 10 == 0:
                print(f"  Synced {total_synced} PRs...")

        if not prs_data["pageInfo"]["hasNextPage"]:
            break
        cursor = prs_data["pageInfo"]["endCursor"]

        if max_pages and page >= max_pages:
            print(f"  Reached max pages ({max_pages}). Stopping.")
            break

    return total_synced


def sync_issues(states, max_pages=None, since_date=None):
    cursor = None
    page = 0
    total_synced = 0
    while True:
        page += 1
        variables = {
            "owner": REPO_OWNER,
            "name": REPO_NAME,
            "states": states,
        }
        if cursor:
            variables["cursor"] = cursor

        print(f"  Fetching Issues page {page}...")
        data = graphql(ISSUE_QUERY, variables, None)
        issues_data = data["repository"]["issues"]
        total = issues_data["totalCount"]

        if page == 1:
            print(f"  Total Issues matching: {total}")

        for issue in issues_data["nodes"]:
            if since_date:
                updated = datetime.fromisoformat(issue["updatedAt"].replace("Z", "+00:00"))
                if updated < since_date:
                    print(f"  Reached issues older than cutoff. Stopping.")
                    return total_synced

            number = issue["number"]
            md = format_issue(issue)
            filepath = ISSUES_DIR / f"ISSUE-{number}.md"
            filepath.write_text(md)
            total_synced += 1

            if total_synced % 10 == 0:
                print(f"  Synced {total_synced} issues...")

        if not issues_data["pageInfo"]["hasNextPage"]:
            break
        cursor = issues_data["pageInfo"]["endCursor"]

        if max_pages and page >= max_pages:
            print(f"  Reached max pages ({max_pages}). Stopping.")
            break

    return total_synced


def sync_single_pr(number, with_diffs=True):
    variables = {
        "owner": REPO_OWNER,
        "name": REPO_NAME,
        "number": number,
    }
    print(f"  Fetching PR #{number}...")
    data = graphql(SINGLE_PR_QUERY, variables, None)
    pr = data["repository"]["pullRequest"]
    if not pr:
        print(f"  PR #{number} not found.")
        return 0
    md = format_pr(pr)
    filepath = PRS_DIR / f"PR-{number}.md"
    filepath.write_text(md)
    if with_diffs:
        diff_size = fetch_diff(number)
        print(f"  Diff: {diff_size // 1024}KB")
    print(f"  Synced PR #{number}: {pr['title']}")
    return 1


def sync_single_issue(number):
    variables = {
        "owner": REPO_OWNER,
        "name": REPO_NAME,
        "number": number,
    }
    print(f"  Fetching Issue #{number}...")
    data = graphql(SINGLE_ISSUE_QUERY, variables, None)
    issue = data["repository"]["issue"]
    if not issue:
        print(f"  Issue #{number} not found.")
        return 0
    md = format_issue(issue)
    filepath = ISSUES_DIR / f"ISSUE-{number}.md"
    filepath.write_text(md)
    print(f"  Synced Issue #{number}: {issue['title']}")
    return 1


def save_state(mode, count):
    state = {}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
    state[mode] = {
        "last_sync": datetime.now(timezone.utc).isoformat(),
        "count": count,
    }
    STATE_FILE.write_text(json.dumps(state, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Sync GitHub data to AirflowKB vault")
    parser.add_argument("--mode", choices=["prs-open", "prs-recent", "issues-open", "issues-recent", "all"])
    parser.add_argument("--pr", type=int, help="Sync a specific PR by number")
    parser.add_argument("--issue", type=int, help="Sync a specific issue by number")
    parser.add_argument("--days", type=int, default=30, help="For recent modes, how many days back (default: 30)")
    parser.add_argument("--max-pages", type=int, default=None, help="Max pages to fetch (50 items/page)")
    parser.add_argument("--with-diffs", action="store_true", help="Also fetch unified diffs for PRs (1 extra API call per PR)")
    args = parser.parse_args()

    if not args.mode and not args.pr and not args.issue:
        parser.print_help()
        sys.exit(1)

    PRS_DIR.mkdir(exist_ok=True)
    ISSUES_DIR.mkdir(exist_ok=True)
    PEOPLE_DIR.mkdir(exist_ok=True)

    since_date = datetime.now(timezone.utc) - timedelta(days=args.days)

    if args.pr:
        count = sync_single_pr(args.pr, with_diffs=True)
        print(f"\nDone. Synced {count} PR.")
        return

    if args.issue:
        count = sync_single_issue(args.issue)
        print(f"\nDone. Synced {count} issue.")
        return

    total = 0

    if args.mode in ("prs-open", "all"):
        print("\n=== Syncing open PRs ===")
        count = sync_prs(["OPEN"], max_pages=args.max_pages, with_diffs=args.with_diffs)
        total += count
        save_state("prs-open", count)
        print(f"  Synced {count} open PRs.")

    if args.mode == "prs-recent":
        print(f"\n=== Syncing PRs updated in last {args.days} days ===")
        count = sync_prs(["OPEN", "MERGED", "CLOSED"], max_pages=args.max_pages, since_date=since_date, with_diffs=args.with_diffs)
        total += count
        save_state("prs-recent", count)
        print(f"  Synced {count} recent PRs.")

    if args.mode in ("issues-open", "all"):
        print("\n=== Syncing open Issues ===")
        count = sync_issues(["OPEN"], max_pages=args.max_pages)
        total += count
        save_state("issues-open", count)
        print(f"  Synced {count} open issues.")

    if args.mode == "issues-recent":
        print(f"\n=== Syncing Issues updated in last {args.days} days ===")
        count = sync_issues(["OPEN", "CLOSED"], max_pages=args.max_pages, since_date=since_date)
        total += count
        save_state("issues-recent", count)
        print(f"  Synced {count} recent issues.")

    if args.mode == "all":
        print(f"\n=== Syncing recent PRs (last {args.days} days) ===")
        count = sync_prs(["MERGED", "CLOSED"], max_pages=args.max_pages, since_date=since_date)
        total += count

        print(f"\n=== Syncing recent Issues (last {args.days} days) ===")
        count = sync_issues(["CLOSED"], max_pages=args.max_pages, since_date=since_date)
        total += count

    # Count totals
    pr_count = len(list(PRS_DIR.glob("PR-*.md")))
    issue_count = len(list(ISSUES_DIR.glob("ISSUE-*.md")))
    people_count = len(list(PEOPLE_DIR.glob("*.md")))

    print(f"\n=== Summary ===")
    print(f"  PRs in vault: {pr_count}")
    print(f"  Issues in vault: {issue_count}")
    print(f"  People in vault: {people_count}")
    print(f"  Synced this run: {total}")


if __name__ == "__main__":
    main()
