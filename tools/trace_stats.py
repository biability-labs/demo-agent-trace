"""Analíticas básicas sobre las líneas registradas en Agent Trace."""
import json
from collections import Counter
from pathlib import Path

from trace_blame import TRACE_DIR


def range_size(line_range):
    """Devuelve el número de líneas incluidas en un rango de una traza."""
    return line_range["end_line"] - line_range["start_line"] + 1


def analytics(trace_dir=TRACE_DIR):
    """Agrupa las líneas atribuidas históricamente por tipo, modelo y fichero."""
    result = {
        "traces": 0,
        "commits": set(),
        "files": set(),
        "lines": 0,
        "by_contributor": Counter(),
        "by_model": Counter(),
        "by_file": Counter(),
    }
    for trace_path in sorted(Path(trace_dir).glob("*.json")):
        record = json.loads(trace_path.read_text())
        result["traces"] += 1
        revision = record.get("vcs", {}).get("revision")
        if revision:
            result["commits"].add(revision)
        for file in record.get("files", []):
            path = file["path"]
            result["files"].add(path)
            for conversation in file.get("conversations", []):
                contributor = conversation.get("contributor", {})
                kind = contributor.get("type", "unknown")
                lines = sum(range_size(line_range) for line_range in conversation.get("ranges", []))
                result["lines"] += lines
                result["by_contributor"][kind] += lines
                result["by_file"][path] += lines
                if contributor.get("model_id"):
                    result["by_model"][contributor["model_id"]] += lines
    return result


def print_breakdown(title, values):
    print(f"\n{title}:")
    if not values:
        print("  Sin datos")
        return
    for name, lines in sorted(values.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {name}: {lines} líneas")


def main():
    result = analytics()
    print("Agent Trace: analíticas históricas de líneas añadidas")
    print(f"Trazas: {result['traces']}")
    print(f"Commits con traza: {len(result['commits'])}")
    print(f"Ficheros con traza: {len(result['files'])}")
    print(f"Líneas atribuidas: {result['lines']}")
    print_breakdown("Por contribuidor", result["by_contributor"])
    print_breakdown("Por modelo de IA", result["by_model"])
    print_breakdown("Por fichero", result["by_file"])


if __name__ == "__main__":
    main()
