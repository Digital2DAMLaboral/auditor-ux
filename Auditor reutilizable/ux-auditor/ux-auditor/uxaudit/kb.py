"""Base de conocimiento: directrices UX de UI UX Pro Max (ux-guidelines.csv, licencia MIT).

Se lee el CSV directamente con el módulo csv (no se ejecuta código de terceros)
y se busca con un BM25 sencillo.
"""
from __future__ import annotations

import csv
import io
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Optional

from .security import clean_text

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with", "is", "be", "use", "not", "no"}


@dataclass(frozen=True)
class Guideline:
    number: str
    category: str
    issue: str
    platform: str
    description: str
    do: str
    dont: str
    code_good: str
    code_bad: str
    severity: str


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


@lru_cache(maxsize=1)
def guidelines() -> tuple[Guideline, ...]:
    raw = resources.files("uxaudit").joinpath("data/ux-guidelines.csv").read_text(encoding="utf-8")
    rows = []
    for row in csv.DictReader(io.StringIO(raw)):
        rows.append(Guideline(
            number=clean_text(row.get("No"), 10), category=clean_text(row.get("Category"), 60),
            issue=clean_text(row.get("Issue"), 80), platform=clean_text(row.get("Platform"), 30),
            description=clean_text(row.get("Description"), 400), do=clean_text(row.get("Do"), 400),
            dont=clean_text(row.get("Don't"), 400), code_good=clean_text(row.get("Code Example Good"), 300),
            code_bad=clean_text(row.get("Code Example Bad"), 300), severity=clean_text(row.get("Severity"), 20),
        ))
    return tuple(rows)


@lru_cache(maxsize=1)
def _index():
    docs = [_tokens(f"{g.category} {g.issue} {g.issue} {g.description} {g.do} {g.dont}") for g in guidelines()]
    df = Counter(t for d in docs for t in set(d))
    avg = sum(map(len, docs)) / max(1, len(docs))
    return docs, df, avg


def by_issue(issue: Optional[str]) -> Optional[Guideline]:
    """Coincidencia exacta (sin distinguir mayúsculas) por nombre de directriz."""
    if not issue:
        return None
    wanted = issue.strip().lower()
    for g in guidelines():
        if g.issue.lower() == wanted:
            return g
    return None


def search(query: str, limit: int = 3) -> list[tuple[float, Guideline]]:
    """Búsqueda BM25 (k1=1.5, b=0.75)."""
    terms = _tokens(clean_text(query, 200))
    if not terms:
        return []
    docs, df, avg = _index()
    n = len(docs)
    results = []
    for doc, g in zip(docs, guidelines()):
        tf = Counter(doc)
        score = 0.0
        for term in terms:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            freq = tf[term]
            score += idf * freq * 2.5 / (freq + 1.5 * (1 - 0.75 + 0.75 * len(doc) / avg))
        if score > 0:
            results.append((round(score, 3), g))
    results.sort(key=lambda item: -item[0])
    return results[: max(1, min(limit, 20))]
