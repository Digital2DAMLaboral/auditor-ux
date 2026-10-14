"""Carga y validación del catálogo de reglas, respuestas manuales y SUS."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import replace
from importlib import resources
from pathlib import Path
from typing import Any, Optional

import yaml

from .config import Config, ConfigError, load_yaml_file
from .models import (CUMPLE, DIMENSIONS, MANUAL_VALUES, NO_APLICA, NO_CUMPLE, PARCIAL, RULE_KINDS,
                     RULE_VIEWPORTS, SEVERITY_WEIGHTS, Rule)
from .security import SecurityError, clean_text, read_text_limited

_RULE_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,40}$")
_REQUIRED = ("id", "dimension", "titulo", "severidad", "tipo", "norma", "hacer", "evitar")
_ALLOWED = set(_REQUIRED) | {"viewports", "kb", "axe", "pregunta"}


def _rule_from_dict(data: Any, origin: str) -> Rule:
    if not isinstance(data, dict):
        raise ConfigError(f"{origin}: cada regla debe ser un objeto.")
    unknown = set(map(str, data)) - _ALLOWED
    if unknown:
        raise ConfigError(f"{origin}: claves desconocidas {sorted(unknown)}.")
    missing = [k for k in _REQUIRED if not data.get(k)]
    if missing:
        raise ConfigError(f"{origin}: faltan campos {missing}.")
    rule_id = data["id"]
    if not isinstance(rule_id, str) or not _RULE_ID_RE.match(rule_id):
        raise ConfigError(f"{origin}: id no válido «{clean_text(rule_id, 40)}».")
    if data["dimension"] not in DIMENSIONS:
        raise ConfigError(f"{rule_id}: dimensión desconocida.")
    if data["severidad"] not in SEVERITY_WEIGHTS:
        raise ConfigError(f"{rule_id}: severidad no válida.")
    if data["tipo"] not in RULE_KINDS:
        raise ConfigError(f"{rule_id}: tipo no válido.")
    viewports = data.get("viewports", "todas")
    if viewports not in RULE_VIEWPORTS:
        raise ConfigError(f"{rule_id}: viewports no válido.")
    axe = data.get("axe") or []
    if not isinstance(axe, list) or not all(isinstance(a, str) and re.match(r"^[a-z0-9-]+$", a) for a in axe):
        raise ConfigError(f"{rule_id}: «axe» debe ser una lista de identificadores de axe-core.")
    if data["tipo"] == "manual" and not data.get("pregunta"):
        raise ConfigError(f"{rule_id}: las reglas manuales necesitan «pregunta».")
    for key in ("titulo", "norma", "hacer", "evitar", "pregunta", "kb"):
        if key in data and data[key] is not None and not isinstance(data[key], str):
            raise ConfigError(f"{rule_id}: «{key}» debe ser texto.")
    return Rule(
        id=rule_id, dimension=data["dimension"], title=clean_text(data["titulo"], 120),
        severity=data["severidad"], kind=data["tipo"], standard=clean_text(data["norma"], 160),
        fix_do=clean_text(data["hacer"], 400), fix_avoid=clean_text(data["evitar"], 400),
        viewports=viewports, kb_issue=clean_text(data["kb"], 80) if data.get("kb") else None,
        axe_rules=tuple(axe), question=clean_text(data["pregunta"], 300) if data.get("pregunta") else None,
    )


def _parse_catalog(data: Any, origin: str) -> tuple[str, list[Rule]]:
    if not isinstance(data, dict) or not isinstance(data.get("reglas"), list):
        raise ConfigError(f"{origin}: debe contener una lista «reglas».")
    version = clean_text(data.get("version", "sin versión"), 20)
    rules = [_rule_from_dict(item, f"{origin} · regla {i + 1}") for i, item in enumerate(data["reglas"])]
    return version, rules


def builtin_rules() -> tuple[str, list[Rule]]:
    text = resources.files("uxaudit").joinpath("data/rules.yaml").read_text(encoding="utf-8")
    return _parse_catalog(yaml.safe_load(text), "rules.yaml")


def load_rules(cfg: Config) -> tuple[str, list[Rule]]:
    """Reglas activas para esta configuración (incorporadas + extra, con ajustes)."""
    version, rules = builtin_rules()
    if cfg.extra_rules_file:
        _, extra = _parse_catalog(load_yaml_file(cfg.extra_rules_file, "fichero de reglas extra"),
                                  cfg.extra_rules_file.name)
        for rule in extra:
            if rule.kind != "manual":
                raise ConfigError(f"{rule.id}: las reglas extra solo pueden ser de tipo manual "
                                  "(las automáticas requieren un analizador).")
        rules += extra
        version += "+extra"
    ids = [r.id for r in rules]
    duplicated = {i for i in ids if ids.count(i) > 1}
    if duplicated:
        raise ConfigError(f"Reglas duplicadas: {sorted(duplicated)}.")
    unknown = (set(cfg.disabled_rules) | set(cfg.severity_overrides)) - set(ids)
    if unknown:
        raise ConfigError(f"La configuración menciona reglas que no existen: {sorted(unknown)}.")
    active = []
    for rule in rules:
        if rule.id in cfg.disabled_rules:
            continue
        if rule.id in cfg.severity_overrides:
            rule = replace(rule, severity=cfg.severity_overrides[rule.id])
        active.append(rule)
    return version, active


# ───────────────────────── respuestas manuales ─────────────────────────

_ANSWER_ALIASES = {
    "cumple": CUMPLE, "si": CUMPLE, "sí": CUMPLE,
    "parcial": PARCIAL, "parcialmente": PARCIAL,
    "no_cumple": NO_CUMPLE, "no cumple": NO_CUMPLE, "no": NO_CUMPLE,
    "no_aplica": NO_APLICA, "no aplica": NO_APLICA, "n/a": NO_APLICA,
}


def normalize_answer(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return CUMPLE if value else NO_CUMPLE
    if not isinstance(value, str):
        raise ConfigError("Cada respuesta debe ser cumple, parcial, no_cumple o no_aplica.")
    key = value.strip().lower()
    if key not in _ANSWER_ALIASES:
        raise ConfigError(f"Respuesta no válida «{clean_text(value, 30)}»: usa cumple, parcial, no_cumple o no_aplica.")
    return _ANSWER_ALIASES[key]


def load_answers(path: str | Path, rules: list[Rule]) -> dict[str, tuple[str, str]]:
    """Lee respuestas.yaml → {regla: (estado, comentario)}."""
    data = load_yaml_file(path, "fichero de respuestas")
    if data is None:
        return {}
    if isinstance(data, dict) and "respuestas" in data:
        data = data["respuestas"]
    if not isinstance(data, dict):
        raise ConfigError("El fichero de respuestas debe ser un objeto {REGLA: cumple, ...}.")
    manual_ids = {r.id for r in rules if r.kind == "manual"}
    answers: dict[str, tuple[str, str]] = {}
    for rule_id, raw in data.items():
        if rule_id not in manual_ids:
            raise ConfigError(f"«{clean_text(rule_id, 40)}» no es una regla manual activa.")
        comment = ""
        if isinstance(raw, dict):
            if set(raw) - {"resultado", "comentario"}:
                raise ConfigError(f"{rule_id}: usa solo «resultado» y «comentario».")
            comment = clean_text(raw.get("comentario", ""), 400)
            raw = raw.get("resultado")
        status = normalize_answer(raw)
        if status is not None:
            answers[rule_id] = (status, comment)
    return answers


def answers_to_yaml(answers: dict[str, tuple[str, str]], rules: list[Rule], header: str) -> str:
    lines = [header.rstrip(), "respuestas:"]
    for rule in rules:
        if rule.kind != "manual":
            continue
        status, comment = answers.get(rule.id, ("", ""))
        lines.append(f"  # {rule.title} — {rule.question}")
        lines.append(f"  {rule.id}:")
        lines.append(f"    resultado: {status}")
        lines.append(f"    comentario: {yaml.safe_dump(comment, allow_unicode=True).strip().removesuffix('...').strip()}")
    return "\n".join(lines) + "\n"


# ───────────────────────── SUS ─────────────────────────

def sus_from_csv(path: str | Path) -> tuple[float, int]:
    """Calcula la puntuación SUS media de un CSV con 10 respuestas (1–5) por participante.

    Admite una fila de cabecera opcional y una primera columna de identificador.
    """
    try:
        text = read_text_limited(path, 1024 * 1024, "CSV de SUS")
    except SecurityError as exc:
        raise ConfigError(str(exc)) from exc
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    scores = []
    for line_no, row in enumerate(csv.reader(io.StringIO(text), dialect), start=1):
        cells = [c.strip() for c in row if c.strip() != ""]
        if not cells:
            continue
        numeric = [c for c in cells if re.fullmatch(r"[1-5]", c)]
        if len(cells) in (10, 11) and len(numeric) == 10:
            values = [int(c) for c in numeric]
        elif line_no == 1:
            continue  # cabecera
        else:
            raise ConfigError(f"CSV de SUS, línea {line_no}: se esperaban 10 respuestas entre 1 y 5.")
        odd = sum(values[i] - 1 for i in range(0, 10, 2))
        even = sum(5 - values[i] for i in range(1, 10, 2))
        scores.append((odd + even) * 2.5)
        if len(scores) > 10_000:
            raise ConfigError("CSV de SUS demasiado grande.")
    if not scores:
        raise ConfigError("El CSV de SUS no contiene respuestas válidas.")
    return round(sum(scores) / len(scores), 2), len(scores)


def manual_value(status: str) -> Optional[float]:
    return MANUAL_VALUES.get(status)
