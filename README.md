# Demo Agent Trace

Demo project for attributing each line of code to a person or a Codex session.
The sample application is a small calculator, and the tools in `tools/` create
and query the attribution history.

## Project structure

```text
.
├── README.md                         ← this guide
├── src/
│   └── calc.py                       ← sample functions: modulo and power
├── tools/
│   ├── agent_trace.py                ← manually creates a trace for the latest commit
│   ├── codex_trace_hook.py           ← Codex hook: detects lines added by the agent
│   ├── trace_commit.py               ← post-commit hook: turns pending data into final traces
│   ├── trace_blame.py                ← `git blame` equivalent with human/AI authorship
│   ├── trace_history.py              ← a line's history and attribution in each commit
│   └── trace_stats.py                ← historical analytics for attributed lines
├── .codex/
│   └── hooks.json                    ← runs the Codex hook at the start and end of a turn
├── .agent_trace/
│   ├── .pending/                     ← temporary state; safe to remove without losing final traces
│   └── traces/                       ← final attribution JSON records
└── .git/hooks/post-commit            ← runs `tools/trace_commit.py` after each commit
```

`__pycache__/` directories contain automatically generated Python bytecode;
they are not part of the project logic.

## What happens when code changes

![Attribution flow diagram: manual and Codex edits](assets/agent-trace-flow.svg)

In short, a manual edit does not create a pending event and is recorded as
`human`. An edit made during a Codex turn is associated with its `session_id`;
when committed, the post-commit hook turns it into an `ai` trace with a
`codex://sessions/<session_id>` URL.

## Hooks in use

| Location | Event | Purpose |
| --- | --- | --- |
| `.codex/hooks.json` | `UserPromptSubmit` | Runs `codex_trace_hook.py before` before Codex edits and stores a temporary working-tree snapshot. |
| `.codex/hooks.json` | `Stop` | Runs `codex_trace_hook.py after`, compares the initial and final snapshots, and records added lines with their session and model. |
| `.git/hooks/post-commit` | After `git commit` | Runs `trace_commit.py`, classifies each added line as `ai`, `human`, or `mixed`, and writes the final JSON. |

`.agent_trace/.pending/` contains only the temporary index, baseline snapshot,
and events that have not yet been consolidated. `.agent_trace/traces/`, on the
other hand, contains the final evidence used by the query tools.

## AI attribution metadata

New lines that exactly match captured Codex output are recorded as `ai` with
`confidence: 1.0`. If a commit changes a line already attributed to AI, or
Codex changes a line attributed to a person, it is recorded as `mixed` with
`confidence: 0.8` and a reason. Confidence measures certainty about origin,
not code quality.

Every automatic trace includes the hook version in
`metadata.dev.openai.codex.trace_hook_version`; each Codex conversation
includes its `turn_id` when available. Prompts and secrets are not stored.

For manually created traces, you can also add the tool version, confidence,
and related resources:

```bash
python3 tools/agent_trace.py --type ai \
  --model openai/gpt-5.6-terra \
  --tool codex --tool-version 1.0 \
  --conversation codex://sessions/abc \
  --related issue=https://github.com/acme/demo/issues/42 \
  --confidence 0.8 \
  --confidence-reason "Codex output was manually adjusted before the commit"
```

### Trace example

The hook stores one JSON file per commit in `.agent_trace/traces/`. This is a
representative example of an exact Codex attribution:

```json
{
  "version": "0.1",
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-11-18T16:08:15Z",
  "vcs": {
    "type": "git",
    "revision": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
  },
  "tool": { "name": "codex" },
  "metadata": {
    "dev.openai.codex": { "trace_hook_version": "1.0" }
  },
  "files": [
    {
      "path": "src/calc.py",
      "conversations": [
        {
          "url": "codex://sessions/01a1ef68-ffd1-7d20-ba08-81cf30fa9d02",
          "contributor": {
            "type": "ai",
            "model_id": "openai/gpt-5.6-terra"
          },
          "ranges": [
            {
              "start_line": 3,
              "end_line": 6,
              "content_hash": "sha256:dab7e1133bee5612"
            }
          ],
          "metadata": {
            "confidence": 1.0,
            "confidence_reason": "The line exactly matches captured Codex output.",
            "dev.openai.codex": { "turn_id": "turn_123" }
          }
        }
      ]
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `version`, `id`, `timestamp` | Format version, unique identifier, and when the trace was created. |
| `vcs.type`, `vcs.revision` | Version-control system and the exact commit SHA to which the lines apply. |
| `tool` | Tool that generated the contribution or trace. Automatic traces use Codex. |
| `metadata.dev.openai.codex.trace_hook_version` | Version of this repository's hook; useful for interpreting or migrating its custom metadata. |
| `files[].path` | Relative path of the attributed file. |
| `conversations[].url` | Codex session that produced the change; it does not contain the prompt. |
| `contributor.type` | Origin of the lines: `ai`, `human`, `mixed`, or `unknown`. |
| `contributor.model_id` | Model that generated the AI-attributed portion. |
| `ranges` | Line blocks, indexed from 1 and positioned in the revision named by `vcs.revision`. |
| `content_hash` | Fingerprint of the range's content; helps recognize it if it moves. |
| `confidence` and `confidence_reason` | Attribution certainty and its explanation. `1.0` is an exact match; `0.8` is used for modified Codex output marked as `mixed`. |
| `turn_id` | Codex turn from which the change originated, if the hook received it. |

## End-to-end test walkthrough

Run these steps from the repository root. Use a test branch if you do not want
to mix the demonstration with your current work.

### 1. Prepare a clean test

```bash
git switch -c demo-agent-trace
rm -f .agent_trace/.pending/baseline \
      .agent_trace/.pending/index.tmp \
      .agent_trace/.pending/events.jsonl
```

### 2. Simulate a manual commit

Edit `src/calc.py` yourself; for example, add a `modulo` function.

```python
def modulo(a, b):
    return a % b
```

Then commit the change:

```bash
git add src/calc.py
git commit -m "feat: add modulo manually"
```

The post-commit hook creates a trace in `.agent_trace/traces/`. Because there
is no Codex event for those lines, they are attributed to `human`.

### 3. Simulate a Codex commit

Start a Codex turn in this repository and ask, for example: “add a
`potencia(a, b)` function to `src/calc.py`.” Codex hooks run automatically
when the message is received and when the turn ends. Check the pending event
before committing:

```bash
tail -n 1 .agent_trace/.pending/events.jsonl
```

Then review and commit the change:

```bash
git diff
git add src/calc.py
git commit -m "feat: add power with Codex"
```

The post-commit hook consumes the pending event, generates a trace, and
associates the lines of `potencia` with `ai` and the Codex session ID.

### 4. View the resulting history

Commit history that touched the file:

```bash
git log --oneline -- src/calc.py
git log -p -- src/calc.py
```

Example output:

```text
300eb00 feat: add parameter to power
709a175 feat: add comment
fe4a231 feat: add power with Codex
7a7c2d2 feat: add modulo manually
b20987b Initial commit
```

The second command shows the patch for each commit; for example, the Codex one:

```diff
+def potencia(a, b):
+    return a ** b
```

Line-level attribution, like `git blame`:

```bash
python3 tools/trace_blame.py src/calc.py
python3 tools/trace_blame.py src/calc.py -L 5
```

Current example output:

```text
7a7c2d2    1 human                                | def modulo(a, b):
7a7c2d2    2 human                                |     return a % b
fe4a231    3 ai (openai/gpt-5.6-terra)            |   ← session: codex://sessions/01a1ef68-ffd1-7d20-ba08-81cf30fa9d02
fe4a231    4 ai (openai/gpt-5.6-terra)            |
300eb00    5 mixed (openai/gpt-5.6-terra)         | def potencia(a, b, c):
fe4a231    6 ai (openai/gpt-5.6-terra)            |     return a ** b  ← session: codex://sessions/01a1ef68-ffd1-7d20-ba08-81cf30fa9d02
709a175    7 human                                | # Comments
```

The single-line query returns the mixed attribution for `potencia`:

```text
300eb00    5 mixed (openai/gpt-5.6-terra)         | def potencia(a, b, c):
```

Full history of a line, including every revision that touched it:

```bash
python3 tools/trace_history.py src/calc.py 5
```

Example output:

```text
fe4a231  feat: add power with Codex
    ai (openai/gpt-5.6-terra)            | def potencia(a, b):
                                           conversation: codex://sessions/01a1ef68-ffd1-7d20-ba08-81cf30fa9d02

300eb00  feat: add parameter to power
    mixed (openai/gpt-5.6-terra)         | def potencia(a, b, c):
```

`trace_blame.py` output shows the SHA, line number, contributor type, and
content. For Codex changes, it appends the session to the last consecutive line
that belongs to that session, without repeating it on subsequent lines.
`trace_history.py` adds the commit sequence and shows the session under each
Codex line.

Basic analytics for accumulated traces:

```bash
python3 tools/trace_stats.py
```

Example output:

```text
Agent Trace: historical analytics for added lines
Traces: 5
Commits with traces: 5
Files with traces: 2
Attributed lines: 70

By contributor:
  ai: 66 lines
  human: 3 lines
  mixed: 1 line

By AI model:
  openai/gpt-5.6-terra: 67 lines

By file:
  README.md: 62 lines
  src/calc.py: 8 lines
```

The report shows the number of added lines attributed to each contributor type
(`human`, `ai`, and so on), AI model, and file. It also includes the number of
recorded traces, commits, and files. These are historical metrics: a line that
is later deleted still counts in the commit where it was attributed.
