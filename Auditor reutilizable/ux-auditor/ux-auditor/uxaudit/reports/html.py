"""Informe HTML autocontenido y seguro.

* Jinja2 con autoescape SIEMPRE activo: todo dato de la página auditada se escapa.
* Content-Security-Policy estricta (sin scripts, sin recursos externos).
* Las capturas se incrustan como data URI JPEG generadas por el propio auditor.
"""
from __future__ import annotations

import base64
from datetime import datetime
from importlib import resources
from typing import Any

from jinja2 import BaseLoader, Environment, StrictUndefined

from ..config import Config


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    return f"{float(value):.2f}".replace(".", ",").removesuffix(",00") if isinstance(value, (int, float)) else str(value)


def _ms_s(value: Any) -> str:
    return "—" if value is None else f"{value / 1000:.2f} s".replace(".", ",")


def _mb(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value / 1_000_000:.2f} MB".replace(".", ",") if value >= 100_000 else f"{value / 1000:.0f} KB"


def _environment() -> Environment:
    env = Environment(loader=BaseLoader(), autoescape=True, undefined=StrictUndefined,
                      trim_blocks=True, lstrip_blocks=True)
    env.globals.update(fmt=_fmt, ms_s=_ms_s, mb=_mb)
    return env


def _readable_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    months = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
              "octubre", "noviembre", "diciembre"]
    return f"{dt.day} de {months[dt.month - 1]} de {dt.year}, {dt:%H:%M}"


def to_html(data: dict[str, Any], result, cfg: Config) -> bytes:
    template_text = resources.files("uxaudit").joinpath("reports/templates/report.html.j2").read_text(encoding="utf-8")
    template = _environment().from_string(template_text)
    view = dict(data)
    view["fecha_legible"] = _readable_date(data["fecha"])
    sizes = {v.name: v for v in cfg.viewports}
    pages = []
    for page_data, page in zip(data["paginas"], result.pages):
        page_view = dict(page_data)
        shots = []
        for name, jpeg in page.screenshots.items():
            if not jpeg.startswith(b"\xff\xd8\xff"):  # solo JPEG generados por nosotros
                continue
            vp = sizes.get(name)
            shots.append({"nombre": name, "src": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii"),
                          "ancho": vp.width if vp else 800, "alto": vp.height if vp else 600})
        page_view["capturas"] = sorted(shots, key=lambda s: s["ancho"])
        pages.append(page_view)
    view["paginas"] = pages
    return template.render(d=view).encode("utf-8")
