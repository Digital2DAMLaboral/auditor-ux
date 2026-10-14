"""Orquestador de la auditoría: recolección → reglas → puntuación.

Cada objetivo se audita en un PROCESO HIJO con tiempo máximo: si una página
bloquea el navegador (bucle infinito, promesa que nunca termina...), el proceso
se termina sin afectar al resto de la auditoría.
"""
from __future__ import annotations

import multiprocessing as mp
import queue
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import __version__
from .config import Config, Viewport
from .models import (NO_APLICA, SIN_EVALUAR, Evidence, Finding, PageScore, Rule)
from .privacy import carbon_grams, trackers_before_consent
from .readability import analyze as analyze_readability
from .rules import manual_value
from .scoring import (READABILITY_THRESHOLDS, READABILITY_THRESHOLDS_STRICT, finalize_count_finding,
                      metric_value, metric_value_high, score_page, status_for, thresholds)
from pathlib import PurePath
from urllib.parse import urlsplit

from .security import RequestPolicy, SecurityError, Target, clamp_int, clamp_number, clean_text, redact_url

AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]
MODERN_IMAGE_MIME = ("image/webp", "image/avif", "image/svg+xml")
# Prueba de WCAG 1.4.12 (valores exactos del criterio).
TEXT_SPACING_CSS = ("*:not(script):not(style){line-height:1.5 !important;letter-spacing:0.12em !important;"
                    "word-spacing:0.16em !important}p{margin-bottom:2em !important}")
SWEEP_WIDTHS = (600, 768, 1024, 1280)
AXE_CONTRAST_ONLY = ("(async () => { const r = await axe.run(document, {runOnly: {type: 'rule', values: ['color-contrast']},"
                     " elementRef: false}); const v = r.violations[0], p = r.passes[0];"
                     " return {fail: v ? v.nodes.length : 0, pass: p ? p.nodes.length : 0,"
                     " nodes: v ? v.nodes.slice(0, 15).map(n => ({t: (n.target || []).join(' ').slice(0, 300),"
                     " s: (n.failureSummary || '').slice(0, 300)})) : []}; })()")


@dataclass
class PageResult:
    target: str
    final_url: str = ""
    title: str = ""
    status: Optional[int] = None
    viewports: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    findings: dict[str, Finding] = field(default_factory=dict)
    score: Optional[PageScore] = None
    screenshots: dict[str, bytes] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    blocked_requests: list[str] = field(default_factory=list)
    error: Optional[str] = None
    duration_s: float = 0.0
    axe_version: str = ""
    nav_signature: dict[str, Any] = field(default_factory=dict)
    site_key: str = ""          # host (web) o carpeta (fichero local): solo se comparan páginas del mismo sitio


@dataclass
class AuditResult:
    project: str
    date: str
    tool_version: str
    rules_version: str
    pages: list[PageResult]
    site_iux: Optional[float]
    site_min: Optional[float]
    site_level: str
    threshold: Optional[float]
    sus: Optional[tuple[float, int]] = None


# ───────────────────────── recolección (proceso hijo) ─────────────────────────

def _collect(cfg: Config, target: Target) -> dict[str, Any]:
    """Abre la página en cada viewport y devuelve datos brutos (no confiables)."""
    from .analyzers.browser import DOM_JS, GAP_JS, AnalyzerError, Browser, axe_source

    policy = RequestPolicy(target, cfg.block_private)
    data: dict[str, Any] = {"viewports": {}, "warnings": [], "perf": None, "network": None,
                            "keyboard": None, "reflow": None, "motion": None, "info": {}, "axe_version": ""}
    axe_js = axe_source()
    perf_vp = next((v for v in cfg.viewports if v.mobile), cfg.viewports[0]).name
    kb_vp = next((v for v in cfg.viewports if not v.mobile), cfg.viewports[0]).name
    axe_run = ("(async () => {"
               "const t = new Promise((_, r) => setTimeout(() => r(new Error('axe: tiempo agotado')), 90000));"
               f"const res = await Promise.race([axe.run(document, {{runOnly: {{type: 'tag', values: {AXE_TAGS!r}}},"
               " iframes: false, elementRef: false, performanceTimer: false}), t]);"
               "const pack = (r, keep) => ({id: r.id, impact: r.impact, help: r.help, count: r.nodes.length,"
               " nodes: keep ? r.nodes.slice(0, 25).map(n => ({t: (n.target || []).join(' ').slice(0, 300),"
               " s: (n.failureSummary || '').slice(0, 300)})) : []});"
               "return {violations: res.violations.map(r => pack(r, true)), incomplete: res.incomplete.map(r => pack(r, false)),"
               " passes: res.passes.map(r => pack(r, false)), version: axe.version};})()")

    with Browser(cfg, target, policy) as browser:
        for vp in cfg.viewports:
            is_perf = cfg.performance and vp.name == perf_vp
            run = browser.page(vp, throttle=is_perf and cfg.throttling)
            try:
                nav = run.navigate()
                vp_data: dict[str, Any] = {"nav": nav}
                if is_perf:
                    data["perf"] = run.evaluate("globalThis.__uxperf ? globalThis.__uxperf.read() : null")
                    data["network"] = list(run.resources.values())
                run.stop_throttling()
                if cfg.screenshots:
                    vp_data["screenshot"] = run.screenshot()
                run.evaluate(axe_js)
                vp_data["axe"] = run.evaluate(axe_run, timeout_ms=120_000)
                run.evaluate(DOM_JS)
                data["info"] = run.call("pageInfo")
                vp_data["dom"] = run.call("run", {"mobile": vp.mobile, "viewport": vp.name})

                if cfg.keyboard and vp.name == kb_vp:
                    data["keyboard"] = _keyboard_pass(run, cfg.max_tab_stops)
                if vp.name == perf_vp:
                    data["motion"] = _motion_pass(run)
                    data["reflow"] = run.with_viewport(320, 640, lambda: run.call("reflow"))
                run.evaluate(GAP_JS)
                _gap_passes(run, vp, cfg, data, vp_data, is_perf=vp.name == perf_vp, is_kb=vp.name == kb_vp)
                data["viewports"][vp.name] = vp_data
                data["warnings"] += run.warnings
                if run.dialogs_dismissed:
                    n = run.dialogs_dismissed
                    data["warnings"].append(f"La página abrió {n} diálogo{'s' if n != 1 else ''} (alert/confirm/prompt); se cerraron automáticamente.")
                if run.popups_closed:
                    n = run.popups_closed
                    data["warnings"].append(f"La página abrió {n} ventana{'s' if n != 1 else ''} emergente{'s' if n != 1 else ''}; se cerraron automáticamente.")
                if run.forbidden_responses:
                    data["warnings"].append("La página cargó recursos desde redes no permitidas: "
                                            + "; ".join(sorted(set(run.forbidden_responses))[:5]))
            except AnalyzerError as exc:
                data["warnings"].append(f"[{vp.name}] {exc}")
                if not data["viewports"]:
                    raise
            finally:
                run.close()
    data["blocked"] = policy.blocked
    return data


def _keyboard_pass(run, max_stops: int) -> dict[str, Any]:
    info = run.call("prepareFocus")
    trapped = False
    stops = min(max_stops, clamp_int(info.get("candidates") if isinstance(info, dict) else 0, 0, 600) + 3)
    for _ in range(max(3, stops)):
        run.press_tab()
        state = run.call("recordFocus")
        if not isinstance(state, dict):
            break
        if state.get("done"):
            break
        if clamp_int(state.get("stuck"), 0, 1000) >= 2:
            trapped = True
            break
    info = info if isinstance(info, dict) else {}
    return {"results": run.call("focusSummary", {"trapped": trapped, "hasMain": bool(info.get("hasMain")),
                                                 "beforeMain": clamp_int(info.get("beforeMain"), 0, 10_000)}),
            "trapped": trapped}


def _safe(fn, warnings: list[str], label: str):
    """Ejecuta una prueba opcional: si falla, se avisa y la regla queda «sin evaluar» (no aprueba)."""
    from .analyzers.browser import AnalyzerError
    try:
        return fn()
    except (AnalyzerError, Exception) as exc:  # noqa: BLE001
        warnings.append(f"No se pudo completar la prueba de {label}: {clean_text(str(exc).splitlines()[0] if str(exc) else type(exc).__name__, 160)}")
        return None


def _gap_passes(run, vp: Viewport, cfg: Config, data: dict[str, Any], vp_data: dict[str, Any], *, is_perf: bool, is_kb: bool) -> None:
    """Pruebas de los huecos del estado del arte (ver gap_checks.js)."""
    w = data["warnings"]
    vp_data["gaps"] = _safe(lambda: run.call("run", {"mobile": vp.mobile}, ns="__uxgap"), w, "patrones y contenido") or []

    def spacing():
        run.call("clipStart", ns="__uxgap")
        run.inject_css(TEXT_SPACING_CSS)
        run.page.wait_for_timeout(350)
        try:
            return run.call("clipEnd", "A11Y-ESPACIADO-TEXTO", ns="__uxgap")
        finally:
            run.clear_css()
            run.page.wait_for_timeout(150)
    vp_data["spacing"] = _safe(spacing, w, "espaciado de texto") or []

    if is_kb:
        def font_size():
            before = run.call("textSize", ns="__uxgap")
            run.set_user_font_size(32)
            run.page.wait_for_timeout(400)
            try:
                after = run.call("textSize", ns="__uxgap")
            finally:
                run.set_user_font_size(16)
                run.page.wait_for_timeout(200)
            return {"before": before, "after": after}
        data["fontsize"] = _safe(font_size, w, "tamaño de letra del usuario")

        if cfg.keyboard:
            def forced():
                run.page.emulate_media(forced_colors="active")
                run.page.wait_for_timeout(300)
                try:
                    return _keyboard_pass(run, min(30, cfg.max_tab_stops))
                finally:
                    run.page.emulate_media(forced_colors="none")
            data["forced"] = _safe(forced, w, "alto contraste")

        def sweep():
            out = []
            try:
                for width in SWEEP_WIDTHS:
                    run.page.set_viewport_size({"width": width, "height": 900})
                    run.page.wait_for_timeout(350)
                    res = run.call("reflow")
                    if isinstance(res, dict):
                        res["label"] = f"{width}px"
                        out.append(res)
            finally:
                run.page.set_viewport_size({"width": vp.width, "height": vp.height})
            return out
        data["sweep"] = (data.get("sweep") or []) + (_safe(sweep, w, "tamaños intermedios") or [])
        data["nav_sig"] = _safe(lambda: run.call("navSignature", ns="__uxgap"), w, "navegación")

    if is_perf:
        def dark():
            before = run.call("backgroundSignature", ns="__uxgap")
            run.page.emulate_media(color_scheme="dark")
            run.page.wait_for_timeout(400)
            try:
                after = run.call("backgroundSignature", ns="__uxgap")
                if after == before:
                    return {"supported": False}
                res = run.evaluate(AXE_CONTRAST_ONLY, timeout_ms=90_000)
                return {"supported": True, **(res if isinstance(res, dict) else {})}
            finally:
                run.page.emulate_media(color_scheme="light")
        data["dark"] = _safe(dark, w, "modo oscuro")

        def urgency():
            run.call("urgencyStart", ns="__uxgap")
            run.page.wait_for_timeout(1600)
            return run.call("urgencyEnd", ns="__uxgap")
        vp_data["urgency"] = _safe(urgency, w, "urgencia artificial") or []
        data["readability"] = _safe(lambda: run.call("readabilityText", ns="__uxgap"), w, "legibilidad")
        data["cookies"] = _safe(lambda: [{"name": c.get("name"), "domain": c.get("domain")}
                                         for c in run.context.cookies()][:500], w, "cookies")

        if vp.mobile:
            def orientation():
                portrait = run.call("visibleTextLength", ns="__uxgap")
                def landscape():
                    return {"text": run.call("visibleTextLength", ns="__uxgap"), "reflow": run.call("reflow")}
                land = run.with_viewport(vp.height, vp.width, landscape)
                return {"portrait": portrait, **land}
            data["orientation"] = _safe(orientation, w, "orientación")


def _motion_pass(run) -> dict[str, Any]:
    before = clamp_int(run.call("runningAnimations"), 0, 100_000)
    run.page.emulate_media(reduced_motion="reduce")
    run.page.wait_for_timeout(500)
    after = clamp_int(run.call("runningAnimations"), 0, 100_000)
    run.page.emulate_media(reduced_motion="no-preference")
    return {"before": before, "after": after}


def _child(cfg: Config, target: Target, out: "mp.Queue") -> None:
    try:
        out.put(("ok", _collect(cfg, target)))
    except SecurityError as exc:
        out.put(("security", str(exc)))
    except Exception as exc:  # noqa: BLE001 — se informa sin trazas internas
        name = type(exc).__name__
        msg = str(exc).splitlines()[0] if str(exc) else name
        out.put(("error", f"{name}: {clean_text(msg, 300)}", clean_text(traceback.format_exc(limit=3), 2000)))


def collect_isolated(cfg: Config, target: Target) -> tuple[str, Any]:
    """Ejecuta _collect en un proceso hijo con tiempo máximo estricto."""
    ctx = mp.get_context("spawn")
    out: mp.Queue = ctx.Queue(maxsize=1)
    proc = ctx.Process(target=_child, args=(cfg, target, out), daemon=True)
    hard_limit = cfg.timeout_s * (2 * len(cfg.viewports) + 2) + 30
    proc.start()
    try:
        status, *payload = out.get(timeout=hard_limit)
    except queue.Empty:
        status, payload = "error", [f"Tiempo máximo de auditoría superado ({hard_limit} s). "
                                    "La página puede tener un bucle infinito o tareas que no terminan."]
    finally:
        proc.join(5)
        if proc.is_alive():
            proc.kill()
            proc.join(5)
    return status, payload[0] if payload else None


# ───────────────────────── reglas a partir de los datos ─────────────────────────

class _Builder:
    def __init__(self, rules: list[Rule], cfg: Config):
        self.rules = {r.id: r for r in rules}
        self.cfg = cfg
        self.findings: dict[str, Finding] = {}
        self.values: dict[str, list[tuple[float, Optional[str], str]]] = {}
        self.axe_map = {a: r.id for r in rules for a in r.axe_rules}
        self.notes: dict[str, str] = {}

    def _f(self, rule_id: str) -> Optional[Finding]:
        if rule_id not in self.rules:
            return None
        return self.findings.setdefault(rule_id, Finding(rule_id))

    def evidence(self, f: Finding, viewport: str, selector: Any, detail: Any) -> None:
        if len(f.evidence) < self.cfg.max_evidence:
            f.evidence.append(Evidence(viewport, clean_text(selector, 300), clean_text(detail, 300)))

    def count(self, rule_id: str, viewport: str, passed: Any, total: Any, items: Any = (), measured: Any = None) -> None:
        f = self._f(rule_id)
        if f is None:
            return
        total = clamp_int(total, 0, 1_000_000)
        passed = min(clamp_int(passed, 0, 1_000_000), total)
        f.passed += passed
        f.total += total
        if measured:
            f.measured = clean_text(measured, 160)
        if isinstance(items, list):
            for item in items[: self.cfg.max_evidence]:
                if isinstance(item, dict):
                    self.evidence(f, viewport, item.get("s"), item.get("d"))

    def value(self, rule_id: str, viewport: str, value: Any, measured: Any = None, items: Any = ()) -> None:
        f = self._f(rule_id)
        if f is None:
            return
        v = clamp_number(value, 0, 1)
        if v is None:
            return
        self.values.setdefault(rule_id, []).append((v, clean_text(measured, 160) if measured else None, viewport))
        if isinstance(items, list):
            for item in items[: self.cfg.max_evidence]:
                if isinstance(item, dict):
                    self.evidence(f, viewport, item.get("s"), item.get("d"))

    def finish(self, sus: Optional[tuple[float, int]], answers: dict[str, tuple[str, str]]) -> dict[str, Finding]:
        for rule_id, f in self.findings.items():
            if rule_id in self.values:
                continue
            finalize_count_finding(f, self.cfg.strict)
            if f.total == 0:
                f.note = self.notes.get(rule_id, "No hay elementos a los que aplicar esta regla.")
            else:
                f.measured = f.measured or f"{f.passed} de {f.total} elementos correctos"
        for rule_id, vals in self.values.items():   # reglas de valor: la peor vista
            worst = min(vals, key=lambda item: item[0])
            f = self.findings[rule_id]
            f.value, f.measured = worst[0], worst[1] or (f"{worst[2]}" if worst[2] else None)
            f.status = status_for(f.value)
        for rule in self.rules.values():
            if rule.kind == "manual":
                status, comment = answers.get(rule.id, (SIN_EVALUAR, ""))
                f = Finding(rule.id, status=status, value=manual_value(status) if status != SIN_EVALUAR else None)
                f.note = comment or ("Pendiente de evaluación experta (uxaudit manual)." if status == SIN_EVALUAR else None)
                self.findings[rule.id] = f
            elif rule.id == "SAT-SUS":
                f = Finding(rule.id)
                if sus:
                    f.value = round(sus[0] / 100, 4)
                    f.status = status_for(f.value)
                    f.measured = f"SUS {sus[0]:.1f}/100 ({sus[1]} participantes)"
                else:
                    f.status, f.note = NO_APLICA, "Sin prueba con usuarios: D7 se omite y se reescalan los pesos."
                self.findings[rule.id] = f
            elif rule.id not in self.findings:
                self.findings[rule.id] = Finding(rule.id, status=NO_APLICA,
                                                 note=self.notes.get(rule.id, "No evaluada en esta auditoría."))
        return self.findings


def _rule_applies(rule: Rule, vp: Viewport) -> bool:
    return rule.viewports == "todas" or (rule.viewports == "movil") == vp.mobile


def _gap_findings(b: "_Builder", cfg: Config, data: dict[str, Any], metrics: dict[str, Any], perf_vp: str, kb_vp: str) -> None:
    """Convierte los datos de las pruebas de huecos en hallazgos."""
    strict = cfg.strict

    # Tamaño de letra del usuario (200 %)
    fs = data.get("fontsize")
    if isinstance(fs, dict):
        before, after = clamp_number(fs.get("before"), 1, 500), clamp_number(fs.get("after"), 1, 500)
        if before and after:
            ratio = after / before
            ok, mid = (1.8, 1.5) if strict else (1.6, 1.25)
            v = 1.0 if ratio >= ok else (0.5 if ratio >= mid else 0.0)
            measured = f"con la letra del navegador al 200 %, el texto pasa de {before:.0f} px a {after:.0f} px (×{ratio:.2f})"
            b.value("A11Y-TAMANO-USUARIO", kb_vp, v, measured,
                    [] if v == 1 else [{"s": "html", "d": "Los tamaños de letra en px no escalan con la preferencia del usuario"}])

    # Foco en modo de alto contraste (colores forzados)
    forced = data.get("forced")
    if isinstance(forced, dict):
        for res in forced.get("results") or []:
            if isinstance(res, dict) and res.get("id") == "A11Y-FOCO-VISIBLE":
                items = [{"s": i.get("s"), "d": "en alto contraste: " + str(i.get("d", ""))}
                         for i in (res.get("items") or []) if isinstance(i, dict)]
                b.count("A11Y-ALTO-CONTRASTE", kb_vp, res.get("passed"), res.get("total"), items)

    # Modo oscuro
    dark = data.get("dark")
    if isinstance(dark, dict):
        if not dark.get("supported"):
            b.notes["A11Y-MODO-OSCURO"] = "La web no ofrece tema oscuro (prefers-color-scheme: dark)."
        else:
            fail, ok = clamp_int(dark.get("fail"), 0, 100_000), clamp_int(dark.get("pass"), 0, 100_000)
            nodes = dark.get("nodes") if isinstance(dark.get("nodes"), list) else []
            b.count("A11Y-MODO-OSCURO", perf_vp, ok, ok + fail,
                    [{"s": n.get("t"), "d": "modo oscuro: " + clean_text(n.get("s"), 200)} for n in nodes if isinstance(n, dict)])

    # Orientación (móvil en horizontal)
    ori = data.get("orientation")
    if isinstance(ori, dict) and isinstance(ori.get("portrait"), dict) and isinstance(ori.get("text"), dict):
        p_chars = clamp_int(ori["portrait"].get("chars"), 0, 10_000_000)
        l_chars = clamp_int(ori["text"].get("chars"), 0, 10_000_000)
        rotate = bool(ori["text"].get("rotate"))
        lost = p_chars > 200 and l_chars < p_chars * 0.5
        v = 0.0 if (rotate or lost) else 1.0
        detail = "pide girar el dispositivo" if rotate else (f"en horizontal solo se ve el {100 * l_chars // max(1, p_chars)} % del texto" if lost else "")
        b.value("A11Y-ORIENTACION", perf_vp, v, detail or "el contenido se mantiene en horizontal",
                [{"s": "body", "d": detail}] if detail else [])
        rf = ori.get("reflow")
        if isinstance(rf, dict):
            (data.setdefault("sweep", [])).append({**rf, "label": "móvil horizontal"})

    # Tamaños intermedios
    sweep = data.get("sweep")
    if isinstance(sweep, list) and sweep:
        passed, items = 0, []
        for res in sweep:
            if not isinstance(res, dict):
                continue
            sw, wv = clamp_int(res.get("scrollWidth"), 0, 100_000), clamp_int(res.get("width"), 1, 100_000)
            label = clean_text(res.get("label"), 30)
            if sw <= wv + 1:
                passed += 1
            else:
                culprits = res.get("culprits") if isinstance(res.get("culprits"), list) else []
                first = culprits[0] if culprits and isinstance(culprits[0], dict) else {"s": "html", "d": ""}
                items.append({"s": first.get("s"), "d": f"a {label}: el contenido mide {sw} px en {wv} px. {first.get('d', '')}"})
        b.count("VIS-RESPONSIVE-INTERMEDIO", "varios", passed, len(sweep), items,
                f"{passed} de {len(sweep)} tamaños sin desbordamiento")

    # Legibilidad
    rd = data.get("readability")
    if isinstance(rd, dict):
        result = analyze_readability(str(rd.get("text", ""))[:30000], clean_text(rd.get("lang"), 10))
        if result is None:
            b.notes["VIS-LEGIBILIDAD"] = "Texto insuficiente (menos de 100 palabras) o idioma no compatible (es/en)."
        else:
            table = READABILITY_THRESHOLDS_STRICT if strict else READABILITY_THRESHOLDS
            v = metric_value_high(result.score, *table[result.lang])
            if result.words_per_sentence > (20 if strict else 25) or result.long_sentences_pct > 20:
                v = min(v, 0.5)
            metrics["legibilidad"] = {"indice": result.index_name, "valor": result.score, "nivel": result.label,
                                      "palabras": result.words, "palabras_por_frase": result.words_per_sentence}
            b.value("VIS-LEGIBILIDAD", perf_vp, v,
                    f"{result.index_name} {result.score:.0f} ({result.label}) · {result.words_per_sentence:.0f} palabras/frase · "
                    f"{result.long_sentences_pct:.0f} % de frases de más de 30 palabras",
                    [] if v == 1 else [{"s": "main", "d": f"Texto {result.label}: acorta frases y usa palabras más comunes"}])

    # Rastreo antes del consentimiento
    network = data.get("network") if isinstance(data.get("network"), list) else None
    if network is not None:
        first_nav = next(iter((data.get("viewports") or {}).values()), {}).get("nav", {})
        host = urlsplit(str(first_nav.get("final_url", ""))).hostname or ""
        cookies = data.get("cookies") if isinstance(data.get("cookies"), list) else []
        tr = trackers_before_consent(network, cookies, host)
        metrics["rastreadores"] = tr["count"]
        b.value("ETI-RASTREO-PREVIO", perf_vp, 1.0 if tr["count"] == 0 else 0.0,
                "sin rastreadores ni cookies de seguimiento al cargar" if tr["count"] == 0
                else f"{tr['count']} rastreadores o cookies de seguimiento antes de dar consentimiento", tr["items"])
        total = clamp_int(metrics.get("peso_bytes"), 0, 10**12)
        grams, rating = carbon_grams(total)
        metrics["co2_g"] = grams
        metrics["co2_calificacion"] = rating
        b.value("ETI-CARBONO", perf_vp, metric_value(grams, *thresholds("ETI-CARBONO", strict)),
                f"{grams:.3f} g CO2e por visita (calificación {rating}, modelo SWD v4)".replace(".", ",", 1))

    b.notes.setdefault("ETI-COOKIES-RECHAZO", "No se ha detectado banner de cookies.")
    b.notes.setdefault("NAV-CONSISTENCIA", "Audita 2 o más páginas del mismo sitio para comprobar la consistencia.")


def build_findings(rules: list[Rule], cfg: Config, data: dict[str, Any], sus, answers) -> tuple[dict[str, Finding], dict[str, Any]]:
    b = _Builder(rules, cfg)
    vps = {v.name: v for v in cfg.viewports}
    metrics: dict[str, Any] = {}
    review = 0

    for vp_name, vp_data in (data.get("viewports") or {}).items():
        vp = vps.get(vp_name)
        if vp is None or not isinstance(vp_data, dict):
            continue
        axe = vp_data.get("axe") or {}
        if isinstance(axe, dict):
            for kind in ("violations", "passes"):
                for item in axe.get(kind) or []:
                    if not isinstance(item, dict):
                        continue
                    rule_id = b.axe_map.get(str(item.get("id")), "A11Y-AXE-OTRAS")
                    count = clamp_int(item.get("count"), 0, 100_000)
                    if kind == "passes":
                        b.count(rule_id, vp_name, count, count)
                    else:
                        nodes = item.get("nodes") if isinstance(item.get("nodes"), list) else []
                        help_text = clean_text(item.get("help"), 120)
                        b.count(rule_id, vp_name, 0, count,
                                [{"s": n.get("t"), "d": f"{help_text} — {clean_text(n.get('s'), 200)}"}
                                 for n in nodes if isinstance(n, dict)])
            for item in axe.get("incomplete") or []:
                if isinstance(item, dict):
                    review += clamp_int(item.get("count"), 0, 100_000)
            metrics["axe_revisar"] = review
        merged = []
        for key in ("dom", "gaps", "spacing", "urgency"):
            if isinstance(vp_data.get(key), list):
                merged += vp_data[key]
        for res in merged:
            if not isinstance(res, dict):
                continue
            rule_id = str(res.get("id", ""))
            if rule_id == "__error":
                continue
            rule = b.rules.get(rule_id)
            if rule is None or not _rule_applies(rule, vp):
                continue
            if "value" in res:
                if res.get("value") is not None:
                    b.value(rule_id, vp_name, res.get("value"), res.get("measured"), res.get("items"))
                else:
                    b._f(rule_id)
            else:
                b.count(rule_id, vp_name, res.get("passed"), res.get("total"), res.get("items"), res.get("measured"))

    # Teclado
    kb = data.get("keyboard")
    kb_vp = next((v.name for v in cfg.viewports if not v.mobile), cfg.viewports[0].name)
    if isinstance(kb, dict):
        for res in kb.get("results") or []:
            if isinstance(res, dict) and str(res.get("id")) in b.rules:
                b.count(str(res["id"]), kb_vp, res.get("passed"), res.get("total"), res.get("items"))

    perf_vp = next((v.name for v in cfg.viewports if v.mobile), cfg.viewports[0].name)
    # Reflujo a 320 px
    reflow = data.get("reflow")
    if isinstance(reflow, dict):
        sw, w = clamp_int(reflow.get("scrollWidth"), 0, 100_000), clamp_int(reflow.get("width"), 1, 100_000)
        ok = sw <= w + 1
        b.count("A11Y-REFLOW", "320px", 1 if ok else 0, 1,
                [] if ok else (reflow.get("culprits") or [{"s": "html", "d": f"{sw}px de ancho a 320px"}]),
                f"ancho del contenido {sw} px a {w} px")

    # Movimiento reducido
    motion = data.get("motion")
    if isinstance(motion, dict):
        before, after = clamp_int(motion.get("before"), 0, 100_000), clamp_int(motion.get("after"), 0, 100_000)
        if before > 0:
            v = 1.0 if after == 0 or after <= before * 0.2 else (0.5 if after < before else 0.0)
            b.value("A11Y-MOVIMIENTO", perf_vp, v, f"{before} animaciones → {after} con «reducir movimiento»",
                    [] if v == 1 else [{"s": "document", "d": f"{after} de {before} animaciones siguen activas con prefers-reduced-motion"}])
        else:
            b._f("A11Y-MOVIMIENTO")

    # Rendimiento
    perf = data.get("perf")
    if cfg.performance and isinstance(perf, dict):
        lcp = clamp_number(perf.get("lcp_ms"), 0, 600_000)
        cls = clamp_number(perf.get("cls"), 0, 100)
        tbt = clamp_number(perf.get("tbt_ms"), 0, 600_000)
        metrics.update({"lcp_ms": lcp, "cls": cls, "tbt_ms": tbt, "fcp_ms": clamp_number(perf.get("fcp_ms"), 0, 600_000),
                        "limitacion": "4G lento + CPU 4×" if cfg.throttling else "sin limitación"})
        if lcp is not None:
            b.value("PERF-LCP", perf_vp, metric_value(lcp, *thresholds("PERF-LCP", cfg.strict)), f"LCP {lcp / 1000:.2f} s")
        if cls is not None:
            b.value("PERF-CLS", perf_vp, metric_value(cls, *thresholds("PERF-CLS", cfg.strict)), f"CLS {cls:.3f}")
        if tbt is not None:
            b.value("PERF-TBT", perf_vp, metric_value(tbt, *thresholds("PERF-TBT", cfg.strict)), f"TBT {tbt:.0f} ms")
    network = data.get("network")
    if cfg.performance and isinstance(network, list):
        total = 0
        heavy = []
        images = 0
        for res in network[:3000]:
            if not isinstance(res, dict):
                continue
            size = clamp_int(res.get("bytes"), 0, 2_000_000_000)
            total += size
            if res.get("type") == "Image" and size > 20_000:
                images += 1
                mime = str(res.get("mime", "")).lower()
                if size > 100_000 and not mime.startswith(MODERN_IMAGE_MIME):
                    heavy.append({"s": redact_url(str(res.get("url", ""))), "d": f"{mime or 'imagen'} de {size // 1024} KB"})
        metrics["peso_bytes"] = total
        metrics["peticiones"] = len(network)
        b.value("PERF-PESO", perf_vp, metric_value(total, *thresholds("PERF-PESO", cfg.strict)),
                f"{total / 1_000_000:.2f} MB en {len(network)} peticiones")
        if images:
            b.count("PERF-IMG-FORMATO", perf_vp, images - len(heavy), images, heavy)
        else:
            b._f("PERF-IMG-FORMATO")

    _gap_findings(b, cfg, data, metrics, perf_vp, kb_vp)
    findings = b.finish(sus, answers)
    if "A11Y-AXE-OTRAS" in findings:
        findings["A11Y-AXE-OTRAS"].review = review
    return findings, metrics


# ───────────────────────── API principal ─────────────────────────

def _consistency(pages: list[PageResult], rules: list[Rule]) -> bool:
    """WCAG 3.2.3 / 3.2.4 / 3.2.6: misma navegación, en el mismo orden, y ayuda en el mismo sitio."""
    if not any(r.id == "NAV-CONSISTENCIA" for r in rules):
        return False
    def related(a: PageResult, b: PageResult) -> bool:
        if a.site_key == b.site_key:
            return True
        if a.site_key.startswith("file:") and b.site_key.startswith("file:"):   # carpetas: una dentro de la otra
            pa, pb = PurePath(a.site_key[5:]), PurePath(b.site_key[5:])
            return pa in pb.parents or pb in pa.parents
        return False

    groups: list[list[PageResult]] = []
    for page in (p for p in pages if p.score and p.nav_signature.get("links")):
        for group in groups:
            if related(group[0], page):
                group.append(page)
                break
        else:
            groups.append([page])
    changed = False
    for group in groups:
        if len(group) >= 2:
            _compare_group(group)
            changed = True
    return changed


def _compare_group(ok_pages: list[PageResult]) -> None:
    ref = ok_pages[0].nav_signature
    ref_links = ref["links"]
    for page in ok_pages:
        sig = page.nav_signature
        links = sig["links"]
        shared = [x for x in ref_links if x in links]
        same_order = shared == [x for x in links if x in set(ref_links)]
        overlap = len(shared) / max(len(ref_links), len(links), 1)
        problems = []
        if overlap < 0.6:
            problems.append(f"solo comparte el {overlap:.0%} del menú con «{ok_pages[0].title or ok_pages[0].target}»")
        if not same_order:
            problems.append("los enlaces comunes del menú aparecen en otro orden")
        if ref.get("help") and not sig.get("help"):
            problems.append("falta el enlace de ayuda/contacto que sí hay en otras páginas")
        elif ref.get("helpPos") is not None and sig.get("helpPos") is not None and abs(ref["helpPos"] - sig["helpPos"]) > 0.25:
            problems.append("el enlace de ayuda/contacto cambia de posición")
        f = Finding("NAV-CONSISTENCIA", passed=0 if problems else 1, total=1,
                    measured=f"menú de {len(links)} enlaces · {overlap:.0%} en común con la página de referencia")
        f.value = 0.0 if problems else 1.0
        f.status = status_for(f.value)
        f.evidence = [Evidence("sitio", "nav", clean_text(p, 300)) for p in problems]
        page.findings["NAV-CONSISTENCIA"] = f


def audit(targets: list[Target], cfg: Config, rules: list[Rule], rules_version: str,
          answers: dict[str, tuple[str, str]], sus: Optional[tuple[float, int]],
          progress: Callable[[str], None] = lambda _m: None) -> AuditResult:
    from .scoring import site_score

    pages: list[PageResult] = []
    for target in targets:
        shown = target.display if cfg.redact_urls else target.url
        progress(f"Auditando {shown} …")
        start = time.monotonic()
        page = PageResult(target=shown, viewports=[v.name for v in cfg.viewports],
                          site_key=(f"file:{target.base_dir}" if target.kind == "file" else f"web:{urlsplit(target.url).hostname or ''}"))
        status, payload = collect_isolated(cfg, target)
        page.duration_s = round(time.monotonic() - start, 1)
        if status != "ok":
            page.error = ("Bloqueado por seguridad: " if status == "security" else "") + clean_text(payload, 400)
            pages.append(page)
            progress(f"  ✗ {page.error}")
            continue
        data = payload
        info = data.get("info") if isinstance(data.get("info"), dict) else {}
        page.title = clean_text(info.get("title"), 200)
        first_nav = next(iter((data.get("viewports") or {}).values()), {}).get("nav", {})
        page.status = clamp_int(first_nav.get("status"), 0, 999) or None
        final = str(first_nav.get("final_url", ""))
        page.final_url = redact_url(final) if cfg.redact_urls else clean_text(final, 2048)
        page.warnings = list(dict.fromkeys(clean_text(w, 300) for w in data.get("warnings", [])))[:30]
        page.blocked_requests = [clean_text(w, 300) for w in data.get("blocked", [])][:50]
        first_axe = next(iter((data.get("viewports") or {}).values()), {}).get("axe")
        page.axe_version = clean_text(first_axe.get("version"), 20) if isinstance(first_axe, dict) else ""
        if page.status and page.status >= 400:
            page.error = (f"El servidor respondió con el código HTTP {page.status}: es una página de error, "
                          "no se puntúa para no falsear la nota del sitio.")
            pages.append(page)
            progress(f"  ✗ {page.error}")
            continue
        for name, vp_data in (data.get("viewports") or {}).items():
            shot = vp_data.get("screenshot") if isinstance(vp_data, dict) else None
            if isinstance(shot, (bytes, bytearray)) and shot[:3] == b"\xff\xd8\xff":
                page.screenshots[name] = bytes(shot)
        page.findings, page.metrics = build_findings(rules, cfg, data, sus, answers)
        sig = data.get("nav_sig")
        if isinstance(sig, dict):
            page.nav_signature = {
                "links": [clean_text(x, 40) for x in (sig.get("links") or [])[:40] if isinstance(x, str)],
                "help": [clean_text(x, 40) for x in (sig.get("help") or [])[:5] if isinstance(x, str)],
                "helpPos": clamp_number(sig.get("helpPos"), 0, 1),
            }
        page.score = score_page(rules, page.findings, cfg.weights, cfg.strict)
        pages.append(page)
        iux = page.score.iux
        progress(f"  ✓ IUX {iux:.2f} ({page.score.level})" if iux is not None else "  ✓ sin puntuación")

    if _consistency(pages, rules):
        for page in pages:
            if page.score:
                page.score = score_page(rules, page.findings, cfg.weights, cfg.strict)

    site_iux, site_min, site_level = site_score([p.score for p in pages if p.score])
    return AuditResult(
        project=cfg.project, date=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        tool_version=__version__, rules_version=rules_version, pages=pages, site_iux=site_iux,
        site_min=site_min, site_level=site_level, threshold=cfg.threshold, sus=sus,
    )
