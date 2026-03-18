#!/usr/bin/env python3
"""
Build directed review context for a PR using the AirflowKB vault.

Instead of dumping raw context, generates SPECIFIC VERIFICATION QUESTIONS
that force the LLM to act on the information.

Usage:
    python build_context.py 63296              # Build context for PR
    python build_context.py 63296 --output md  # Output as markdown
    python build_context.py 63296 --review     # Build context + run LLM review
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
PRS_DIR = VAULT_DIR / "PRs"
DIFFS_DIR = VAULT_DIR / "PRs" / "diffs"
ISSUES_DIR = VAULT_DIR / "Issues"
PEOPLE_DIR = VAULT_DIR / "People"

AIRFLOW_CURRENT_STABLE = "3.1.8"
AIRFLOW_NEXT_VERSION = "3.2.0"


def parse_frontmatter(filepath):
    """Parse YAML frontmatter from a markdown file."""
    text = filepath.read_text(errors="replace")
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    fm_text = text[3:end].strip()
    body = text[end + 3:].strip()
    fm = {}
    for line in fm_text.split("\n"):
        if ":" in line:
            key, val = line.split(":", 1)
            fm[key.strip()] = val.strip().strip('"')

    return fm, body


def get_pr_note(pr_number):
    """Read PR note and parse frontmatter."""
    filepath = PRS_DIR / f"PR-{pr_number}.md"
    if not filepath.exists():
        return None, None
    return parse_frontmatter(filepath)


def get_pr_diff(pr_number):
    """Read PR diff file."""
    filepath = DIFFS_DIR / f"PR-{pr_number}.diff"
    if filepath.exists():
        return filepath.read_text(errors="replace")
    return None


def get_pr_files(pr_number):
    """Extract files changed from PR note."""
    filepath = PRS_DIR / f"PR-{pr_number}.md"
    if not filepath.exists():
        return []
    text = filepath.read_text(errors="replace")
    files = []
    in_files = False
    for line in text.split("\n"):
        if line.strip() == "## Files Changed":
            in_files = True
            continue
        if in_files and line.startswith("## "):
            break
        if in_files and line.startswith("- `"):
            f = line.strip("- `").strip("`").strip()
            if f:
                files.append(f)
    return files


def find_overlapping_prs(files, exclude_pr):
    """Find other open PRs that touch the same files."""
    overlaps = {}
    for f in files:
        fname = os.path.basename(f)
        if fname in ("__init__.py", "conftest.py"):
            continue
        result = subprocess.run(
            ["grep", "-rl", fname, str(DIFFS_DIR)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            for match in result.stdout.strip().split("\n"):
                if not match:
                    continue
                match_pr = re.search(r"PR-(\d+)\.diff", match)
                if match_pr:
                    pr_num = int(match_pr.group(1))
                    if pr_num != exclude_pr:
                        if pr_num not in overlaps:
                            overlaps[pr_num] = []
                        overlaps[pr_num].append(fname)
    return overlaps


def get_author_profile(author):
    """Build author profile from vault data."""
    # Count PRs by this author
    result = subprocess.run(
        ["grep", "-rl", f'author: "\\[\\[{author}\\]\\]"', str(PRS_DIR)],
        capture_output=True, text=True,
    )
    author_prs = []
    if result.returncode == 0:
        for line in result.stdout.strip().split("\n"):
            if line:
                match = re.search(r"PR-(\d+)\.md", line)
                if match:
                    author_prs.append(int(match.group(1)))

    # Get labels/areas from their PRs
    areas = {}
    for pr_num in author_prs[:30]:
        fm, _ = get_pr_note(pr_num)
        if fm and "labels" in fm:
            for label in fm["labels"].strip("[]").split(","):
                label = label.strip()
                if label.startswith("area:"):
                    area = label.replace("area:", "")
                    areas[area] = areas.get(area, 0) + 1

    return {
        "total_prs": len(author_prs),
        "pr_numbers": author_prs,
        "areas": areas,
    }


def find_maintainer_comments(files, pr_number):
    """Find what maintainers said about the same files in other PRs."""
    maintainers = ["potiuk", "ashb", "kaxil", "jedcunningham", "ephraimbuddy",
                   "uranusjr", "ferruzzi", "jscheffl", "Lee-W", "XD-DENG"]
    findings = []

    for f in files[:5]:
        fname = os.path.basename(f)
        if fname in ("__init__.py", "conftest.py"):
            continue

        # Find PRs that touch this file
        result = subprocess.run(
            ["grep", "-rl", fname, str(PRS_DIR)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            continue

        for match_file in result.stdout.strip().split("\n"):
            if not match_file or not match_file.endswith(".md"):
                continue
            match_pr = re.search(r"PR-(\d+)\.md", match_file)
            if not match_pr:
                continue
            other_pr = int(match_pr.group(1))
            if other_pr == pr_number:
                continue

            # Check if maintainers commented on this PR
            try:
                text = Path(match_file).read_text(errors="replace")
            except FileNotFoundError:
                continue

            for m in maintainers:
                if f"[[{m}]]" in text:
                    # Extract what they said (first comment only)
                    pattern = rf"### \[\[{m}\]\].*?\n\n(.*?)(?:\n\n###|\n\n##|$)"
                    comment_match = re.search(pattern, text, re.DOTALL)
                    if comment_match:
                        comment = comment_match.group(1).strip()[:200]
                        findings.append({
                            "maintainer": m,
                            "pr": other_pr,
                            "file": fname,
                            "comment": comment,
                        })

    # Deduplicate by maintainer+file
    seen = set()
    unique = []
    for f in findings:
        key = (f["maintainer"], f["file"])
        if key not in seen:
            seen.add(key)
            unique.append(f)

    return unique[:10]


def extract_review_positions(pr_number):
    """Extract maintainer review positions from the PR note."""
    filepath = PRS_DIR / f"PR-{pr_number}.md"
    if not filepath.exists():
        return []
    text = filepath.read_text(errors="replace")
    positions = []

    review_pattern = r"### \[\[(\w+)\]\] - (\w+) \((\d{4}-\d{2}-\d{2})\)\n\n(.*?)(?=\n### |\n## |$)"
    for match in re.finditer(review_pattern, text, re.DOTALL):
        reviewer = match.group(1)
        state = match.group(2)
        date = match.group(3)
        body = match.group(4).strip()[:300]
        positions.append({
            "reviewer": reviewer,
            "state": state,
            "date": date,
            "body": body,
        })

    return positions


def check_version_fields(diff_text):
    """Check for version_added fields that might be wrong."""
    issues = []
    version_matches = re.findall(r"version_added:\s*[\"']?(\d+\.\d+\.\d+)", diff_text)
    for v in version_matches:
        major, minor, patch = map(int, v.split("."))
        stable_major, stable_minor, stable_patch = map(int, AIRFLOW_CURRENT_STABLE.split("."))
        if (major, minor, patch) <= (stable_major, stable_minor, stable_patch):
            issues.append(
                f"version_added says {v} but current stable is {AIRFLOW_CURRENT_STABLE}. "
                f"Should probably be {AIRFLOW_NEXT_VERSION} or later."
            )
    return issues


def check_exception_consistency(diff_text):
    """Check if different exception types are raised for similar validations."""
    exceptions = re.findall(r"raise (\w+(?:Error|Exception))\(", diff_text)
    if len(set(exceptions)) > 1:
        return f"Multiple exception types raised: {', '.join(set(exceptions))}. Should these be consistent?"
    return None


def check_code_duplication(diff_text):
    """Detect duplicated validation logic in the diff."""
    # Find repeated conditional patterns
    conditions = re.findall(r'if "\.\.?" in \w+.*?:', diff_text)
    if len(conditions) > 1:
        return f"Same validation check appears {len(conditions)} times. Consider extracting to a shared helper."
    return None


def build_context(pr_number):
    """Build directed review context with verification questions."""
    fm, body = get_pr_note(pr_number)
    if not fm:
        print(f"PR-{pr_number} not found in vault. Run: python sync_github.py --pr {pr_number}")
        sys.exit(1)

    diff = get_pr_diff(pr_number)
    files = get_pr_files(pr_number)
    author = fm.get("author", "").strip("[[]]")

    # Gather intelligence
    overlapping = find_overlapping_prs(files, pr_number)
    author_profile = get_author_profile(author)
    review_positions = extract_review_positions(pr_number)
    maintainer_history = find_maintainer_comments(files, pr_number)

    # Automated checks on the diff
    version_issues = check_version_fields(diff) if diff else []
    exception_issue = check_exception_consistency(diff) if diff else None
    duplication_issue = check_code_duplication(diff) if diff else None

    # Build the context document
    sections = []

    # Section 1: Verification questions (the core value)
    questions = []

    if version_issues:
        for vi in version_issues:
            questions.append(f"VERSION CHECK: {vi}")

    if exception_issue:
        questions.append(f"CONSISTENCY CHECK: {exception_issue}")

    if duplication_issue:
        questions.append(f"DUPLICATION CHECK: {duplication_issue}")

    if overlapping:
        conflict_details = []
        for opr, ofiles in sorted(overlapping.items())[:5]:
            ofm, _ = get_pr_note(opr)
            otitle = ""
            if ofm:
                pr_path = PRS_DIR / f"PR-{opr}.md"
                for line in pr_path.read_text(errors="replace").split("\n"):
                    if line.startswith("# PR-"):
                        otitle = line.split(":", 1)[1].strip() if ":" in line else ""
                        break
            conflict_details.append(f"  - PR-{opr} ({otitle}) touches: {', '.join(ofiles)}")
        questions.append(
            "CONFLICT CHECK: These open PRs modify the same files:\n"
            + "\n".join(conflict_details)
            + "\n  Are there merge conflicts or semantic conflicts with this PR?"
        )

    if author_profile["total_prs"] > 0:
        author_areas = ", ".join(f"{a} ({c})" for a, c in sorted(
            author_profile["areas"].items(), key=lambda x: -x[1]
        )[:5])
        current_files_areas = set()
        for f in files:
            if "models/" in f or "utils/" in f or "jobs/" in f:
                current_files_areas.add("core")
            elif "providers/" in f:
                current_files_areas.add("providers")
            elif "api" in f.lower():
                current_files_areas.add("API")
            elif "test" in f.lower():
                current_files_areas.add("tests")

        new_areas = current_files_areas - set(author_profile["areas"].keys())
        if new_areas:
            questions.append(
                f"AUTHOR EXPERIENCE: @{author} has {author_profile['total_prs']} PRs, "
                f"mostly in: {author_areas}. "
                f"This PR touches {', '.join(new_areas)} which is NEW for this author. "
                f"Does the approach follow established patterns in these areas?"
            )

    if review_positions:
        for rp in review_positions:
            if rp["state"] in ("CHANGES_REQUESTED", "COMMENTED"):
                questions.append(
                    f"MAINTAINER FEEDBACK: @{rp['reviewer']} ({rp['state']}, {rp['date']}): "
                    f'"{rp["body"]}" '
                    f"Has this feedback been addressed in the current version?"
                )

    # Check if breaking change needs devlist discussion
    if diff:
        is_breaking = any(x in diff.lower() for x in [
            "breaking", "backward", "deprecat", "behaviour changes",
            "significant.rst", "behavior change"
        ])
        if is_breaking:
            questions.append(
                "GOVERNANCE CHECK: This appears to be a breaking/behavioral change. "
                "Apache Airflow requires significant changes to be discussed on the dev "
                "mailing list before merging. Has this been discussed there?"
            )

    # Section 2: Maintainer history on these files
    if maintainer_history:
        history_lines = []
        for mh in maintainer_history[:5]:
            history_lines.append(
                f"  - @{mh['maintainer']} on PR-{mh['pr']} ({mh['file']}): "
                f'"{mh["comment"][:150]}"'
            )
        sections.append(
            "MAINTAINER HISTORY on files touched by this PR:\n" + "\n".join(history_lines)
        )

    # Assemble the context
    context = "## DIRECTED REVIEW CONTEXT\n\n"
    context += "The following verification questions are generated from the project knowledge base. "
    context += "Each question MUST be addressed in your review.\n\n"

    for i, q in enumerate(questions, 1):
        context += f"### Question {i}\n{q}\n\n"

    if sections:
        context += "---\n\n## ADDITIONAL CONTEXT\n\n"
        for s in sections:
            context += s + "\n\n"

    return context, diff, fm, body


def build_full_review_prompt(pr_number):
    """Build the complete review prompt with context + diff."""
    context, diff, fm, body = build_context(pr_number)

    # Extract description from body
    desc_match = re.search(r"## Description\n\n(.*?)(?=\n## )", body, re.DOTALL)
    description = desc_match.group(1).strip() if desc_match else body[:2000]

    title_match = re.search(r"# PR-\d+: (.+)", body)
    title = title_match.group(1) if title_match else f"PR-{pr_number}"

    prompt = f"""You are a code reviewer for Apache Airflow. Review this PR and provide your assessment.

You MUST address every question in the DIRECTED REVIEW CONTEXT section. These are based on
historical project data and maintainer patterns.

Output JSON with:
- summary (2-3 sentences, must reference findings from the verification questions)
- overall_assessment (APPROVE/REQUEST_CHANGES/COMMENT)
- comments: array of {{path, line, body, category}}
- context_findings: array of {{question_number, finding, severity: "critical"|"warning"|"info"}}

## PR #{pr_number}: {title}

### Description

{description}

{context}

### Diff

```diff
{diff[:100000] if diff else "No diff available"}
```
"""
    return prompt


def main():
    parser = argparse.ArgumentParser(description="Build review context from AirflowKB vault")
    parser.add_argument("pr", type=int, help="PR number")
    parser.add_argument("--output", choices=["text", "md", "json"], default="text",
                       help="Output format")
    parser.add_argument("--review", action="store_true",
                       help="Run LLM review with context")
    parser.add_argument("--model", default="claude-sonnet-4-20250514",
                       help="Model for review")
    args = parser.parse_args()

    if args.review:
        prompt = build_full_review_prompt(args.pr)

        # Save prompt for reference
        prompt_file = VAULT_DIR / "Scripts" / f"review_prompt_PR-{args.pr}.md"
        prompt_file.write_text(prompt)
        print(f"Prompt saved to: {prompt_file}", file=sys.stderr)
        print(f"Prompt size: {len(prompt)} chars", file=sys.stderr)

        # Run review
        result = subprocess.run(
            ["claude", "--model", args.model, "-p"],
            input=prompt,
            capture_output=True,
            text=True,
        )
        print(result.stdout)

        # Save result
        result_file = VAULT_DIR / "Scripts" / f"review_result_PR-{args.pr}.md"
        result_file.write_text(result.stdout)
        print(f"\nResult saved to: {result_file}", file=sys.stderr)
    else:
        context, diff, fm, body = build_context(args.pr)
        if args.output == "json":
            print(json.dumps({"context": context, "pr": args.pr}, indent=2))
        else:
            print(context)


if __name__ == "__main__":
    main()
