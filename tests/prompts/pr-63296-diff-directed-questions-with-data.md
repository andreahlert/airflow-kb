You are a code reviewer for Apache Airflow. Review this PR and provide your assessment.

You MUST address every question in the DIRECTED REVIEW CONTEXT section. These are based on
historical project data and maintainer patterns.

Output JSON with:
- summary (2-3 sentences, must reference findings from the verification questions)
- overall_assessment (APPROVE/REQUEST_CHANGES/COMMENT)
- comments: array of {path, line, body, category}
- context_findings: array of {question_number, finding, severity: "critical"|"warning"|"info"}

## PR #63296: fix: block path traversal via ".." in dag_id and run_id

### Description

## Problem

`validate_key()` and `validate_run_id()` both allow `..` in their values. Since `dag_id` and `run_id` are used in log file paths (e.g. `dag_id=.../run_id=.../`), a crafted value containing `..` could theoretically traverse outside the intended log directory.

## DIRECTED REVIEW CONTEXT

The following verification questions are generated from the project knowledge base. Each question MUST be addressed in your review.

### Question 1
VERSION CHECK: version_added says 3.0.0 but current stable is 3.1.8. Should probably be 3.2.0 or later.

### Question 2
CONSISTENCY CHECK: Multiple exception types raised: AirflowException, ValueError. Should these be consistent?

### Question 3
DUPLICATION CHECK: Same validation check appears 3 times. Consider extracting to a shared helper.

### Question 4
CONFLICT CHECK: These open PRs modify the same files:
  - PR-34487 (Add watchdog for immediately processing changes in the DAGs folder) touches: dag.py
  - PR-36504 ([POC][WIP] Async SQLAlchemy sessions in Airflow) touches: config.yml
  - PR-45931 (Add config option [secrets]backends_order) touches: config.yml
  - PR-51134 (Serialized Dag - Write Dag Race Condition- Reopen) touches: dag.py
  - PR-51391 (AIP-88: Lazy expandable task mapping) touches: dagrun.py
  Are there merge conflicts or semantic conflicts with this PR?

### Question 5
AUTHOR EXPERIENCE: @YoannAbriel has 20 PRs, mostly in: task-sdk (6), API (5), Scheduler (3), deadline-alerts (2), db-migrations (2). This PR touches core which is NEW for this author. Does the approach follow established patterns in these areas?

### Question 6
MAINTAINER FEEDBACK: @potiuk (CHANGES_REQUESTED, 2026-03-10): "This is extremely risky change if we do not have a mechanism to allow those. 

If we merge thius change, suddenly all the Dags of someone who has `..` in their name will fail and they will have to manually convert their Dags. People migh have weird conventions for names and" Has this feedback been addressed in the current version?

### Question 7
MAINTAINER FEEDBACK: @ferruzzi (COMMENTED, 2026-03-17): "Still pending the config flag to enable/disable the feature, but nice progress.  Ping me when you are ready for a re-review.

> **[[ferruzzi]]** on `airflow-core/newsfragments/63296.significant.rst:1`
> @potiuk - What do you think, does this count as a `significant` or should it be a bugfix one-line" Has this feedback been addressed in the current version?

### Question 8
GOVERNANCE CHECK: This appears to be a breaking/behavioral change. Apache Airflow requires significant changes to be discussed on the dev mailing list before merging. Has this been discussed there?

---

## ADDITIONAL CONTEXT

MAINTAINER HISTORY on files touched by this PR:
  - @potiuk on PR-62343 (config.yml): "@anishgirianish This PR has been converted to **draft** because it does not yet meet our [Pull Request quality criteria](https://github.com/apache/air"
  - @kaxil on PR-62343 (config.yml): "> @pierrejeambrun  thank you very much for the review. The dev list discussion ([thread](https://lists.apache.org/thread/xd7zmyp95y77cw36mb5wjp17dyynz"
  - @ferruzzi on PR-62343 (config.yml): "+0.5 Consider this an approval AS LONG AS someone else with the API background also approves that portion.

I'm still learning the API side, but from "
  - @ashb on PR-63489 (config.yml): "This by passes all manner of concurrency controls that exist - pretty much all of them they exist today. 

This is also a huge conceptual shift and no"
  - @jscheffl on PR-63489 (config.yml): "> This by passes all manner of concurrency controls that exist - pretty much all of them they exist today.
> 
> This is also a huge conceptual shift a"



### Diff

```diff
diff --git a/airflow-core/newsfragments/63296.significant.rst b/airflow-core/newsfragments/63296.significant.rst
new file mode 100644
index 0000000000000..11bfbfb5b8970
--- /dev/null
+++ b/airflow-core/newsfragments/63296.significant.rst
@@ -0,0 +1,16 @@
+Block path traversal via ``..`` in ``dag_id`` and ``run_id``
+
+DAG IDs and run IDs containing ``..`` are now rejected by default to prevent path traversal.
+A configuration flag ``[core] allow_dotdot_in_ids`` (default: ``False``) is available for
+environments that rely on ``..`` in identifiers.
+
+* Types of change
+
+  * [ ] Dag changes
+  * [x] Config changes
+  * [x] API changes
+  * [ ] CLI changes
+  * [x] Behaviour changes
+  * [ ] Plugin changes
+  * [ ] Dependency changes
+  * [ ] Code interface changes
diff --git a/airflow-core/src/airflow/config_templates/config.yml b/airflow-core/src/airflow/config_templates/config.yml
index 0c002f5276cfe..bd764323c1dfc 100644
--- a/airflow-core/src/airflow/config_templates/config.yml
+++ b/airflow-core/src/airflow/config_templates/config.yml
@@ -439,6 +439,16 @@ core:
       example: ~
       default: "1024"
 
+    allow_dotdot_in_ids:
+      description: |
+        Allow ``..`` (consecutive dots) in DAG IDs and run IDs. By default, ``..`` is blocked to prevent
+        path traversal attacks. Set to ``True`` only if you have existing DAGs or runs whose IDs contain
+        ``..`` and cannot be renamed.
+      version_added: 3.0.0
+      type: boolean
+      example: ~
+      default: "False"
+
     daemon_umask:
       description: |
         The default umask to use for process when run in daemon mode (scheduler, worker,  etc.)
diff --git a/airflow-core/src/airflow/models/dagrun.py b/airflow-core/src/airflow/models/dagrun.py
index 9923781fbe58d..40ef2f8f37e48 100644
--- a/airflow-core/src/airflow/models/dagrun.py
+++ b/airflow-core/src/airflow/models/dagrun.py
@@ -387,6 +387,8 @@ def __repr__(self):
     def validate_run_id(self, key: str, run_id: str) -> str | None:
         if not run_id:
             return None
+        if ".." in run_id and not airflow_conf.getboolean("core", "allow_dotdot_in_ids", fallback=False):
+            raise ValueError(f"The run_id '{run_id}' must not contain '..' to prevent path traversal")
         if re.match(RUN_ID_REGEX, run_id):
             return run_id
         regex = airflow_conf.get("scheduler", "allowed_run_id_pattern").strip()
diff --git a/airflow-core/src/airflow/serialization/definitions/dag.py b/airflow-core/src/airflow/serialization/definitions/dag.py
index a8fa92d12ce9a..e37a62b369742 100644
--- a/airflow-core/src/airflow/serialization/definitions/dag.py
+++ b/airflow-core/src/airflow/serialization/definitions/dag.py
@@ -548,6 +548,9 @@ def create_dagrun(
         if not isinstance(run_id, str):
             raise ValueError(f"`run_id` should be a str, not {type(run_id)}")
 
+        if ".." in run_id and not airflow_conf.getboolean("core", "allow_dotdot_in_ids", fallback=False):
+            raise ValueError(f"The run_id '{run_id}' must not contain '..' to prevent path traversal")
+
         # This is also done on the DagRun model class, but SQLAlchemy column
         # validator does not work well for some reason.
         if not re.match(RUN_ID_REGEX, run_id):
diff --git a/airflow-core/src/airflow/utils/helpers.py b/airflow-core/src/airflow/utils/helpers.py
index 5e2dd1b9dedf2..604e8271f861b 100644
--- a/airflow-core/src/airflow/utils/helpers.py
+++ b/airflow-core/src/airflow/utils/helpers.py
@@ -61,6 +61,8 @@ def validate_key(k: str, max_length: int = 250):
             f"The key {k!r} has to be made of alphanumeric characters, dashes, "
             f"dots and underscores exclusively"
         )
+    if ".." in k and not conf.getboolean("core", "allow_dotdot_in_ids", fallback=False):
+        raise AirflowException(f"The key {k!r} must not contain consecutive dots ('..') to prevent path traversal")
 
 
 def ask_yesno(question: str, default: bool | None = None, output_fn=print) -> bool:
diff --git a/airflow-core/tests/unit/models/test_dagrun.py b/airflow-core/tests/unit/models/test_dagrun.py
index 2bed00cf75c99..902c8e4a0a728 100644
--- a/airflow-core/tests/unit/models/test_dagrun.py
+++ b/airflow-core/tests/unit/models/test_dagrun.py
@@ -2961,6 +2961,24 @@ def test_dag_run_id_config(session, dag_maker, pattern, run_id, result):
                 dag_maker.create_dagrun(run_id=run_id, run_type=run_type)
 
 
+@pytest.mark.db_test
+@pytest.mark.need_serialized_dag(False)
+@pytest.mark.parametrize(
+    "run_id",
+    [
+        "manual__..%2F..%2Fetc%2Fpasswd",
+        "my..run",
+        "..",
+    ],
+)
+def test_dag_run_id_rejects_path_traversal(session, dag_maker, run_id):
+    """run_id containing '..' should be rejected to prevent path traversal."""
+    with dag_maker():
+        pass
+    with pytest.raises(ValueError, match=r"must not contain '\.\.'"):
+        dag_maker.create_dagrun(run_id=run_id, run_type=DagRunType.MANUAL)
+
+
 def _get_states(dr):
     """
     For a given dag run, get a dict of states.
diff --git a/airflow-core/tests/unit/utils/test_helpers.py b/airflow-core/tests/unit/utils/test_helpers.py
index 8e16d11869843..ab82f82047568 100644
--- a/airflow-core/tests/unit/utils/test_helpers.py
+++ b/airflow-core/tests/unit/utils/test_helpers.py
@@ -140,6 +140,16 @@ def test_build_airflow_dagrun_url(self):
                 AirflowException,
             ),
             (" " * 251, f"The key: {' ' * 251} has to be less than 250 characters", AirflowException),
+            (
+                "my..key",
+                "The key 'my..key' must not contain consecutive dots ('..') to prevent path traversal",
+                AirflowException,
+            ),
+            (
+                "..",
+                "The key '..' must not contain consecutive dots ('..') to prevent path traversal",
+                AirflowException,
+            ),
         ],
     )
     def test_validate_key(self, key_id, message, exception):

```
