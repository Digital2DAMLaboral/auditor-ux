"""Informes JSON y Markdown."""
from __future__ import annotations

import json
import re
from typing import Any

from ..models import SEVERITY_LABELS, STATUS_LABELS


def to_json(data: dict[str, Any]) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+!|>~])")


def md(text: Any) -> str:
    """Escapa texto no confiable para Markdown (sin HTML en bruto ni enlaces inyectados)."""
    s = "" if text is None else str(text)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = _MD_SPECIAL.sub(r"\\\1", s)
    return s.replace("\n", " ")


def fmt(score: Any) -> str:
    return "—" if score is None else f"{score:.2f}".replace(".", ",")


def to_markdown(data: dict[str, Any]) -> bytes:
    out: list[str] = []
    site = data["sitio"]
    out.append(f"# Informe UX-Auditor · {md(data['proyecto'])}")
    out.append("")
    out.append(f"- **Fecha:** {md(data['fecha'])}")
    out.append(f"- **IUX del sitio:** **{fmt(site['iux'])} / 10** ({md(site['nivel'])})"
               + (f" · peor página {fmt(site['iux_minimo'])}" if site['paginas'] > 1 else ""))
    if site.get("paginas_con_error"):
        out.append(f"- **Páginas sin auditar:** {site['paginas_con_error']}")
    if data.get("umbral") is not None:
        ok = site.get("supera_umbral")
        out.append(f"- **Umbral CI:** {fmt(data['umbral'])} → {'✅ supera' if ok else '❌ no supera'}")
    out.append(f"- **Herramienta:** UX-Auditor {md(data['herramienta']['version'])} · reglas {md(data['herramienta']['reglas'])}")
    out.append("")
    for page in data["paginas"]:
        out.append(f"## {md(page['objetivo'])}")
        out.append("")
        if page.get("error"):
            out.append(f"> ⚠️ {md(page['error'])}")
            out.append("")
            continue
        out.append(f"**IUX: {fmt(page['iux'])} / 10 — {md(page['nivel'])}** · cobertura {fmt(page['cobertura_pct'])} %")
        if page.get("techos"):
            out.append("")
            out.append(f"> ⛔ Techos aplicados (modo {md(page['modo'])}); sin techos la nota sería {fmt(page['iux_sin_bloqueo'])}:")
            for t in page["techos"]:
                out.append(f"> - {md(t)}")
        out.append("")
        out.append("| Dimensión | Peso | Nota |")
        out.append("|---|---:|---:|")
        for key, d in page["dimensiones"].items():
            out.append(f"| {key} {md(d['nombre'])} | {fmt(d['peso'])} | {fmt(d['nota'])} |")
        out.append("")
        problems = [h for h in page["hallazgos"] if h["estado"] in ("no_cumple", "parcial")]
        out.append(f"### Problemas ({len(problems)})")
        out.append("")
        for h in problems:
            out.append(f"- **[{SEVERITY_LABELS[h['severidad']]}] {md(h['regla'])} · {md(h['titulo'])}** — "
                       f"{STATUS_LABELS[h['estado']]}" + (f" ({md(h['medido'])})" if h.get("medido") else ""))
            out.append(f"  - Norma: {md(h['norma'])}")
            out.append(f"  - Cómo corregirlo: {md(h['correccion']['hacer'])}")
            for e in h["evidencias"][:5]:
                out.append(f"  - [{md(e['viewport'])}] {md(e['selector'])}: {md(e['detalle'])}")
        pending = page.get("manuales_pendientes") or []
        if pending:
            out.append("")
            out.append(f"> ℹ️ Reglas manuales sin evaluar: {md(', '.join(pending))}. Ejecuta `uxaudit manual` para completarlas.")
        for w in page.get("avisos") or []:
            out.append(f"> ⚠️ {md(w)}")
        out.append("")
    return ("\n".join(out) + "\n").encode("utf-8")
