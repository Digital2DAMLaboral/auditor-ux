"""Generadores de informes (JSON, Markdown y HTML)."""
from __future__ import annotations

from typing import Any, Optional

from ..kb import by_issue
from ..models import DIMENSIONS, SEVERITY_LABELS, STATUS_LABELS, Rule

STATUS_ORDER = {"no_cumple": 0, "parcial": 1, "sin_evaluar": 2, "cumple": 3, "no_aplica": 4}
SEV_ORDER = {"critica": 0, "alta": 1, "media": 2, "baja": 3}


def kb_entry(rule: Rule) -> Optional[dict[str, str]]:
    g = by_issue(rule.kb_issue)
    if g is None:
        return None
    return {"directriz": g.issue, "categoria": g.category, "hacer": g.do, "evitar": g.dont,
            "codigo_correcto": g.code_good, "codigo_incorrecto": g.code_bad, "severidad": g.severity}


def finding_dict(rule: Rule, f) -> dict[str, Any]:
    return {
        "regla": rule.id, "dimension": rule.dimension, "titulo": rule.title, "tipo": rule.kind,
        "severidad": rule.severity, "peso": rule.weight, "estado": f.status,
        "valor": None if f.value is None else round(f.value, 4),
        "superados": f.passed, "total": f.total, "medido": f.measured, "nota": f.note,
        "revisar_manualmente": f.review or None, "norma": rule.standard,
        "evidencias": [{"viewport": e.viewport, "selector": e.selector, "detalle": e.detail} for e in f.evidence],
        "correccion": {"hacer": rule.fix_do, "evitar": rule.fix_avoid, "ui_ux_pro_max": kb_entry(rule)},
    }


def sorted_findings(rules: list[Rule], findings: dict) -> list[tuple[Rule, Any]]:
    pairs = [(r, findings[r.id]) for r in rules if r.id in findings]
    return sorted(pairs, key=lambda p: (STATUS_ORDER.get(p[1].status, 9), SEV_ORDER[p[0].severity], p[0].dimension, p[0].id))


def to_data(result, rules: list[Rule]) -> dict[str, Any]:
    """Estructura serializable (base del JSON y de los demás informes)."""
    pages = []
    for p in result.pages:
        page: dict[str, Any] = {
            "objetivo": p.target, "url_final": p.final_url, "titulo": p.title, "estado_http": p.status,
            "viewports": p.viewports, "duracion_s": p.duration_s, "error": p.error,
            "avisos": p.warnings, "peticiones_bloqueadas": p.blocked_requests, "metricas": p.metrics,
            "axe_core": p.axe_version or None,
        }
        if p.score:
            s = p.score
            page.update({
                "iux": s.iux, "iux_sin_bloqueo": s.iux_raw, "nivel": s.level, "bloqueo": s.blocked_by,
                "techos": s.caps, "modo": "estricto" if s.strict else "estándar",
                "cobertura_pct": s.coverage, "manuales_pendientes": s.manual_pending,
                "dimensiones": {k: {"nombre": d.name, "peso": d.weight, "nota": d.score,
                                    "peso_evaluado": d.evaluated_weight, "peso_posible": d.possible_weight}
                                for k, d in s.dimensions.items()},
                "hallazgos": [finding_dict(r, f) for r, f in sorted_findings(rules, p.findings)],
            })
        pages.append(page)
    return {
        "herramienta": {"nombre": "UX-Auditor", "version": result.tool_version, "reglas": result.rules_version,
                        "base_conocimiento": "UI UX Pro Max · ux-guidelines.csv (MIT)"},
        "proyecto": result.project, "fecha": result.date, "umbral": result.threshold,
        "sitio": {"iux": result.site_iux, "iux_minimo": result.site_min, "nivel": result.site_level,
                  "paginas": len(result.pages),
                  "paginas_con_error": sum(1 for p in result.pages if p.error),
                  "supera_umbral": None if result.threshold is None or result.site_iux is None
                  else result.site_iux >= result.threshold},
        "sus": {"puntuacion": result.sus[0], "participantes": result.sus[1]} if result.sus else None,
        "dimensiones": DIMENSIONS, "severidades": SEVERITY_LABELS, "estados": STATUS_LABELS,
        "paginas": pages,
    }
