"""Genera una traza de atribución para las líneas añadidas en HEAD."""
import argparse
import hashlib
import json
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

TRACE_DIR = Path(".agent_trace")
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def git(*args):
    return subprocess.check_output(["git", *args], text=True)


def added_ranges(revision):
    parents = git("rev-list", "--parents", "-n", "1", revision).split()
    base = parents[1] if len(parents) > 1 else git("hash-object", "-t", "tree", "/dev/null").strip()
    diff = git("diff", "-U0", "--no-color", base, revision, "--", ".", ":(exclude).agent_trace")
    ranges, path = {}, None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = None if line == "+++ /dev/null" else line[6:]
        if not path or not (match := HUNK_RE.match(line)):
            continue
        start, count = int(match.group(1)), int(match.group(2) or 1)
        if count:
            ranges.setdefault(path, []).append((start, start + count - 1))
    return ranges


def content_hash(revision, path, start, end):
    lines = git("show", f"{revision}:{path}").splitlines()[start - 1:end]
    return "sha256:" + hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]


def confidence(value):
    value = float(value)
    if not 0 <= value <= 1:
        raise argparse.ArgumentTypeError("debe estar entre 0 y 1")
    return value


def related_resources(values):
    resources = []
    for value in values:
        kind, separator, url = value.partition("=")
        if not separator or not kind or not url:
            raise argparse.ArgumentTypeError("usa TIPO=URL")
        resources.append({"type": kind, "url": url})
    return resources


def build_record(args):
    revision = git("rev-parse", "HEAD").strip()
    contributor = {"type": args.type}
    if args.model:
        contributor["model_id"] = args.model
    files = []
    for path, ranges in added_ranges(revision).items():
        conv = {"contributor": contributor, "ranges": [
            {"start_line": start, "end_line": end,
             "content_hash": content_hash(revision, path, start, end)}
            for start, end in ranges
        ]}
        if args.conversation:
            conv["url"] = args.conversation
        if args.related:
            conv["related"] = related_resources(args.related)
        if args.confidence is not None:
            conv["metadata"] = {"confidence": args.confidence}
            if args.confidence_reason:
                conv["metadata"]["confidence_reason"] = args.confidence_reason
        files.append({"path": path, "conversations": [conv]})
    record = {"version": "0.1", "id": str(uuid.uuid4()),
              "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
              "vcs": {"type": "git", "revision": revision}, "files": files}
    if args.tool:
        record["tool"] = {"name": args.tool}
        if args.tool_version:
            record["tool"]["version"] = args.tool_version
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=["human", "ai", "mixed", "unknown"], required=True)
    parser.add_argument("--model", help="provider/model-name, p. ej. anthropic/claude-opus-5-5")
    parser.add_argument("--tool", help="herramienta que generó el código")
    parser.add_argument("--tool-version", help="versión de la herramienta")
    parser.add_argument("--conversation", help="URL de la conversación")
    parser.add_argument("--related", action="append", default=[], metavar="TIPO=URL",
                        help="recurso relacionado; se puede repetir")
    parser.add_argument("--confidence", type=confidence, help="certeza de atribución, de 0 a 1")
    parser.add_argument("--confidence-reason", help="motivo de una confianza menor que 1")
    record = build_record(parser.parse_args())
    out = TRACE_DIR / "traces" / f"{record['id']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(f"Traza escrita en {out} ({sum(len(f['conversations'][0]['ranges']) for f in record['files'])} rangos)")


if __name__ == "__main__":
    main()
