"""Motor de puntuación del Índice de Experiencia de Usuario (IUX, 0–10).

Fórmula (apartado 03 del trabajo):
  Nota(Dk) = 10 · Σ(wᵢ · resultadoᵢ) / Σwᵢ          (solo reglas aplicables)
  IUX      = Σ(Pesoₖ · Nota(Dk)) / ΣPesoₖ            (solo dimensiones con datos)

Techos (la nota final es el mínimo entre el IUX y cada techo aplicable):
  · Estándar: fallo CRÍTICO en D1                       → máx. 4,9
  · Estricto (por defecto), además:
      - fallo CRÍTICO en cualquier dimensión            → máx. 4,9
      - fallo de severidad ALTA en accesibilidad (D1)   → máx. 6,9
      - «Excelente» (≥ 9) solo con cobertura ≥ 90 %, evaluación experta completa
        y ninguna regla alta o crítica incumplida, ni siquiera parcialmente → si no, máx. 8,9
"""
from __future__ import annotations

from statistics import mean
from typing import Optional

from .models import (A11Y_HIGH_CAP, BLOCK_CAP, CUMPLE, DIMENSIONS, EXCELLENCE_CAP, EXCELLENCE_MIN_COVERAGE,
                     NO_APLICA, NO_CUMPLE, PARCIAL, PARTIAL_RATIO, PARTIAL_RATIO_STRICT, SIN_EVALUAR,
                     DimensionScore, Finding, PageScore, Rule, level_for)

# Umbrales de las métricas: (valor «10 puntos», valor «5 puntos», valor «0 puntos»)
METRIC_THRESHOLDS = {
    "PERF-LCP": (2500.0, 4000.0, 6000.0),        # ms
    "PERF-CLS": (0.10, 0.25, 0.40),
    "PERF-TBT": (200.0, 600.0, 1000.0),          # ms (proxy de INP en laboratorio)
    "PERF-PESO": (1_600_000.0, 3_000_000.0, 5_000_000.0),  # bytes
    "ETI-CARBONO": (0.079, 0.209, 0.359),        # g CO2e por visita (A · C · E de la escala SWD)
}
# Modo estricto: el «bueno» de Google pasa a ser la mitad de la nota; 0 puntos en «mejorable».
METRIC_THRESHOLDS_STRICT = {
    "PERF-LCP": (1800.0, 2500.0, 4000.0),
    "PERF-CLS": (0.05, 0.10, 0.25),
    "PERF-TBT": (100.0, 200.0, 600.0),
    "PERF-PESO": (1_000_000.0, 1_600_000.0, 3_000_000.0),
    "ETI-CARBONO": (0.040, 0.145, 0.278),        # A+ · B · D
}
# Legibilidad (más alto = mejor): (10 puntos, 5 puntos, 0 puntos)
READABILITY_THRESHOLDS = {"es": (70.0, 60.0, 50.0), "en": (60.0, 50.0, 40.0)}
READABILITY_THRESHOLDS_STRICT = {"es": (75.0, 65.0, 55.0), "en": (65.0, 55.0, 45.0)}


def thresholds(rule_id: str, strict: bool) -> tuple[float, float, float]:
    return (METRIC_THRESHOLDS_STRICT if strict else METRIC_THRESHOLDS)[rule_id]


def ratio_value(passed: int, total: int, strict: bool = False) -> Optional[float]:
    """Regla de conteo → 1 (todos bien), 0,5 (≥ 90 % · estricto ≥ 95 %) o 0."""
    if total <= 0:
        return None
    if passed >= total:
        return 1.0
    limit = PARTIAL_RATIO_STRICT if strict else PARTIAL_RATIO
    return 0.5 if passed / total >= limit else 0.0


def metric_value(value: float, good: float, mid: float, poor: float) -> float:
    """Interpolación lineal por tramos: ≤good → 1; mid → 0,5; ≥poor → 0."""
    if value <= good:
        return 1.0
    if value >= poor:
        return 0.0
    if value <= mid:
        return 1.0 - 0.5 * (value - good) / (mid - good)
    return 0.5 - 0.5 * (value - mid) / (poor - mid)


def metric_value_high(value: float, good: float, mid: float, poor: float) -> float:
    """Igual que metric_value pero para métricas donde más alto es mejor."""
    return metric_value(-value, -good, -mid, -poor)


def status_for(value: Optional[float]) -> str:
    if value is None:
        return NO_APLICA
    if value >= 0.999:
        return CUMPLE
    if value <= 0.001:
        return NO_CUMPLE
    return PARCIAL


def finalize_count_finding(f: Finding, strict: bool = False) -> Finding:
    f.value = ratio_value(f.passed, f.total, strict)
    f.status = status_for(f.value)
    return f


def score_page(rules: list[Rule], findings: dict[str, Finding], weights: dict[str, float],
               strict: bool = False) -> PageScore:
    dims: dict[str, DimensionScore] = {}
    for key, name in DIMENSIONS.items():
        dim_rules = [r for r in rules if r.dimension == key]
        num = den = 0.0
        evaluated = 0
        for rule in dim_rules:
            f = findings.get(rule.id)
            if f is None or f.value is None or f.status in (NO_APLICA, SIN_EVALUAR):
                continue
            num += rule.weight * f.value
            den += rule.weight
            evaluated += rule.weight
        possible = sum(r.weight for r in dim_rules
                       if not (findings.get(r.id) and findings[r.id].status == NO_APLICA))
        score = round(10 * num / den, 2) if den > 0 else None
        dims[key] = DimensionScore(key, name, float(weights.get(key, 0)), score, evaluated, possible)

    usable = [d for d in dims.values() if d.score is not None and d.weight > 0]
    total_w = sum(d.weight for d in usable)
    iux_raw = round(sum(d.weight * d.score for d in usable) / total_w, 2) if total_w > 0 else None

    def failing(rule: Rule, statuses=(NO_CUMPLE,)) -> bool:
        f = findings.get(rule.id)
        return f is not None and f.status in statuses

    active_dims = {k for k, d in dims.items() if d.weight > 0}
    critical = sorted(r.id for r in rules if r.severity == "critica" and failing(r)
                      and (r.dimension == "D1" or (strict and r.dimension in active_dims)))
    high_a11y = sorted(r.id for r in rules if strict and r.dimension == "D1" and r.severity == "alta" and failing(r))

    possible_total = sum(d.possible_weight for d in dims.values() if d.weight > 0)
    evaluated_total = sum(d.evaluated_weight for d in dims.values() if d.weight > 0)
    coverage = round(100 * evaluated_total / possible_total, 1) if possible_total else 0.0
    pending = sorted(r.id for r in rules if r.kind == "manual" and dims[r.dimension].weight > 0
                     and (findings.get(r.id) is None or findings[r.id].status == SIN_EVALUAR))

    caps: list[tuple[float, str]] = []
    if critical:
        caps.append((BLOCK_CAP, f"Fallo crítico ({', '.join(critical)}): nota máxima {BLOCK_CAP:.1f}".replace(".", ",")))
    if high_a11y:
        caps.append((A11Y_HIGH_CAP, f"Incumplimiento de accesibilidad de severidad alta ({', '.join(high_a11y)}): "
                                    f"nota máxima {A11Y_HIGH_CAP:.1f}".replace(".", ",")))
    if strict:
        reasons = []
        serious = sorted(r.id for r in rules if r.severity in ("alta", "critica") and r.dimension in active_dims
                         and failing(r, (NO_CUMPLE, PARCIAL)))
        if serious:
            n = len(serious)
            reasons.append(f"{n} regla{'s' if n != 1 else ''} alta{'s' if n != 1 else ''} o crítica{'s' if n != 1 else ''} sin cumplir del todo")
        if pending:
            n = len(pending)
            reasons.append(f"{n} regla{'s' if n != 1 else ''} de evaluación experta sin responder")
        if coverage < EXCELLENCE_MIN_COVERAGE:
            reasons.append(f"cobertura {coverage:.0f} % (< {EXCELLENCE_MIN_COVERAGE:.0f} %)")
        if reasons:
            caps.append((EXCELLENCE_CAP, "«Excelente» exige una auditoría completa y sin fallos graves: "
                                         + "; ".join(reasons) + ". Nota máxima " + f"{EXCELLENCE_CAP:.1f}".replace(".", ",")))

    iux = iux_raw
    # Se informan todos los techos (aunque la nota ya esté por debajo): explican qué impide subir.
    applied = [reason for _, reason in sorted(caps)]
    if iux is not None and caps:
        iux = min(iux, min(c for c, _ in caps))
    return PageScore(dims, iux_raw, iux, level_for(iux), critical, coverage, pending, applied, strict)


def site_score(pages: list[PageScore]) -> tuple[Optional[float], Optional[float], str]:
    """IUX del sitio = media de las páginas; se devuelve también la peor página."""
    values = [p.iux for p in pages if p.iux is not None]
    if not values:
        return None, None, level_for(None)
    avg = round(mean(values), 2)
    return avg, min(values), level_for(avg)
