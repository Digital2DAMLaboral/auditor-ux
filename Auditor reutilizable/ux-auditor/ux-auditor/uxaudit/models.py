"""Modelos de datos del UX-Auditor (reglas, hallazgos y puntuaciones)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

DIMENSIONS: dict[str, str] = {
    "D1": "Accesibilidad",
    "D2": "Usabilidad e interacción",
    "D3": "Rendimiento percibido",
    "D4": "Diseño visual y consistencia",
    "D5": "Formularios y feedback",
    "D6": "Navegación y arquitectura de la información",
    "D7": "Satisfacción percibida",
    "D8": "Ética, privacidad y sostenibilidad",
}

DEFAULT_WEIGHTS: dict[str, float] = {
    "D1": 25, "D2": 15, "D3": 15, "D4": 10, "D5": 10, "D6": 10, "D7": 5, "D8": 10,
}
# Pesos del modo estándar original (7 dimensiones, apartado 03 v1).
LEGACY_WEIGHTS: dict[str, float] = {
    "D1": 25, "D2": 20, "D3": 15, "D4": 15, "D5": 10, "D6": 10, "D7": 5, "D8": 0,
}

SEVERITY_WEIGHTS: dict[str, int] = {"critica": 4, "alta": 3, "media": 2, "baja": 1}
SEVERITY_LABELS: dict[str, str] = {"critica": "Crítica", "alta": "Alta", "media": "Media", "baja": "Baja"}

RULE_KINDS = ("auto", "metrica", "manual")
RULE_VIEWPORTS = ("todas", "movil", "escritorio")

# Estado de cada regla tras la auditoría.
CUMPLE, PARCIAL, NO_CUMPLE, NO_APLICA, SIN_EVALUAR = (
    "cumple", "parcial", "no_cumple", "no_aplica", "sin_evaluar")
STATUS_LABELS = {
    CUMPLE: "Cumple", PARCIAL: "Cumple parcialmente", NO_CUMPLE: "No cumple",
    NO_APLICA: "No aplica", SIN_EVALUAR: "Sin evaluar",
}
MANUAL_VALUES = {CUMPLE: 1.0, PARCIAL: 0.5, NO_CUMPLE: 0.0, NO_APLICA: None}

# «Parcial» si cumple al menos este porcentaje de los elementos (estándar 90 %, estricto 95 %).
PARTIAL_RATIO = 0.9
PARTIAL_RATIO_STRICT = 0.95
# Techos de la nota.
BLOCK_CAP = 4.9          # fallo crítico (estándar: solo en D1; estricto: en cualquier dimensión)
A11Y_HIGH_CAP = 6.9      # estricto: fallo de severidad alta en accesibilidad
EXCELLENCE_CAP = 8.9     # estricto: «Excelente» exige evaluación completa y ningún fallo alto
EXCELLENCE_MIN_COVERAGE = 90.0

LEVELS = (  # (nota mínima, nombre)
    (9.0, "Excelente"),
    (7.0, "Buena"),
    (5.0, "Aceptable"),
    (3.0, "Deficiente"),
    (0.0, "Crítica"),
)


def level_for(score: Optional[float]) -> str:
    if score is None:
        return "Sin datos"
    for minimum, name in LEVELS:
        if score >= minimum - 1e-9:
            return name
    return "Crítica"


@dataclass(frozen=True)
class Rule:
    id: str
    dimension: str
    title: str
    severity: str
    kind: str
    standard: str
    fix_do: str
    fix_avoid: str
    viewports: str = "todas"
    kb_issue: Optional[str] = None
    axe_rules: tuple[str, ...] = ()
    question: Optional[str] = None

    @property
    def weight(self) -> int:
        return SEVERITY_WEIGHTS[self.severity]


@dataclass
class Evidence:
    viewport: str
    selector: str
    detail: str


@dataclass
class Finding:
    """Resultado de una regla en una página."""
    rule_id: str
    status: str = SIN_EVALUAR
    value: Optional[float] = None       # 0..1 (None = excluida del cálculo)
    passed: int = 0
    total: int = 0
    measured: Optional[str] = None      # valor medido legible (p. ej. «LCP 2,1 s»)
    evidence: list[Evidence] = field(default_factory=list)
    review: int = 0                     # elementos que axe marca para revisión manual
    note: Optional[str] = None


@dataclass
class DimensionScore:
    key: str
    name: str
    weight: float
    score: Optional[float]
    evaluated_weight: int       # Σ pesos de reglas evaluadas
    possible_weight: int        # Σ pesos de todas las reglas activas de la dimensión


@dataclass
class PageScore:
    dimensions: dict[str, DimensionScore]
    iux_raw: Optional[float]
    iux: Optional[float]
    level: str
    blocked_by: list[str]
    coverage: float             # % del peso total de reglas que se ha podido evaluar
    manual_pending: list[str]   # reglas manuales sin respuesta
    caps: list[str] = field(default_factory=list)   # techos aplicados (explicación legible)
    strict: bool = True
