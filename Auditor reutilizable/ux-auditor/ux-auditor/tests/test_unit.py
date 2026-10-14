"""Pruebas unitarias (sin navegador): puntuación, seguridad, configuración, reglas e informes."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from uxaudit.config import Config, ConfigError, load_config, parse_config
from uxaudit.kb import by_issue, search
from uxaudit.models import CUMPLE, LEGACY_WEIGHTS, NO_APLICA, NO_CUMPLE, PARCIAL, Finding, Rule
from uxaudit.rules import builtin_rules, load_answers, load_rules, sus_from_csv
from uxaudit.privacy import carbon_grams, site_domain, trackers_before_consent
from uxaudit.readability import analyze as readability, syllables_es
from uxaudit.scoring import metric_value, metric_value_high, ratio_value, score_page, status_for
from uxaudit.security import (RequestPolicy, SecurityError, atomic_write, clean_text, ip_forbidden,
                              redact_url, validate_target)

FIXTURES = Path(__file__).parent / "fixtures"


def _rule(rid: str, dim: str, sev: str = "alta", kind: str = "metrica") -> Rule:
    return Rule(rid, dim, rid, sev, kind, "norma", "hacer", "evitar")


# ───────────── puntuación ─────────────

def test_ejemplo_del_documento_da_8_05():
    """Reproduce el ejemplo resuelto del apartado 3.5 del trabajo."""
    notas = {"D1": 7.5, "D2": 8.0, "D3": 9.3, "D4": 8.5, "D5": 6.0, "D6": 9.0}
    rules = [_rule(f"R-{d}", d) for d in notas] + [_rule("SAT-SUS", "D7")]
    findings = {f"R-{d}": Finding(f"R-{d}", status=status_for(n / 10), value=n / 10) for d, n in notas.items()}
    findings["SAT-SUS"] = Finding("SAT-SUS", status=NO_APLICA)
    score = score_page(rules, findings, LEGACY_WEIGHTS, strict=False)
    assert score.iux == pytest.approx(8.05, abs=0.005)
    assert score.level == "Buena"
    assert score.dimensions["D7"].score is None


def test_regla_de_bloqueo_limita_a_4_9():
    rules = [_rule("A11Y-X", "D1", "critica", "auto"), _rule("OK", "D2")]
    findings = {"A11Y-X": Finding("A11Y-X", status=NO_CUMPLE, value=0.0),
                "OK": Finding("OK", status=CUMPLE, value=1.0)}
    # D1 = 0, D2 = 10 → IUX bruto = 20·10/45 = 4,44 (ya < 4,9); subimos D2 con más peso:
    score = score_page(rules, findings, {"D1": 1, "D2": 99}, strict=False)
    assert score.iux_raw > 4.9
    assert score.iux == 4.9
    assert score.blocked_by == ["A11Y-X"]


def test_ratio_y_metricas():
    assert ratio_value(10, 10) == 1.0
    assert ratio_value(9, 10) == 0.5          # ≥ 90 % → parcial
    assert ratio_value(8, 10) == 0.0
    assert ratio_value(0, 0) is None          # no aplica
    assert ratio_value(94, 100, strict=True) == 0.0   # estricto: parcial solo desde el 95 %
    assert ratio_value(95, 100, strict=True) == 0.5
    assert metric_value_high(80, 70, 60, 50) == 1.0 and metric_value_high(55, 70, 60, 50) == 0.25
    lcp = (2500, 4000, 6000)
    assert metric_value(2000, *lcp) == 1.0
    assert metric_value(3100, *lcp) == pytest.approx(0.8)   # 3,1 s → 8 puntos (ejemplo del documento)
    assert metric_value(4000, *lcp) == 0.5
    assert metric_value(7000, *lcp) == 0.0


# ───────────── seguridad ─────────────

@pytest.mark.parametrize("raw", [
    "javascript:alert(1)", "data:text/html,hola", "file:///etc/passwd", "ftp://example.com/x",
    "http://usuario:clave@example.com/", "http:///sin-host", "http://example.com/\x00", "/etc/passwd", "",
    "http://example.com/" + "a" * 3000,
])
def test_objetivos_rechazados(raw):
    with pytest.raises(SecurityError):
        validate_target(raw)


def test_objetivos_validos():
    t = validate_target("https://Example.com/ruta?token=abc#frag")
    assert t.kind == "url" and t.url.startswith("https://example.com/ruta?token=abc")
    assert "abc" not in t.display and "frag" not in t.url
    local = validate_target(str(FIXTURES / "buena.html"))
    assert local.kind == "file" and local.base_dir == FIXTURES.resolve()


@pytest.mark.parametrize("ip,private,blocked", [
    ("169.254.169.254", False, True), ("::ffff:169.254.169.254", False, True), ("fe80::1", False, True),
    ("0.0.0.0", False, True), ("127.0.0.1", False, False), ("127.0.0.1", True, True),
    ("10.0.0.5", True, True), ("192.168.1.1", True, True), ("100.64.0.1", True, True),
    ("93.184.216.34", True, False), ("2606:4700::1111", True, False),
])
def test_politica_de_ips(ip, private, blocked):
    assert (ip_forbidden(ip, private) is not None) == blocked


def test_politica_de_ficheros_locales(tmp_path):
    page = tmp_path / "web" / "index.html"
    page.parent.mkdir()
    page.write_text("<html></html>")
    policy = RequestPolicy(validate_target(str(page)), block_private=False)
    assert policy.check(page.parent.joinpath("img.png").as_uri()) is None
    assert policy.check("file:///etc/passwd") is not None
    assert policy.check((tmp_path / "secreto.txt").as_uri()) is not None
    remote = RequestPolicy(validate_target("https://example.com"), block_private=False)
    assert remote.check("file:///etc/passwd") is not None
    assert remote.check("chrome://settings") is not None
    assert remote.check("http://169.254.169.254/latest/") is not None


def test_texto_no_confiable():
    assert clean_text("a‮b⁦c\x00d\ne", 50) == "abcd e"
    assert len(clean_text("x" * 1000, 20)) == 20
    assert redact_url("https://h.com:8443/p?token=SECRETO#x") == "https://h.com:8443/p?…"


def test_escritura_atomica_segura(tmp_path):
    atomic_write(tmp_path, "informe.json", b"{}")
    assert (tmp_path / "informe.json").read_bytes() == b"{}"
    for bad in ("../fuera.txt", "a/b.txt", ".oculto", "x" * 200):
        with pytest.raises(SecurityError):
            atomic_write(tmp_path, bad, b"")
    target = tmp_path / "destino.txt"
    target.write_text("no tocar")
    os.symlink(target, tmp_path / "enlace.json")
    with pytest.raises(SecurityError):
        atomic_write(tmp_path, "enlace.json", b"ataque")
    assert target.read_text() == "no tocar"


# ───────────── configuración ─────────────

def test_configuracion_estricta(tmp_path):
    with pytest.raises(ConfigError):
        parse_config({"proyeto": "x"}, tmp_path)               # clave mal escrita
    with pytest.raises(ConfigError):
        parse_config({"pesos": {"D9": 10}}, tmp_path)
    with pytest.raises(ConfigError):
        parse_config({"umbral_ci": 11}, tmp_path)
    with pytest.raises(ConfigError):
        parse_config({"tiempo_maximo_s": "45"}, tmp_path)
    cfg = parse_config({"perfil": "movil", "umbral_ci": 7, "pesos": {"D7": 0}}, tmp_path)
    assert [v.name for v in cfg.viewports] == ["movil"] and cfg.threshold == 7 and cfg.weights["D7"] == 0


def test_yaml_no_ejecuta_objetos_python(tmp_path):
    evil = tmp_path / "uxaudit.yaml"
    evil.write_text("proyecto: !!python/object/apply:os.system ['echo hackeado']\n")
    with pytest.raises(ConfigError):
        load_config(evil)


def test_configuracion_demasiado_grande(tmp_path):
    big = tmp_path / "uxaudit.yaml"
    big.write_text("proyecto: " + "x" * 300_000)
    with pytest.raises(ConfigError):
        load_config(big)


# ───────────── reglas, respuestas y SUS ─────────────

def test_catalogo_de_reglas_coherente():
    version, rules = builtin_rules()
    assert version == "2.1.0" and len(rules) >= 100
    ids = [r.id for r in rules]
    assert len(ids) == len(set(ids))
    assert {r.dimension for r in rules} == {"D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"}
    for r in rules:
        assert r.kb_issue is None or by_issue(r.kb_issue), f"{r.id}: directriz «{r.kb_issue}» no existe"


def test_desactivar_y_reponderar_reglas():
    cfg = Config(disabled_rules=frozenset({"INT-CURSOR"}), severity_overrides={"VIS-FUENTES": "alta"})
    _, rules = load_rules(cfg)
    ids = {r.id: r for r in rules}
    assert "INT-CURSOR" not in ids and ids["VIS-FUENTES"].severity == "alta"
    with pytest.raises(ConfigError):
        load_rules(Config(disabled_rules=frozenset({"NO-EXISTE"})))


def test_respuestas_manuales(tmp_path):
    _, rules = builtin_rules()
    f = tmp_path / "r.yaml"
    f.write_text("respuestas:\n  MAN-HOVER: cumple\n  MAN-AYUDA: {resultado: parcial, comentario: falta FAQ}\n  MAN-CONSISTENCIA:\n")
    answers = load_answers(f, rules)
    assert answers == {"MAN-HOVER": ("cumple", ""), "MAN-AYUDA": ("parcial", "falta FAQ")}
    f.write_text("respuestas:\n  A11Y-CONTRASTE: cumple\n")   # no es manual → no se puede «aprobar» a mano
    with pytest.raises(ConfigError):
        load_answers(f, rules)


def test_sus(tmp_path):
    f = tmp_path / "sus.csv"
    f.write_text("id,q1,q2,q3,q4,q5,q6,q7,q8,q9,q10\nP1,5,1,5,1,5,1,5,1,5,1\nP2,3,3,3,3,3,3,3,3,3,3\n")
    assert sus_from_csv(f) == (75.0, 2)       # (100 + 50) / 2
    f.write_text("5,1,5,1,5,1,5,1,5,9\n")
    with pytest.raises(ConfigError):
        sus_from_csv(f)


def test_base_de_conocimiento():
    assert search("touch target size")[0][1].issue in ("Touch Target Size", "Target Size (Minimum)")
    assert by_issue("focusable error summary").severity == "High"


# ───────────── informes ─────────────

def _fake_result():
    from uxaudit.engine import AuditResult, PageResult
    from uxaudit.models import Evidence
    _, rules = builtin_rules()
    payload = "<script>alert('x')</script><img src=x onerror=alert(1)>{{7*7}}"
    findings = {r.id: Finding(r.id, status=CUMPLE, value=1.0) for r in rules}
    findings["A11Y-CONTRASTE"] = Finding("A11Y-CONTRASTE", status=NO_CUMPLE, value=0.0, passed=0, total=1,
                                         measured=payload, evidence=[Evidence("movil", payload, payload)])
    page = PageResult(target=payload, title=payload, findings=findings, warnings=[payload])
    page.score = score_page(rules, findings, Config().weights)
    return AuditResult(payload, "2026-10-13T20:00:00+02:00", "1.0.0", "1.0.0", [page], page.score.iux,
                       page.score.iux, page.score.level, 7.0), rules


def test_informes_escapan_contenido_hostil():
    from uxaudit.reports import to_data
    from uxaudit.reports.html import to_html
    from uxaudit.reports.text import to_json, to_markdown
    result, rules = _fake_result()
    data = to_data(result, rules)
    html = to_html(data, result, Config()).decode()
    assert "<script" not in html and "<img src=x" not in html
    assert "&lt;script&gt;" in html and "{{7*7}}" in html          # sin inyección de plantillas
    assert "Content-Security-Policy" in html and "default-src 'none'" in html
    md = to_markdown(data).decode()
    assert "<script" not in md and "&lt;script&gt;" in md
    assert b"<script>" in to_json(data)   # JSON conserva el dato literal (es dato, no HTML)


# ───────────── modo estricto ─────────────

def _page(statuses: dict[str, tuple[str, str, str]]):
    rules = [Rule(rid, dim, rid, sev, "auto", "n", "h", "e") for rid, (dim, sev, _) in statuses.items()]
    values = {CUMPLE: 1.0, PARCIAL: 0.5, NO_CUMPLE: 0.0}
    findings = {rid: Finding(rid, status=st, value=values[st]) for rid, (_, _, st) in statuses.items()}
    return rules, findings


def test_estricto_fallo_critico_en_cualquier_dimension():
    rules, findings = _page({"A": ("D1", "alta", CUMPLE), "B": ("D2", "alta", CUMPLE), "C": ("D8", "critica", NO_CUMPLE),
                             "D": ("D3", "alta", CUMPLE), "E": ("D4", "alta", CUMPLE)})
    estandar = score_page(rules, findings, Config().weights, strict=False)
    estricto = score_page(rules, findings, Config().weights, strict=True)
    assert estandar.iux > 4.9 and estricto.iux == 4.9
    assert any("C" in c for c in estricto.caps)


def test_estricto_fallo_alto_de_accesibilidad_limita_a_6_9():
    rules, findings = _page({"A": ("D1", "alta", NO_CUMPLE), **{f"X{i}": ("D2", "alta", CUMPLE) for i in range(30)}})
    s = score_page(rules, findings, {"D1": 1, "D2": 99}, strict=True)
    assert s.iux_raw > 6.9 and s.iux == 6.9


def test_estricto_excelente_exige_evaluacion_completa():
    rules, findings = _page({f"X{i}": ("D2", "media", CUMPLE) for i in range(5)})
    rules.append(Rule("MAN-1", "D2", "m", "media", "manual", "n", "h", "e", question="¿?"))
    findings["MAN-1"] = Finding("MAN-1", status="sin_evaluar")
    s = score_page(rules, findings, Config().weights, strict=True)
    assert s.iux_raw == 10 and s.iux == 8.9 and s.level == "Buena"
    findings["MAN-1"] = Finding("MAN-1", status=CUMPLE, value=1.0)
    assert score_page(rules, findings, Config().weights, strict=True).iux == 10


# ───────────── legibilidad, privacidad y carbono ─────────────

@pytest.mark.parametrize("word,n", [("camión", 2), ("país", 2), ("ciudad", 2), ("aéreo", 4), ("guerra", 2),
                                    ("construcción", 3), ("biología", 4), ("rey", 1)])
def test_silabas_espanol(word, n):
    assert syllables_es(word) == n


def test_legibilidad_distingue_textos():
    facil = readability("El tren sale a las diez. Llega a Madrid a las doce. Compra el billete en la web. " * 15, "es")
    dificil = readability(("La implementación de los mecanismos de interoperabilidad administrativa, conforme a lo "
                           "establecido en la normativa reguladora correspondiente, requerirá disposiciones "
                           "complementarias de carácter reglamentario. ") * 8, "es")
    assert facil.score >= 75 and dificil.score < 50
    assert readability("Hola mundo.", "es") is None          # menos de 100 palabras


def test_rastreadores_y_cookies():
    network = [{"url": "https://www.googletagmanager.com/gtag/js?id=G-1"}, {"url": "https://example.com/app.js"},
               {"url": "https://www.facebook.com/tr?id=1"}]
    cookies = [{"name": "_ga", "domain": ".tienda.es"}, {"name": "sesion", "domain": "tienda.es"},
               {"name": "IDE", "domain": ".doubleclick.net"}]
    res = trackers_before_consent(network, cookies, "www.tienda.es")
    assert res["count"] == 4       # gtag, píxel de Meta, cookie _ga, cookie de tercero
    assert trackers_before_consent([{"url": "https://tienda.es/x.js"}], [{"name": "sesion", "domain": "tienda.es"}],
                                   "tienda.es")["count"] == 0
    assert site_domain("www.bbc.co.uk") == "bbc.co.uk" and site_domain("a.b.tienda.es") == "tienda.es"


def test_huella_de_carbono_swd_v4():
    grams, rating = carbon_grams(1_000_000)          # 1 MB
    assert grams == pytest.approx(0.148, abs=0.001) and rating == "C"
    assert carbon_grams(100_000)[1] == "A+"
