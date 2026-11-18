"""Historia completa de una línea y quién la escribió."""
import argparse
import re
import subprocess
from pathlib import Path

from trace_blame import find_contributor, load_traces

HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def line_history(path, line):
    if line < 1:
        raise ValueError("El número de línea debe ser mayor que cero.")

    try:
        with Path(path).open(encoding="utf-8") as source:
            total_lines = sum(1 for _ in source)
    except OSError as error:
        raise ValueError(f"No se puede leer {path}: {error.strerror}.") from error
    if line > total_lines:
        raise ValueError(f"La línea {line} no existe en {path} (tiene {total_lines} líneas).")

    output = subprocess.check_output(
        ["git", "log", "-L", f"{line},{line}:{path}", "--format=COMMIT %H %s", "--no-color"], text=True)
    history, current, new_line = [], None, 0
    for row in output.splitlines():
        if row.startswith("COMMIT "):
            sha, _, subject = row[7:].partition(" ")
            current = {"sha": sha, "subject": subject, "path": path, "added": []}
            history.append(current)
        elif row.startswith("+++ "):
            if row != "+++ /dev/null":
                current["path"] = row[6:]
        elif match := HUNK_RE.match(row):
            new_line = int(match.group(1))
        elif row.startswith("+"):
            current["added"].append((new_line, row[1:]))
            new_line += 1
        elif row.startswith(" "):
            new_line += 1
    return history


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("line", type=int)
    args = parser.parse_args()
    traces = load_traces()
    try:
        history = line_history(args.path, args.line)
    except ValueError as error:
        parser.error(str(error))
    for entry in reversed(history):
        print(f"{entry['sha'][:7]}  {entry['subject']}")
        for line, text in entry["added"]:
            contributor, url = find_contributor(traces, entry["sha"], entry["path"], line)
            who = contributor.get("type", "unknown")
            if contributor.get("model_id"):
                who += f" ({contributor['model_id']})"
            print(f"    {who:<36} | {text}")
            if url:
                print(f"    {'':<36}   conversación: {url}")
        print()


if __name__ == "__main__":
    main()
