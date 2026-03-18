## PR Review: Simplify approach for creating dag run and task spans

### Summary

This PR fundamentally redesigns Airflow's OpenTelemetry tracing by replacing a complex span tracking system with a much simpler approach. The changes emit dag run spans upon completion and task spans during execution, using standard OTEL patterns instead of custom abstractions. While this simplifies the codebase significantly, it represents a breaking behavioral change that removes detailed internal spans in favor of a cleaner, more maintainable implementation.

**Overall Assessment: REQUEST_CHANGES**

### Context Findings

**Question 1 - VERSION CHECK: ✅ RESOLVED**
- Finding: New configurations properly use `version_added: 3.2.0` 
- Severity: info

**Question 16 - MAINTAINER FEEDBACK: ✅ RESOLVED** 
- Finding: `configure_otel()` moved inside `initialize()` function in settings.py
- Severity: info

**Question 51 - MAINTAINER FEEDBACK: ✅ RESOLVED**
- Finding: Configuration uses full word "milliseconds" as requested
- Severity: info

**Question 54 - MAINTAINER FEEDBACK: ✅ RESOLVED**
- Finding: Version updated to 3.2.0 for new configurations
- Severity: info

**Question 55 - GOVERNANCE CHECK: ❌ UNADDRESSED**
- Finding: No evidence of dev mailing list discussion for this breaking change
- Severity: critical

### Major Concerns

1. **Breaking Change Without Governance Discussion** - This represents a significant behavioral change that fundamentally alters how spans are created and structured. Apache projects typically require dev list discussion for such changes.

2. **Loss of Detailed Observability** - The previous implementation provided detailed spans for internal Airflow operations (scheduler events, executor metrics, etc.). This simplified approach only provides dag run and task level spans, potentially reducing observability for operations teams.

3. **Different Span Hierarchy** - The new approach creates a fundamentally different span structure that will break existing dashboards, alerts, and monitoring setups that depend on the current span relationships.

### Comments

```json
{
  "summary": "This PR significantly simplifies Airflow's OpenTelemetry implementation by replacing complex span tracking with standard OTEL patterns. While the code is much cleaner, this represents a breaking behavioral change that removes detailed internal spans and alters the span hierarchy. The governance concern and observability impact need to be addressed before merging.",
  "overall_assessment": "REQUEST_CHANGES", 
  "comments": [
    {
      "path": "airflow-core/src/airflow/config_templates/config.yml",
      "line": 1425,
      "body": "Consider adding a migration guide in the deprecation notice explaining how users can achieve similar observability with the new approach.",
      "category": "documentation"
    },
    {
      "path": "airflow-core/src/airflow/observability/traces/__init__.py", 
      "line": 115,
      "body": "The `_load_exporter_from_env()` function could benefit from better error handling. If the entry point loading fails, the error message could be more helpful for debugging.",
      "category": "error_handling"
    },
    {
      "path": "airflow-core/src/airflow/jobs/scheduler_job_runner.py",
      "line": 1295,
      "body": "All the span tracking code removal means we lose observability into scheduler performance. Consider documenting what observability is lost and how operators can monitor scheduler health with the new approach.",
      "category": "observability"
    },
    {
      "path": "task-sdk/src/airflow/sdk/execution_time/task_runner.py",
      "line": 148,
      "body": "The span naming convention `task_run.{task_id}` is good, but consider if we need to include more context like try_number for retry scenarios to distinguish spans from different attempts.",
      "category": "naming"
    },
    {
      "path": "airflow-core/tests/integration/otel/test_otel.py", 
      "line": 510,
      "body": "The test expectations show a much simpler span hierarchy. While cleaner, this represents a breaking change for users who depend on the more detailed span structure. Document this change prominently.",
      "category": "breaking_change"
    }
  ],
  "context_findings": [
    {"question_number": 1, "finding": "New configurations properly use version_added: 3.2.0", "severity": "info"},
    {"question_number": 16, "finding": "configure_otel() moved inside initialize() function as requested", "severity": "info"}, 
    {"question_number": 51, "finding": "Configuration uses full word 'milliseconds' as requested", "severity": "info"},
    {"question_number": 54, "finding": "Version updated to 3.2.0 for new configurations", "severity": "info"},
    {"question_number": 55, "finding": "No evidence of dev mailing list discussion for this breaking change", "severity": "critical"}
  ]
}
```

