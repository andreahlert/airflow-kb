# airflow-kb

Agentic knowledge base for Apache Airflow. Syncs GitHub PRs, Issues, and diffs to a local Obsidian vault, then generates directed review context that improves LLM-based code review quality.

## How it works

1. **Sync** GitHub data (PRs, Issues, comments, reviews, diffs) to local markdown files
2. **Build context** by querying the vault for historical data related to a specific PR
3. **Generate directed questions** that force the LLM to verify specific facts instead of guessing
4. **Run LLM review** with the enriched prompt

## Quick start

```bash
# Sync open PRs with diffs
python src/sync_github.py --mode prs-open --with-diffs

# Build review context for a PR
python src/build_context.py 63296

# Run full LLM review with context
python src/build_context.py 63296 --review
```

## Vault structure

```
vault/
├── PRs/
│   ├── PR-12345.md          # metadata, description, comments, reviews
│   └── diffs/PR-12345.diff  # unified diff (separate for performance)
├── Issues/
│   └── ISSUE-9876.md        # metadata, description, comments
├── People/
│   └── potiuk.md            # auto-generated contributor profiles
└── Scripts/
    └── .sync_state.json     # incremental sync state
```

## Test results

See [docs/test-results.md](docs/test-results.md) for the full comparison of review approaches.
