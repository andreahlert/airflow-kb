# Historical Context Layer for Airflow's PR Auto-Triage

## The Problem

Airflow's auto-triage system (`breeze pr auto-triage`) uses LLMs to assess PR quality and assist code review. The system works: Jarek triaged ~100 PRs in under an hour, reducing open PRs from 500+ to ~430 in two days.

But the LLM has no memory. Every review starts from zero. It receives the diff and the PR description, nothing else. It doesn't know that @ashb rejected a similar approach three months ago. It doesn't know the author has never touched core before. It doesn't know there's an open thread on the dev mailing list about this exact topic. It doesn't know five other PRs modify the same files.

Jarek himself noted: "The LLM assessments are pretty good, but a few were significantly wrong." This is the gap.

## The Idea

Build a local knowledge base that mirrors all project communication (GitHub PRs, Issues, comments, reviews, diffs, dev mailing list, Slack) as markdown files. Before each LLM review, query this knowledge base to generate directed verification questions with factual data. Feed these questions to the LLM alongside the diff.

The LLM stops being a generic reviewer and becomes a reviewer with institutional memory.

## What I Built

### Data Layer

A sync pipeline that pulls project data into a local Obsidian vault:

- **GitHub Sync** (`sync_github.py`): PRs, issues, comments, reviews, inline review comments, and unified diffs via GraphQL API. 2,335 PRs and 2,311 diffs synced.
- **DevList Sync** (`sync_devlist.py`): Apache Ponymail API, full email bodies, grouped by thread. 426 threads across 6 months (2,108 emails).
- **Slack Sync** (`sync_slack.py`): Channel history and search results via postcli-slack. 6 channels synced.
- **People**: 855 contributor profiles auto-generated with backlinks to their PRs and reviews.

Total: ~6,100 files, 139 MB. All searchable via grep in milliseconds.

### Context Generator

A script (`build_context.py`) that, given a PR number, queries the vault and generates directed verification questions. Not a passive dump of information, but specific questions the LLM must answer:

1. **VERSION CHECK**: "version_added says 3.0.0 but current stable is 3.1.8. Should be 3.2.0 or later."
2. **CONSISTENCY CHECK**: "Multiple exception types raised: ValueError, AirflowException. Should these be consistent?"
3. **CONFLICT CHECK**: "These open PRs modify the same files: PR-63489, PR-45931. Are there merge conflicts?"
4. **AUTHOR EXPERIENCE**: "@YoannAbriel has 20 PRs, mostly in task-sdk. This PR touches core, which is new for this author."
5. **MAINTAINER FEEDBACK**: "@potiuk (CHANGES_REQUESTED): 'This is extremely risky if we do not have a mechanism to allow those.' Has this been addressed?"
6. **GOVERNANCE CHECK**: "This is a breaking change. Has it been discussed on the dev mailing list?"

The questions are generated automatically from vault data. No manual curation needed.

## How I Tested

### Phase 1: Four approaches on one PR (PR-63296, path traversal fix)

| Approach | What the LLM receives |
|---|---|
| **Diff Only** | PR description + diff |
| **Diff + Passive Context** | Diff + raw block of vault data |
| **Directed Questions (no data)** | Diff + generic checklist questions |
| **Directed Questions (with data)** | Diff + specific questions with vault facts |

Key finding: **Directed Questions (no data)** produced better structure but the LLM confabulated. It said the dev mailing list discussion was "properly documented" when no evidence existed. With vault data, the system correctly flagged it as critical. Without real data, the LLM invents answers.

### Phase 2: Twenty PRs, two approaches

Expanded to 20 PRs across providers, scheduler, task-sdk, API, dev-tools, and UI. Compared Diff Only vs Directed Questions (with data).

**Results:**

| Metric | Value |
|---|---|
| PRs tested | 20 |
| Assessment changed | 6 (30%) |
| Vault caught issues Diff Only missed | 3 PRs |
| Vault provided confidence to approve | 2 PRs |
| PRs with at least 1 critical finding | 11 (55%) |
| Average context findings per PR | 6.4 |

### Assessment changes in detail

**3 PRs upgraded to REQUEST_CHANGES** (vault caught real issues):
- PR-56187 (100 files, 132 interactions): Diff Only approved. Vault found 4 critical issues. The most discussed PR in the dataset, approved without context.
- PR-62554 (19 files, scheduler/triggerer): Diff Only approved. Vault identified unaddressed maintainer feedback.
- PR-63450 (16 files, dev-tools/UI): Diff Only approved. Vault found 2 critical governance issues.

**2 PRs downgraded to APPROVE** (vault reduced false positives):
- PR-61274 (7 files, 72 interactions): Diff Only flagged concerns. Vault showed they were already addressed.
- PR-57744 (40 files, task-sdk): Diff Only requested changes. Vault confirmed the approach follows established patterns.

### What the vault detects that diffs cannot

- Wrong `version_added` fields (needs to know current stable version)
- Conflicts with other open PRs (needs inventory of all open PRs)
- Whether maintainer feedback was addressed (needs review history)
- Whether a topic was discussed on the dev mailing list (needs devlist archive)
- Whether the author has experience in the area being modified (needs contribution history)
- Whether a similar approach was previously rejected (needs historical PR data)

## How This Fits With the Existing System

The auto-triage system has four layers:

1. **Data fetching** (GitHub API)
2. **Deterministic assessment** (CI checks, merge conflicts, unresolved comments)
3. **LLM assessment** (quality triage, code review)
4. **Actions** (draft, close, comment, label)

The vault adds a **context layer between 2 and 3**. Before the LLM receives the prompt, a function queries the vault and appends directed questions with factual data. The rest of the system stays unchanged.

Implementation would be a single function: `build_vault_context(pr_files, pr_author) -> str` that returns text to append to the LLM prompt. Compatible with the existing `_build_user_message()` and `_build_review_user_message()` in `llm_utils.py`.

## Repository

All code, prompts, and results are published at: https://github.com/andreahlert/airflow-kb

```
airflow-kb/
├── src/
│   ├── sync_github.py      # GitHub -> markdown
│   ├── sync_devlist.py      # Apache DevList -> markdown
│   ├── sync_slack.py        # Slack -> markdown
│   └── build_context.py     # Vault -> directed questions
├── docs/
│   ├── test-results.md      # 5-PR test (4 approaches)
│   └── test-results-20prs.md # 20-PR test
└── tests/
    ├── prompts/             # All prompts used
    └── results/             # All 41 LLM responses (auditable)
```
