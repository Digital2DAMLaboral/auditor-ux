"""Carga y validación estricta de la configuración del proyecto (uxaudit.yaml)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Optional

import yaml

from .models import DEFAULT_WEIGHTS, DIMENSIONS, SEVERITY_WEIGHTS
from .security import SecurityError, clean_text, read_text_limited

MAX_CONFIG_BYTES = 256 * 1024


class ConfigError(ValueError):
    """Configuración no válida."""


@dataclass(frozen=True)
class Viewport:
    name: str
    width: int
    height: int
    mobile: bool
    scale: float = 1.0


MOBILE = Viewport("movil", 375, 812, True, 2.0)
DESKTOP = Viewport("escritorio", 1440, 900, False, 1.0)

PROFILES: dict[str, tuple[Viewport, ...]] = {
    "web": (MOBILE, DESKTOP),
    "movil": (MOBILE,),
    "escritorio": (DESKTOP,),
}


@dataclass(frozen=True)
class Config:
    project: str = "Proyecto sin nombre"
    profile: str = "web"
    viewports: tuple[Viewport, ...] = PROFILES["web"]
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    threshold: Optional[float] = None
    disabled_rules: frozenset[str] = frozenset()
    severity_overrides: dict[str, str] = field(default_factory=dict)
    timeout_s: int = 45
    settle_ms: int = 1500
    block_private: bool = False
    redact_urls: bool = True
    performance: bool = True
    throttling: bool = True
    screenshots: bool = True
    keyboard: bool = True
    max_evidence: int = 15
    max_tab_stops: int = 80
    extra_rules_file: Optional[Path] = None
    strict: bool = True


# Claves admitidas en uxaudit.yaml → (nombre interno, validador)
_KEYS = {
    "proyecto", "perfil", "viewports", "pesos", "umbral_ci", "reglas_desactivadas",
    "severidades", "tiempo_maximo_s", "espera_tras_carga_ms", "bloquear_redes_privadas",
    "redactar_urls", "rendimiento", "capturas", "teclado", "max_evidencias",
    "max_tabulaciones", "reglas_extra", "modo",
}
_RENDIMIENTO_KEYS = {"activado", "limitar_red_y_cpu"}
_VIEWPORT_KEYS = {"nombre", "ancho", "alto", "movil", "escala"}
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")
_RULE_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,40}$")


def _bool(value: Any, key: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"«{key}» debe ser true o false.")
    return value


def _number(value: Any, key: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"«{key}» debe ser un número.")
    if not low <= value <= high:
        raise ConfigError(f"«{key}» debe estar entre {low} y {high}.")
    return float(value)


def _viewport(data: Any, index: int) -> Viewport:
    if not isinstance(data, dict):
        raise ConfigError(f"viewports[{index}] debe ser un objeto con nombre, ancho, alto y movil.")
    unknown = set(data) - _VIEWPORT_KEYS
    if unknown:
        raise ConfigError(f"viewports[{index}]: claves desconocidas {sorted(map(str, unknown))}.")
    name = data.get("nombre")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ConfigError(f"viewports[{index}].nombre debe ser un identificador corto (minúsculas, números, - o _).")
    return Viewport(
        name=name,
        width=int(_number(data.get("ancho"), f"viewports[{index}].ancho", 240, 3840)),
        height=int(_number(data.get("alto"), f"viewports[{index}].alto", 240, 2160)),
        mobile=_bool(data.get("movil", False), f"viewports[{index}].movil"),
        scale=_number(data.get("escala", 1), f"viewports[{index}].escala", 1, 3),
    )


def parse_config(data: Any, base_dir: Path) -> Config:
    """Valida un diccionario de configuración (ya cargado de YAML)."""
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError("La configuración debe ser un objeto YAML (clave: valor).")
    unknown = set(map(str, data)) - _KEYS
    if unknown:
        raise ConfigError(f"Claves desconocidas en la configuración: {sorted(unknown)}. Revisa la ortografía.")

    cfg = Config()
    changes: dict[str, Any] = {}

    if "proyecto" in data:
        if not isinstance(data["proyecto"], str):
            raise ConfigError("«proyecto» debe ser un texto.")
        changes["project"] = clean_text(data["proyecto"], 80) or cfg.project

    if "modo" in data:
        if data["modo"] not in ("estricto", "estandar", "estándar"):
            raise ConfigError("«modo» debe ser estricto o estandar.")
        changes["strict"] = data["modo"] == "estricto"

    profile = data.get("perfil", "web")
    if profile not in PROFILES:
        raise ConfigError(f"«perfil» debe ser uno de {sorted(PROFILES)}.")
    changes["profile"] = profile
    changes["viewports"] = PROFILES[profile]

    if "viewports" in data:
        raw = data["viewports"]
        if not isinstance(raw, list) or not 1 <= len(raw) <= 4:
            raise ConfigError("«viewports» debe ser una lista de 1 a 4 elementos.")
        vps = tuple(_viewport(v, i) for i, v in enumerate(raw))
        if len({v.name for v in vps}) != len(vps):
            raise ConfigError("Los nombres de los viewports deben ser únicos.")
        changes["viewports"] = vps

    if "pesos" in data:
        raw = data["pesos"]
        if not isinstance(raw, dict):
            raise ConfigError("«pesos» debe ser un objeto {D1: 25, ...}.")
        weights = dict(DEFAULT_WEIGHTS)
        for key, value in raw.items():
            if key not in DIMENSIONS:
                raise ConfigError(f"Dimensión desconocida en «pesos»: {clean_text(key, 20)}.")
            weights[key] = _number(value, f"pesos.{key}", 0, 100)
        if sum(weights.values()) <= 0:
            raise ConfigError("La suma de los pesos debe ser mayor que 0.")
        changes["weights"] = weights

    if "umbral_ci" in data and data["umbral_ci"] is not None:
        changes["threshold"] = _number(data["umbral_ci"], "umbral_ci", 0, 10)

    if "reglas_desactivadas" in data:
        raw = data["reglas_desactivadas"] or []
        if not isinstance(raw, list) or not all(isinstance(r, str) and _RULE_ID_RE.match(r) for r in raw):
            raise ConfigError("«reglas_desactivadas» debe ser una lista de identificadores de regla.")
        changes["disabled_rules"] = frozenset(raw)

    if "severidades" in data:
        raw = data["severidades"] or {}
        if not isinstance(raw, dict):
            raise ConfigError("«severidades» debe ser un objeto {REGLA: alta}.")
        overrides = {}
        for rule_id, sev in raw.items():
            if not isinstance(rule_id, str) or not _RULE_ID_RE.match(rule_id):
                raise ConfigError(f"Identificador de regla no válido en «severidades»: {clean_text(rule_id, 40)}.")
            if sev not in SEVERITY_WEIGHTS:
                raise ConfigError(f"Severidad no válida para {rule_id}: usa {list(SEVERITY_WEIGHTS)}.")
            overrides[rule_id] = sev
        changes["severity_overrides"] = overrides

    simple = {
        "tiempo_maximo_s": ("timeout_s", 5, 300),
        "espera_tras_carga_ms": ("settle_ms", 0, 15000),
        "max_evidencias": ("max_evidence", 1, 100),
        "max_tabulaciones": ("max_tab_stops", 5, 300),
    }
    for key, (attr, low, high) in simple.items():
        if key in data:
            changes[attr] = int(_number(data[key], key, low, high))

    for key, attr in (("bloquear_redes_privadas", "block_private"), ("redactar_urls", "redact_urls"),
                      ("capturas", "screenshots"), ("teclado", "keyboard")):
        if key in data:
            changes[attr] = _bool(data[key], key)

    if "rendimiento" in data:
        raw = data["rendimiento"]
        if not isinstance(raw, dict) or set(raw) - _RENDIMIENTO_KEYS:
            raise ConfigError(f"«rendimiento» admite solo {sorted(_RENDIMIENTO_KEYS)}.")
        if "activado" in raw:
            changes["performance"] = _bool(raw["activado"], "rendimiento.activado")
        if "limitar_red_y_cpu" in raw:
            changes["throttling"] = _bool(raw["limitar_red_y_cpu"], "rendimiento.limitar_red_y_cpu")

    if data.get("reglas_extra"):
        if not isinstance(data["reglas_extra"], str):
            raise ConfigError("«reglas_extra» debe ser una ruta a un fichero YAML.")
        changes["extra_rules_file"] = (base_dir / data["reglas_extra"]).resolve()

    return replace(cfg, **changes)


def load_yaml_file(path: str | Path, what: str) -> Any:
    """Carga YAML con safe_load (nunca construye objetos Python arbitrarios)."""
    text = read_text_limited(path, MAX_CONFIG_BYTES, what)
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (línea {mark.line + 1})" if mark else ""
        raise ConfigError(f"El {what} no es YAML válido{where}.") from exc


def load_config(path: Optional[str | Path]) -> Config:
    if path is None:
        default = Path("uxaudit.yaml")
        if not default.is_file():
            return Config()
        path = default
    try:
        data = load_yaml_file(path, "fichero de configuración")
    except SecurityError as exc:
        raise ConfigError(str(exc)) from exc
    return parse_config(data, Path(path).expanduser().resolve().parent)


SAMPLE_CONFIG = """\
# Configuración del UX-Auditor para este proyecto.
# Documentación de cada clave: README.md · sección «Configuración».
proyecto: Mi proyecto
perfil: web                 # web (móvil + escritorio) | movil | escritorio
modo: estricto              # estricto (por defecto) | estandar

# Pesos de cada dimensión del Índice IUX (se reescalan si falta alguna).
pesos: {D1: 25, D2: 15, D3: 15, D4: 10, D5: 10, D6: 10, D7: 5, D8: 10}

umbral_ci: 7.0              # «uxaudit run» devuelve código 1 si el IUX queda por debajo

reglas_desactivadas: []     # p. ej. [NAV-BARRA-INFERIOR]
severidades: {}             # p. ej. {INT-CURSOR: media}

tiempo_maximo_s: 45
espera_tras_carga_ms: 1500
bloquear_redes_privadas: false   # true en servidores de CI compartidos (anti-SSRF)
redactar_urls: true              # oculta parámetros (?token=...) en los informes
capturas: true
teclado: true                    # prueba real de navegación con la tecla Tab
rendimiento:
  activado: true
  limitar_red_y_cpu: true        # simula un móvil medio con 4G (como Lighthouse)

# viewports personalizados (opcional; sustituyen a los del perfil):
# viewports:
#   - {nombre: movil, ancho: 375, alto: 812, movil: true, escala: 2}
#   - {nombre: escritorio, ancho: 1440, alto: 900, movil: false}

# reglas_extra: reglas_equipo.yaml   # reglas manuales propias del equipo
"""

SAMPLE_ANSWERS_HEADER = """\
# Respuestas de la evaluación experta (reglas manuales).
# Valores: cumple | parcial | no_cumple | no_aplica   (déjalo vacío si aún no se ha evaluado)
# Puedes rellenarlo a mano o con:  uxaudit manual -o respuestas.yaml
"""
