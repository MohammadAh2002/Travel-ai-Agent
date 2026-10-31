# Eval scorecard

Cases file: `cases.sample.jsonl` · runs: **10** · passed: **8** (**80%**)

Turn latency: avg **15.07 s**, p95 **29.45 s** · cost: not reported by the app

| case | category | result | why it failed |
|---|---|---|---|
| S3-01 | happy_path | ✅ |  |
| S3-02 | happy_path | ✅ |  |
| S3-03 | rejection | ✅ |  |
| S3-04 | revision | ✅ |  |
| S3-05 | conflict | ❌ | the case wanted to approve/reject, but the last reply had no pending_action |
| S3-06 | conflict | ✅ |  |
| S3-07 | tool_failure | ✅ |  |
| S3-08 | memory | ✅ |  |
| S3-09 | guardrail | ❌ | the case wanted to approve/reject, but the last reply had no pending_action |
| S3-10 | clarification | ✅ |  |

| category | passed |
|---|---|
| clarification | 1/1 |
| conflict | 1/2 |
| guardrail | 0/1 |
| happy_path | 2/2 |
| memory | 1/1 |
| rejection | 1/1 |
| revision | 1/1 |
| tool_failure | 1/1 |
