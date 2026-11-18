"""Hook post-commit: convierte las ediciones de Codex pendientes en una traza del commit."""

import json
import re
import uuid
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path

from agent_trace import added_ranges, content_hash, git
from trace_blame import find_contributor, load_traces

TRACE_DIR = Path(".agent_trace")
EVENTS = TRACE_DIR / ".pending" / "events.jsonl"
HOOK_VERSION = "1.0"
MIXED_SIMILARITY = 0.65
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def load_events():
    if not EVENTS.exists():
        return []
    return [json.loads(line) for line in EVENTS.read_text().splitlines() if line.strip()]


def take_contribution(events, path, text):
    """Clasifica una línea del commit usando la evidencia capturada por Codex."""
    for event in events:
        lines = event["files"].get(path, [])
        if text in lines:
            lines.remove(text)
            return "ai", event, 1.0, "La línea coincide con la salida capturada de Codex."

    candidates = []
    for event in events:
        for source in event["files"].get(path, []):
            score = SequenceMatcher(None, source, text).ratio()
            candidates.append((score, event, source))
    if candidates:
        score, event, source = max(candidates, key=lambda candidate: candidate[0])
        if score >= MIXED_SIMILARITY:
            event["files"][path].remove(source)
            reason = "La línea capturada de Codex fue modificada antes del commit."
            return "mixed", event, 0.8, reason
    return "human", None, None, None


def replaced_lines(revision, path):
    """Relaciona cada línea añadida con la línea reemplazada, si la hay."""
    parents = git("rev-list", "--parents", "-n", "1", revision).split()
    if len(parents) < 2:
        return {}, None
    parent = parents[1]
    diff = git("diff", "-U0", "--no-color", parent, revision, "--", path)
    replacements, deleted, added = {}, [], []

    def save_hunk():
        for old_line, new_line in zip(deleted, added):
            replacements[new_line] = old_line

    old_line = new_line = None
    for row in diff.splitlines():
        if match := HUNK_RE.match(row):
            save_hunk()
            deleted, added = [], []
            old_line, new_line = int(match.group(1)), int(match.group(3))
        elif old_line is not None and row.startswith("-"):
            deleted.append(old_line)
            old_line += 1
        elif new_line is not None and row.startswith("+"):
            added.append(new_line)
            new_line += 1
    save_hunk()
    return replacements, parent


def contributor_at_revision(traces, revision, path, line):
    """Obtiene la atribución de una línea en una revisión anterior."""
    output = git("blame", "--porcelain", revision, "-L", f"{line},{line}", "--", path)
    header = output.splitlines()[0].split()
    sha, original_line = header[0], int(header[1])
    return find_contributor(traces, sha, path, original_line)[0]


def main():
    revision = git("rev-parse", "HEAD").strip()
    events = load_events()
    traces = load_traces()
    files = []
    for path, ranges in added_ranges(revision).items():
        content = git("show", f"{revision}:{path}").splitlines()
        replacements, parent = replaced_lines(revision, path)
        labels = []
        for start, end in ranges:
            for n in range(start, end + 1):
                kind, event, confidence, reason = take_contribution(events, path, content[n - 1])
                previous = (contributor_at_revision(traces, parent, path, replacements[n])
                            if n in replacements else {})
                if previous.get("type") in {"ai", "mixed"}:
                    kind = "mixed"
                    confidence = 0.8
                    reason = "Una línea atribuida previamente a IA fue modificada en este commit."
                    model = previous.get("model_id") or (event or {}).get("model_id")
                    key = (kind, None, model, confidence, reason, None)
                elif previous.get("type") == "human" and event:
                    kind = "mixed"
                    confidence = 0.8
                    reason = "Una línea atribuida previamente a una persona fue modificada por IA."
                    key = (kind, event["session_id"], event["model_id"], confidence, reason,
                           event.get("turn_id"))
                else:
                    key = (kind, event["session_id"] if event else None,
                           event["model_id"] if event else None, confidence, reason,
                           event.get("turn_id") if event else None)
                labels.append((n, key))
        groups = {}
        for n, key in labels:
            rngs = groups.setdefault(key, [])
            if rngs and rngs[-1][1] == n - 1:
                rngs[-1][1] = n
            else:
                rngs.append([n, n])
        conversations = []
        for (kind, session, model, confidence, reason, turn_id), rngs in groups.items():
            contributor = {"type": kind}
            if model:
                contributor["model_id"] = model
            conv = {"contributor": contributor, "ranges": [
                {"start_line": start, "end_line": end,
                 "content_hash": content_hash(revision, path, start, end)}
                for start, end in rngs
            ]}
            if session:
                conv["url"] = f"codex://sessions/{session}"
            if confidence is not None:
                conv["metadata"] = {
                    "confidence": confidence,
                    "confidence_reason": reason,
                    "dev.openai.codex": {"turn_id": turn_id},
                }
            conversations.append(conv)
        files.append({"path": path, "conversations": conversations})
    if files:
        write_record(revision, files)
    prune(events)


def write_record(revision, files):
    record = {
        "version": "0.1", "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "vcs": {"type": "git", "revision": revision},
        "tool": {"name": "codex"},
        "metadata": {"dev.openai.codex": {"trace_hook_version": HOOK_VERSION}},
        "files": files,
    }
    out = TRACE_DIR / "traces" / f"{record['id']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(f"agent-trace: {out}")


def prune(events):
    for event in events:
        for path, lines in event["files"].items():
            current = Path(path).read_text().splitlines() if Path(path).exists() else []
            event["files"][path] = [line for line in lines if line in current]
    remaining = [event for event in events if any(event["files"].values())]
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    EVENTS.write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in remaining))


if __name__ == "__main__":
    main()
