"""Histórico de puntuaciones (historial.jsonl en la carpeta de informes)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .security import append_line, clean_text, clamp_number, read_text_limited

HISTORY_FILE = "historial.jsonl"


def record(out_dir: Path, result, report_name: str) -> None:
    entry = {
        "fecha": result.date, "proyecto": result.project, "iux": result.site_iux, "nivel": result.site_level,
        "paginas": [{"objetivo": p.target, "iux": p.score.iux if p.score else None} for p in result.pages],
        "informe": report_name, "version": result.tool_version,
    }
    append_line(out_dir, HISTORY_FILE, json.dumps(entry, ensure_ascii=False))


def load(out_dir: Path, limit: int = 30) -> list[dict[str, Any]]:
    path = out_dir / HISTORY_FILE
    if not path.is_file():
        return []
    entries = []
    for line in read_text_limited(path, 5_000_000, "histórico").splitlines()[-limit:]:
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        entries.append({"fecha": clean_text(raw.get("fecha"), 40), "proyecto": clean_text(raw.get("proyecto"), 80),
                        "iux": clamp_number(raw.get("iux"), 0, 10), "nivel": clean_text(raw.get("nivel"), 20),
                        "informe": clean_text(raw.get("informe"), 120)})
    return entries
