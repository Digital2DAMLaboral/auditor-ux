"""Legibilidad del texto (lenguaje claro · accesibilidad cognitiva).

* Español: índice de Fernández-Huerta (1959), adaptación de Flesch:
      L = 206,84 − 0,60·P − 1,02·F
  P = sílabas por cada 100 palabras · F = frases por cada 100 palabras.
* Inglés: Flesch Reading Ease (1948):
      RE = 206,835 − 1,015·(palabras/frase) − 84,6·(sílabas/palabra)

Escala (ambos): 90–100 muy fácil · 80–90 fácil · 70–80 bastante fácil · 60–70 normal ·
50–60 bastante difícil · 30–50 difícil · 0–30 muy difícil.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

_WORD = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*", re.UNICODE)
_SENTENCE_END = re.compile(r"[.!?…;:]+(?=\s|$)|\n{2,}")

_STRONG = set("aeoáéó")
_WEAK = set("iuü")
_WEAK_ACCENT = set("íú")
_VOWELS = _STRONG | _WEAK | _WEAK_ACCENT | {"y"}

_ES_STOP = {"de", "la", "que", "el", "en", "y", "los", "se", "del", "las", "un", "por", "con", "no", "una", "su",
            "para", "es", "al", "lo", "como", "más", "pero", "sus", "le", "ya", "o", "este", "sí", "porque", "esta"}
_EN_STOP = {"the", "of", "and", "to", "in", "is", "you", "that", "it", "he", "was", "for", "on", "are", "as",
            "with", "his", "they", "at", "be", "this", "have", "from", "or", "one", "had", "by", "but", "not"}


def syllables_es(word: str) -> int:
    """Cuenta sílabas en español por núcleos vocálicos (diptongos, triptongos e hiatos)."""
    w = word.lower()
    w = w.replace("qu", "q").replace("gue", "ge").replace("gui", "gi")  # «u» muda
    count = 0
    prev = ""   # tipo de la vocal anterior: "S" fuerte, "W" débil, "A" débil acentuada
    for i, ch in enumerate(w):
        if ch == "y" and (i == len(w) - 1 or w[i + 1] not in _VOWELS) and i > 0 and w[i - 1] in _VOWELS:
            kind = "W"   # «y» final tras vocal (rey, muy) actúa como vocal débil
        elif ch in _STRONG:
            kind = "S"
        elif ch in _WEAK:
            kind = "W"
        elif ch in _WEAK_ACCENT:
            kind = "A"
        else:
            prev = ""
            continue
        if not prev:
            count += 1
        elif prev == "S" and kind == "S":
            count += 1          # hiato: dos vocales fuertes
        elif "A" in (prev, kind):
            count += 1          # hiato por tilde en la débil (país, río)
        prev = kind
    return max(1, count)


def syllables_en(word: str) -> int:
    w = word.lower().strip("'’")
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    groups = re.findall(r"[aeiouy]{1,2}", w)
    return max(1, len(groups))


def detect_language(text: str, declared: str) -> Optional[str]:
    declared = (declared or "").lower()
    if declared.startswith("es"):
        return "es"
    if declared.startswith("en"):
        return "en"
    words = [w.lower() for w in _WORD.findall(text[:5000])]
    if len(words) < 30:
        return None
    es = sum(w in _ES_STOP for w in words)
    en = sum(w in _EN_STOP for w in words)
    if max(es, en) / len(words) < 0.08:
        return None
    return "es" if es >= en else "en"


@dataclass
class Readability:
    lang: str
    score: float
    words: int
    sentences: int
    words_per_sentence: float
    long_sentences_pct: float
    index_name: str

    @property
    def label(self) -> str:
        s = self.score
        for limit, name in ((90, "muy fácil"), (80, "fácil"), (70, "bastante fácil"), (60, "normal"),
                            (50, "bastante difícil"), (30, "difícil")):
            if s >= limit:
                return name
        return "muy difícil"


def analyze(text: str, declared_lang: str = "", min_words: int = 100) -> Optional[Readability]:
    text = unicodedata.normalize("NFC", text or "")[:30000]
    lang = detect_language(text, declared_lang)
    if lang is None:
        return None
    sentences = [s for s in _SENTENCE_END.split(text) if _WORD.search(s)]
    words = _WORD.findall(text)
    if len(words) < min_words or not sentences:
        return None
    count = syllables_es if lang == "es" else syllables_en
    syll = sum(count(w) for w in words)
    n_w, n_s = len(words), len(sentences)
    long_pct = 100 * sum(1 for s in sentences if len(_WORD.findall(s)) > 30) / n_s
    if lang == "es":
        p = 100 * syll / n_w
        f = 100 * n_s / n_w
        score = 206.84 - 0.60 * p - 1.02 * f
        name = "Fernández-Huerta"
    else:
        score = 206.835 - 1.015 * (n_w / n_s) - 84.6 * (syll / n_w)
        name = "Flesch Reading Ease"
    return Readability(lang, round(max(0.0, min(100.0, score)), 1), n_w, n_s, round(n_w / n_s, 1),
                       round(long_pct, 1), name)
