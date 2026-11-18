"""Hook de Codex para Agent Trace."""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def git(*args, env=None, cwd=None):
    return subprocess.check_output(["git", *args], text=True, env=env, cwd=cwd)


def snapshot(root):
    pending = root / ".agent_trace" / ".pending"
    pending.mkdir(parents=True, exist_ok=True)
    tmp_index = pending / "index.tmp"
    real_index = Path(git("rev-parse", "--path-format=absolute", "--git-path", "index", cwd=root).strip())
    if real_index.exists():
        shutil.copy(real_index, tmp_index)
    env = {**os.environ, "GIT_INDEX_FILE": str(tmp_index)}
    git("add", "-A", "--", ".", ":(exclude).agent_trace", env=env, cwd=root)
    return git("write-tree", env=env, cwd=root).strip()


def added_lines(root, tree_a, tree_b):
    diff = git("diff", "-U0", "--no-color", tree_a, tree_b, cwd=root)
    result = {}
    path = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = None if line == "+++ /dev/null" else line[6:]
            continue
        if not path:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            result.setdefault(path, []).append(line[1:])
    return result


def main():
    mode = sys.argv[1]
    payload = json.load(sys.stdin)
    root = Path(git("rev-parse", "--show-toplevel", cwd=payload.get("cwd")).strip())
    pending = root / ".agent_trace" / ".pending"
    baseline = pending / "baseline"
    if mode == "before":
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(snapshot(root))
        return
    if not baseline.exists():
        return
    tree_after = snapshot(root)
    changes = added_lines(root, baseline.read_text().strip(), tree_after)
    baseline.unlink()
    model = payload.get("model")
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session_id": payload.get("session_id"),
        "turn_id": payload.get("turn_id"),
        "model_id": f"openai/{model}" if model else None,
        "files": changes,
    }
    if changes:
        with open(pending / "events.jsonl", "a") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"agent-trace hook: {e}", file=sys.stderr)
    sys.exit(0)
