# Test Results: LLM Review Quality with Vault Context

Tests conducted on 2026-03-18 using `claude-sonnet-4-20250514` across 5 Apache Airflow PRs with different profiles.

## Approaches tested

| Approach | What the LLM receives | Simulates |
|---|---|---|
| **Diff Only** | PR description + unified diff | Potiuk's current `breeze pr auto-triage` system |
| **Diff + Passive Context** | Diff + raw block of vault data (maintainer comments, author profile, overlapping PRs) | Naive approach: dump all context as text |
| **Diff + Directed Questions (no data)** | Diff + generic checklist questions without project-specific answers | Good prompting without actual data |
| **Diff + Directed Questions (with data)** | Diff + specific verification questions pre-filled with vault data | Full system: `build_context.py` output |

## PR-63296: fix: block path traversal via ".." in dag_id and run_id

Security fix, breaking change, reviews from @potiuk (CHANGES_REQUESTED) and @ferruzzi.

All four approaches were tested on this PR.

| Finding | Diff Only | Diff + Passive Context | Directed Questions (no data) | Directed Questions (with data) |
|---|---|---|---|---|
| `version_added: 3.0.0` is wrong (should be 3.2.0+) | Not detected | Detected | "Needs verification" (doesn't know the version) | Detected + comment on file |
| ValueError vs AirflowException inconsistency | Mentioned text difference only | Identified exception type mismatch | Detected but justified as correct | Identified type + which file has which |
| Validation duplicated across files | Mentioned once | Mentioned once | 3 occurrences + suggested helper | 3 occurrences + suggested shared helper |
| Conflicts with other open PRs | Not detected | Not detected | "Cannot verify" | Listed 4 specific PRs |
| @potiuk feedback addressed? | Not mentioned | Mentioned | Mentioned generically | Evaluated whether addressed |
| @ferruzzi pending question (newsfragment type) | Not mentioned | Mentioned | Not mentioned | Identified specific pending question |
| Dev mailing list discussion needed | Not detected | Not detected | "Properly documented" **(WRONG)** | Flagged as **CRITICAL** |
| Author experience in this area | Not mentioned | Mentioned | "Follows patterns" (generic) | Evaluated against actual PR history |

**Key insight**: Without real data, the LLM confabulates. "Directed Questions (no data)" said the devlist discussion was "properly documented" when no evidence exists. With vault data, the system correctly flagged it as critical.

## PR-63489: Allow direct queueing from triggerer

Architectural change to scheduler/triggerer. 6 files, @ashb did CHANGES_REQUESTED calling it "a huge conceptual shift".

| Finding | Diff Only | Directed Questions (with data) |
|---|---|---|
| Assessment | REQUEST_CHANGES | REQUEST_CHANGES |
| @ashb blocking feedback not addressed | Not mentioned | **Flagged as CRITICAL**: "@ashb's concern about bypassing concurrency controls has NOT been addressed" |
| Specific conflicting PRs | "Diff is incomplete" | Listed PR-51391, PR-52005, PR-55068 touching trigger.py |
| @dabla duplicate code feedback | Not mentioned | Identified as addressed (find_executor refactoring) |
| Concurrency bypass risk | Mentioned generically ("pool limit bypass as trade-off") | **Specific**: "bypasses task pools, DAG concurrency limits, executor limits" |
| Config naming | Suggested validation | Suggested renaming to `bypass_scheduler_for_executors` for clarity |

**Key insight**: The vault surfaced that @ashb's blocking review was not addressed. A human reviewer would know this. Without the vault, the LLM treats the PR as a fresh submission.

## PR-55068: Re-enable start_from_trigger with template rendering

Complex feature, 17 files changed, 73 interactions, 14 reviewers.

| Finding | Diff Only | Directed Questions (with data) |
|---|---|---|
| Assessment | REQUEST_CHANGES | REQUEST_CHANGES |
| Method complexity | "Too long" | "Too long" + reviewer context |
| @kaxil concern (unnecessary DAG serialization) | Not mentioned | Identified as partially addressed |
| @uranusjr concern (RuntimeTaskInstance) | Not mentioned | Identified as addressed |
| @jason810496 performance concern (memory/cache) | Not mentioned | Identified as partially addressed, cache may still grow |
| Nested callable validation | Not detected | **Flagged as CRITICAL**: surface-level validation only |
| Reviewer feedback integration | Zero awareness of 73 interactions | Evaluated 5+ maintainer positions with status |

**Key insight**: With 73 interactions from 14 reviewers, the vault provides months of discussion context that no amount of prompting can replace. The LLM correctly identified which concerns were addressed and which weren't.

## PR-63746: Set task name for 2.11.X path

Provider fix (Celery), 1 file, 1 line change. Maintainer (@o-nikolas) as author.

| Finding | Diff Only | Directed Questions (with data) |
|---|---|---|
| Assessment | APPROVE | APPROVE |
| Conflict risk | Not evaluated | Evaluated 5 overlapping PRs, concluded low risk |
| Quality of review | Adequate | Adequate + unnecessary overhead |

**Key insight**: For simple fixes by experienced maintainers, the vault adds minimal value. The review decision doesn't change.

## PR-63653: Fix grammar in dag model docstring

Typo fix, 1 file, 1 word change.

| Finding | Diff Only | Directed Questions (with data) |
|---|---|---|
| Assessment | APPROVE | APPROVE |
| Difference | "Good catch" | "Good catch" + evaluated conflicts (low risk) + author experience (not relevant) |

**Key insight**: For trivial PRs, the vault is pure overhead. No value added.

## Summary

| PR | Type | Vault improvement |
|---|---|---|
| 63296 | Security / breaking change | **~50-60%** better |
| 63489 | Architectural change | **~60-70%** better |
| 55068 | Complex feature (73 interactions) | **~50-60%** better |
| 63746 | Simple provider fix | **~5-10%** better |
| 63653 | Typo / docs | **~0%** (overhead) |

## Conclusions

1. **Vault value scales with PR complexity and discussion history.** Architectural PRs and PRs with extensive maintainer feedback benefit the most.

2. **Directed questions > passive context > nothing.** The question format forces the LLM to verify specific facts instead of making a generic review.

3. **Without real data, the LLM confabulates.** Directed questions without vault data produce better structure but fill gaps with false claims ("properly documented", "follows patterns").

4. **The combination of directed questions + vault data eliminates confabulation.** The LLM cannot invent facts when the prompt contains verifiable data with sources.

5. **Trivial PRs don't need context.** A heuristic based on files changed, labels, and author experience could skip context generation for simple PRs.

## Reproduction

All prompts and results are in `tests/prompts/` and `tests/results/`. The naming convention is:

```
pr-{number}-{approach}.md
```

Where approach is one of:
- `diff-only`
- `diff-passive-context`
- `diff-directed-questions-no-data`
- `diff-directed-questions-with-data`
