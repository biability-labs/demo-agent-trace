"""Como git blame, pero atribuyendo líneas a humano o IA."""
import argparse
import json
import subprocess
from pathlib import Path

TRACE_DIR = Path(".agent_trace") / "traces"


def load_traces():
    by_revision = {}
    for trace in TRACE_DIR.glob("*.json"):
        record = json.loads(trace.read_text())
        revision = record.get("vcs", {}).get("revision")
        if revision:
            by_revision.setdefault(revision, []).append(record)
    return by_revision


def blame(path, line=None):
    command = ["git", "blame", "--porcelain"]
    if line:
        command += ["-L", f"{line},{line}"]
    output = subprocess.check_output(command + ["--", path], text=True)
    result, filenames = [], {}
    sha = original = final = None
    for row in output.splitlines():
        if row.startswith("\t"):
            result.append((sha, filenames[sha], original, final, row[1:]))
        elif row.startswith("filename "):
            filenames[sha] = row[9:]
        else:
            parts = row.split()
            if len(parts) >= 3 and len(parts[0]) == 40 and parts[1].isdigit():
                sha, original, final = parts[0], int(parts[1]), int(parts[2])
    return result


def find_contributor(traces, sha, path, original_line):
    for record in traces.get(sha, []):
        for file in record["files"]:
            if file["path"] != path:
                continue
            for conversation in file["conversations"]:
                for line_range in conversation["ranges"]:
                    if line_range["start_line"] <= original_line <= line_range["end_line"]:
                        return (line_range.get("contributor") or conversation.get("contributor") or {},
                                conversation.get("url"))
    return {"type": "unknown"}, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("-L", "--line", type=int)
    args = parser.parse_args()
    previous_url = None
    for sha, path, original, final, text in blame(args.path, args.line):
        contributor, url = find_contributor(load_traces(), sha, path, original)
        who = contributor.get("type", "unknown")
        if contributor.get("model_id"):
            who += f" ({contributor['model_id']})"
        session = f"  ← sesión: {url}" if url and url != previous_url else ""
        print(f"{sha[:7]} {final:>4} {who:<36} | {text}{session}")
        previous_url = url


if __name__ == "__main__":
    main()
