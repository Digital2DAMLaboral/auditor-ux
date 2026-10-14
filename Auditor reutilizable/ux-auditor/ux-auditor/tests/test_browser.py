"""Pruebas de integración con Chromium real (marcador «browser»)."""
from __future__ import annotations

import http.server
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from uxaudit.config import PROFILES, Config
from uxaudit.engine import audit
from uxaudit.rules import load_rules
from uxaudit.security import validate_target

pytestmark = pytest.mark.browser
FIXTURES = Path(__file__).parent / "fixtures"
FAST = Config(settle_ms=300, throttling=False, timeout_s=20)


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:  # noqa: BLE001
        return False


if not _chromium_available():
    pytest.skip("Chromium no disponible (python -m playwright install chromium)", allow_module_level=True)


def _run(target: str, cfg: Config = FAST, answers=None):
    version, rules = load_rules(cfg)
    result = audit([validate_target(target)], cfg, rules, version, answers or {}, None)
    return result.pages[0]


def _all_manual(value="cumple"):
    _, rules = load_rules(FAST)
    return {r.id: (value, "") for r in rules if r.kind == "manual"}


def _failing(page) -> set[str]:
    return {k for k, f in page.findings.items() if f.status in ("no_cumple", "parcial")}


@pytest.fixture(scope="module")
def buena():
    return _run(str(FIXTURES / "buena.html"), answers=_all_manual())


@pytest.fixture(scope="module")
def mala():
    return _run(str(FIXTURES / "mala.html"))


def test_pagina_buena_puntua_alto(buena):
    assert buena.error is None
    assert buena.score.iux >= 9.5, _failing(buena)
    assert not buena.score.blocked_by and not buena.score.caps
    assert buena.findings["A11Y-MOVIMIENTO"].status == "cumple"
    assert buena.findings["NAV-SALTAR"].status == "cumple"
    assert buena.findings["A11Y-TECLADO-ALCANCE"].status == "cumple"
    assert buena.findings["NAV-PRUEBA-TRONCO"].status == "cumple"
    assert set(buena.screenshots) == {"movil", "escritorio"}


def test_pagina_mala_detecta_los_problemas_sembrados(mala):
    esperados = {
        "A11Y-REFLOW", "A11Y-ZOOM", "A11Y-IDIOMA", "A11Y-FOCO-VISIBLE", "A11Y-MOVIMIENTO", "A11Y-ALT",
        "INT-CLIC-NO-SEMANTICO", "INT-OBJETIVO-WCAG", "VIS-TAM-TEXTO", "VIS-INTERLINEADO", "VIS-FUENTES",
        "VIS-EMOJI-ICONOS", "VIS-DESBORDAMIENTO", "FORM-ETIQUETA-VISIBLE", "FORM-AUTOCOMPLETE",
        "FORM-TIPO-ENTRADA", "FORM-PEGAR", "FORM-GRUPOS", "FORM-ENVIO", "NAV-TITULO", "NAV-LANDMARKS",
        "NAV-ANCLAS-ROTAS", "NAV-TEXTO-ENLACES", "NAV-NUEVA-VENTANA", "NAV-MENU", "NAV-BARRA-INFERIOR",
        "PERF-IMG-DIMENSIONES",
        # huecos del estado del arte
        "A11Y-TAMANO-USUARIO", "A11Y-ALTO-CONTRASTE", "VIS-RESPONSIVE-INTERMEDIO", "A11Y-ESPACIADO-TEXTO",
        # Steve Krug
        "NAV-PRUEBA-TRONCO",
    }
    assert esperados <= _failing(mala), esperados - _failing(mala)
    assert mala.score.iux <= 4.9
    assert "A11Y-REFLOW" in mala.score.blocked_by


def test_sin_evaluacion_experta_no_hay_excelente():
    page = _run(str(FIXTURES / "buena.html"))
    assert page.score.iux <= 8.9 and page.score.level == "Buena"
    assert any("Excelente" in c for c in page.score.caps)


def test_modo_estandar_es_menos_exigente(mala):
    estandar = _run(str(FIXTURES / "mala.html"), replace(FAST, strict=False))
    assert estandar.score.iux > mala.score.iux


def test_resultados_reproducibles(buena):
    again = _run(str(FIXTURES / "buena.html"), answers=_all_manual())
    assert again.score.iux == pytest.approx(buena.score.iux, abs=0.01)


def test_pagina_hostil_no_engana_ni_escapa():
    page = _run(str(FIXTURES / "maliciosa.html"))
    assert page.error is None
    # La página sustituye getComputedStyle, Array.prototype.filter y document.title en su mundo:
    # el auditor mide en un mundo aislado y no se deja engañar.
    assert "Título falso" not in page.title
    assert page.findings["A11Y-TRAMPA-TECLADO"].status == "no_cumple"
    assert any("169.254.169.254" in b for b in page.blocked_requests)
    assert any("diálogo" in w for w in page.warnings) and any("ventana" in w for w in page.warnings)
    # Ningún texto conserva caracteres de control bidireccionales.
    for f in page.findings.values():
        for e in f.evidence:
            assert "‮" not in e.detail and "‮" not in e.selector


def test_bucle_infinito_se_corta_por_tiempo():
    cfg = replace(FAST, timeout_s=5, viewports=PROFILES["escritorio"])
    page = _run(str(FIXTURES / "bucle.html"), cfg)
    assert page.error and "Tiempo máximo" in page.error


@pytest.fixture(scope="module")
def server():
    body = (FIXTURES / "buena.html").read_bytes()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.startswith("/redir"):
                self.send_response(302)
                self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
                self.end_headers()
                return
            if self.path.startswith("/trampas"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write((FIXTURES / "trampas.html").read_bytes())
                return
            if self.path.startswith("/error"):
                self.send_response(500)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_redireccion_a_metadatos_bloqueada(server):
    page = _run(f"{server}/redir")
    assert page.error and "Bloqueado por seguridad" in page.error and page.score is None


def test_bloqueo_de_redes_privadas(server):
    page = _run(f"{server}/ok", replace(FAST, block_private=True))
    assert page.error and "red privada" in page.error


def test_pagina_de_error_http_no_puntua(server):
    page = _run(f"{server}/error")
    assert page.error and "HTTP 500" in page.error


def test_url_con_token_se_oculta(server):
    page = _run(f"{server}/ok?token=SECRETO")
    assert "SECRETO" not in page.target and "SECRETO" not in page.final_url


def test_patrones_oscuros_y_privacidad(server):
    page = _run(f"{server}/trampas.html")
    esperados = {"ETI-COOKIES-RECHAZO", "ETI-PRESELECCION", "ETI-CONFIRMSHAMING", "ETI-URGENCIA", "ETI-RASTREO-PREVIO",
                 "A11Y-CALIDAD-ALT", "A11Y-NOMBRE-EN-ETIQUETA", "A11Y-MULTIMEDIA", "FORM-OBLIGATORIOS",
                 "INT-CTA-COMPITEN", "VIS-TEXTO-COGNITIVO", "A11Y-ESPACIADO-TEXTO",
                 "FORM-FORMATO-LIBRE", "VIS-PALABRAS-INNECESARIAS", "INT-ENLACES-DISTINGUIBLES", "NAV-PRUEBA-TRONCO"}
    assert esperados <= _failing(page), esperados - _failing(page)
    rastreo = " ".join(e.detail for e in page.findings["ETI-RASTREO-PREVIO"].evidence)
    assert "googletagmanager" in rastreo and "_ga" in rastreo and "_fbp" in rastreo
    assert page.score.iux <= 4.9


def test_consistencia_entre_paginas(server):
    cfg = FAST
    version, rules = load_rules(cfg)
    targets = [validate_target(str(FIXTURES / "buena.html")), validate_target(str(FIXTURES / "mala.html"))]
    result = audit(targets, cfg, rules, version, {}, None)
    assert result.pages[0].findings["NAV-CONSISTENCIA"].status == "cumple"
    assert result.pages[1].findings["NAV-CONSISTENCIA"].status == "no_cumple"
