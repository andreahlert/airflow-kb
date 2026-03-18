Subject: [DISCUSS] Adding historical context to LLM-assisted PR triage

Hi everyone,

Following the auto-triage discussion [1], I've been experimenting with something that might help with one of the gaps Jarek mentioned: "The LLM assessments are pretty good, but a few were significantly wrong."

I think a big reason for those wrong assessments is that the LLM starts every review from zero. It sees the diff and the description, but it doesn't know what happened before. It doesn't know @ashb rejected a similar approach last month, or that the author has never worked in that area of the codebase, or that there's an active devlist thread about the same topic.

So I built a prototype to test whether giving the LLM historical context actually makes a difference.

**What I did**

I synced Airflow's GitHub data (2,335 PRs with comments, reviews, inline review comments, and diffs), 6 months of the dev mailing list (426 threads, full email bodies), and recent Slack conversations into a local markdown knowledge base. About 6,100 files, 139 MB, all searchable in milliseconds.

Then I wrote a script that, given a PR number, queries this knowledge base and generates specific verification questions for the LLM. Not a generic checklist, but factual questions with data. Things like: "version_added says 3.0.0 but current stable is 3.1.8, is this correct?" or "@potiuk requested changes on March 10 saying this is extremely risky without a config flag. Has this been addressed?" or "PR-63489 and PR-45931 also modify config.yml. Are there conflicts?"

**How I tested**

First I tested four different approaches on one PR (PR-63296, the path traversal fix) to understand what works:

- Diff only (what the system does today)
- Diff + passive context dump (just paste all the history)
- Directed questions without real data (good format, no facts)
- Directed questions with vault data (specific questions with verified facts)

The interesting finding was that directed questions without data actually made things worse in some cases. The LLM filled in the gaps with false claims. It said the devlist discussion was "properly documented" when there was no discussion at all. With real data from the vault, it correctly flagged that as a critical issue.

Then I expanded to 20 PRs across different areas (providers, scheduler, task-sdk, API, dev-tools) and compared "diff only" vs "directed questions with data."

**Results across 20 PRs**

In 6 of 20 PRs (30%), the assessment changed:

- 3 PRs went from APPROVE to REQUEST_CHANGES. The vault caught unaddressed maintainer feedback, governance violations, and conflicts with other open PRs that the diff alone couldn't reveal. The strongest case: PR-56187 (100 files, 132 interactions, the most discussed PR in the dataset) was approved by "diff only" but the vault found 4 critical issues.

- 2 PRs went from REQUEST_CHANGES to APPROVE. The vault showed that maintainer concerns had already been addressed, reducing false positives.

- 55% of all PRs had at least one critical finding that only the vault could detect (wrong version fields, missing devlist discussion, unaddressed feedback, conflicts with other open PRs).

All prompts and LLM responses are published and auditable: https://github.com/andreahlert/airflow-kb

**How this could work with the existing system**

The auto-triage tool already has a clean separation between deterministic checks and LLM assessment. The context layer would sit between those two: before `_build_user_message()` or `_build_review_user_message()` sends the prompt to the LLM, a function queries the local knowledge base and appends the directed questions. Everything else stays the same. Human in the loop, maintainer in the driver's seat, no automated posting.

The vault sync could run as a cron job (like the canary build cache already does) or on-demand before a triage session.

I'd love to hear thoughts on whether this direction is useful. Happy to put together a PR if there's interest.

Andre

[1] https://lists.apache.org/thread/ly6lrm2gc4p7p54vomr8621nmb1pvlsk
