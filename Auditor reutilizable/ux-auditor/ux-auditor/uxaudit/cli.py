"""Interfaz de línea de comandos: uxaudit run | init | manual | reglas | historial | kb."""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import __version__
from .config import SAMPLE_ANSWERS_HEADER, SAMPLE_CONFIG, PROFILES, ConfigError, load_config
from .models import DIMENSIONS, SEVERITY_LABELS
from .security import SecurityError, atomic_write, clean_text, ensure_output_dir, slugify, validate_target

EXIT_OK, EXIT_BELOW_THRESHOLD, EXIT_USAGE, EXIT_AUDIT_FAILED = 0, 1, 2, 3
MAX_TARGETS = 20


def _color(code: str, text: str) -> str:
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
        return f"\033[{code}m{text}\033[0m"
    return text


def _fmt(v: Optional[float]) -> str:
    return "  —  " if v is None else f"{v:5.2f}"


def _warn(msg: str) -> None:
    print(_color("33", f"Aviso: {msg}"), file=sys.stderr)


def _err(msg: str) -> None:
    print(_color("31", f"Error: {msg}"), file=sys.stderr)


# ───────────────────────── run ─────────────────────────

def cmd_run(args: argparse.Namespace) -> int:
    from .engine import audit
    from .history import record
    from .reports import to_data
    from .reports.html import to_html
    from .reports.text import to_json, to_markdown
    from .rules import load_answers, load_rules, sus_from_csv

    cfg = load_config(args.config)
    overrides = {}
    if args.perfil:
        overrides["profile"], overrides["viewports"] = args.perfil, PROFILES[args.perfil]
    if args.umbral is not None:
        if not 0 <= args.umbral <= 10:
            raise ConfigError("--umbral debe estar entre 0 y 10.")
        overrides["threshold"] = args.umbral
    if args.bloquear_redes_privadas:
        overrides["block_private"] = True
    if args.sin_rendimiento:
        overrides["performance"] = False
    if args.sin_capturas:
        overrides["screenshots"] = False
    if args.sin_teclado:
        overrides["keyboard"] = False
    if args.urls_completas:
        overrides["redact_urls"] = False
    if args.proyecto:
        overrides["project"] = clean_text(args.proyecto, 80)
    if args.modo:
        overrides["strict"] = args.modo == "estricto"
    cfg = replace(cfg, **overrides)

    if len(args.objetivos) > MAX_TARGETS:
        raise ConfigError(f"Como máximo {MAX_TARGETS} páginas por auditoría.")
    targets = [validate_target(t) for t in args.objetivos]
    rules_version, rules = load_rules(cfg)
    answers = load_answers(args.respuestas, rules) if args.respuestas else {}
    sus = None
    if args.sus is not None:
        if not 0 <= args.sus <= 100:
            raise ConfigError("--sus debe estar entre 0 y 100.")
        sus = (float(args.sus), 0)
    elif args.sus_csv:
        sus = sus_from_csv(args.sus_csv)

    formats = {f.strip().lower() for f in args.formato.split(",") if f.strip()}
    unknown = formats - {"html", "json", "md"}
    if unknown or not formats:
        raise ConfigError("--formato admite html, json y md (separados por comas).")
    out_dir = ensure_output_dir(args.salida)

    quiet = args.silencioso
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        _warn("se ejecuta como root, por lo que Chromium no puede usar su sandbox. "
             "Para auditar webs de terceros usa un usuario sin privilegios.")
    progress = (lambda _m: None) if quiet else (lambda m: print(m, file=sys.stderr))
    result = audit(targets, cfg, rules, rules_version, answers, sus, progress)

    data = to_data(result, rules)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"uxaudit-{slugify(cfg.project)}-{stamp}"
    written = []
    if "json" in formats:
        written.append(atomic_write(out_dir, base + ".json", to_json(data)))
    if "md" in formats:
        written.append(atomic_write(out_dir, base + ".md", to_markdown(data)))
    if "html" in formats:
        written.append(atomic_write(out_dir, base + ".html", to_html(data, result, cfg)))
    record(out_dir, result, written[-1].name)

    if quiet:
        for page in result.pages:
            if page.error:
                _err(f"{page.target}: {page.error}")
    else:
        _print_summary(result)
        for path in written:
            print(f"  Informe: {path}")
    failed = [p for p in result.pages if p.error]
    if failed:
        # Fallo cerrado: en CI, una página que no se pudo auditar no debe pasar desapercibida.
        _err(f"{len(failed)} de {len(result.pages)} páginas no se pudieron auditar.")
        return EXIT_AUDIT_FAILED
    if cfg.threshold is not None and (result.site_iux is None or result.site_iux < cfg.threshold):
        print(_color("31", f"  ✗ IUX {_fmt(result.site_iux).strip()} por debajo del umbral {cfg.threshold:.2f}"), file=sys.stderr)
        return EXIT_BELOW_THRESHOLD
    return EXIT_OK


def _print_summary(result) -> None:
    print()
    for page in result.pages:
        print(_color("1", f"■ {page.title or page.target}"))
        if page.error:
            print(_color("31", f"  {page.error}"))
            continue
        s = page.score
        for key, d in s.dimensions.items():
            if d.weight <= 0:
                continue
            label = f"  {key} {d.name} "
            print(f"{label:.<52} {_fmt(d.score)}")
        problems = [f for f in page.findings.values() if f.status in ("no_cumple", "parcial")]
        level_color = "32" if (s.iux or 0) >= 7 else ("33" if (s.iux or 0) >= 5 else "31")
        mode = "estricto" if s.strict else "estándar"
        print(_color(level_color, f"  IUX = {_fmt(s.iux).strip()} / 10  →  {s.level.upper()}  [modo {mode}]")
              + f"   ({len(problems)} problemas · cobertura {s.coverage:.0f} %)")
        for cap in s.caps:
            print(_color("31", f"  ⛔ {cap}"))
        if s.manual_pending:
            print(f"  ℹ {len(s.manual_pending)} reglas manuales sin evaluar (uxaudit manual)")
        print()
    if len(result.pages) > 1:
        failed = sum(1 for p in result.pages if p.error)
        extra = f" · {failed} sin auditar" if failed else ""
        print(_color("1", f"IUX del sitio: {_fmt(result.site_iux).strip()} ({result.site_level}) · peor página {_fmt(result.site_min).strip()}{extra}"))


# ───────────────────────── init ─────────────────────────

def cmd_init(args: argparse.Namespace) -> int:
    from .rules import answers_to_yaml, builtin_rules

    directory = ensure_output_dir(args.carpeta)
    config_text = SAMPLE_CONFIG.replace("perfil: web ", f"perfil: {args.perfil} ", 1)
    files = {"uxaudit.yaml": config_text}
    _, rules = builtin_rules()
    files["respuestas.yaml"] = answers_to_yaml({}, rules, SAMPLE_ANSWERS_HEADER)
    for name, content in files.items():
        if (directory / name).exists() and not args.forzar:
            print(f"  · {name} ya existe (usa --forzar para sobrescribirlo)")
            continue
        atomic_write(directory, name, content.encode("utf-8"))
        print(f"  ✓ {directory / name}")
    return EXIT_OK


# ───────────────────────── manual ─────────────────────────

def cmd_manual(args: argparse.Namespace) -> int:
    from .rules import answers_to_yaml, load_answers, load_rules, normalize_answer

    cfg = load_config(args.config)
    _, rules = load_rules(cfg)
    manual = [r for r in rules if r.kind == "manual"]
    out = Path(args.salida)
    answers = load_answers(out, rules) if out.is_file() else {}
    if not sys.stdin.isatty():
        _err("«uxaudit manual» es interactivo; rellena respuestas.yaml a mano si no hay terminal.")
        return EXIT_USAGE
    print("Evaluación experta · responde: c = cumple, p = parcial, n = no cumple, x = no aplica, Intro = mantener/omitir, q = salir\n")
    keys = {"c": "cumple", "p": "parcial", "n": "no_cumple", "x": "no_aplica"}
    for i, rule in enumerate(manual, 1):
        current = answers.get(rule.id, ("", ""))
        print(_color("1", f"[{i}/{len(manual)}] {rule.title}") + f"  ({SEVERITY_LABELS[rule.severity]} · {DIMENSIONS[rule.dimension]})")
        print(f"  {rule.question}")
        if current[0]:
            print(f"  Respuesta actual: {current[0]}")
        while True:
            raw = input("  > ").strip().lower()
            if raw == "q":
                break
            if raw == "":
                break
            if raw in keys:
                comment = clean_text(input("  Comentario (opcional): "), 400)
                answers[rule.id] = (normalize_answer(keys[raw]), comment)
                break
            print("  Respuesta no válida (c/p/n/x/Intro/q).")
        if raw == "q":
            break
        print()
    out_dir = ensure_output_dir(out.parent if str(out.parent) else ".")
    atomic_write(out_dir, out.name, answers_to_yaml(answers, rules, SAMPLE_ANSWERS_HEADER).encode("utf-8"))
    print(f"✓ Guardado en {out_dir / out.name}. Úsalo con: uxaudit run <url> --respuestas {out.name}")
    return EXIT_OK


# ───────────────────────── reglas / historial / kb ─────────────────────────

def cmd_rules(args: argparse.Namespace) -> int:
    from .rules import load_rules

    cfg = load_config(args.config)
    version, rules = load_rules(cfg)
    print(f"Catálogo de reglas {version} · {len(rules)} reglas activas\n")
    for key, name in DIMENSIONS.items():
        dim_rules = [r for r in rules if r.dimension == key and (not args.tipo or r.kind == args.tipo)]
        if args.dimension and key != args.dimension or not dim_rules:
            continue
        print(_color("1", f"{key} · {name} (peso {cfg.weights.get(key, 0):g} %)"))
        for r in dim_rules:
            print(f"  {r.id:<24} {SEVERITY_LABELS[r.severity]:<8} {r.kind:<8} {r.title}")
        print()
    return EXIT_OK


def cmd_history(args: argparse.Namespace) -> int:
    from .history import load

    entries = load(Path(args.salida).expanduser(), args.n)
    if not entries:
        print("No hay auditorías registradas en esa carpeta.")
        return EXIT_OK
    previous = None
    for e in entries:
        trend = ""
        if previous is not None and e["iux"] is not None:
            diff = e["iux"] - previous
            trend = "  =" if abs(diff) < 0.005 else (_color("32", f"  ▲ +{diff:.2f}") if diff > 0 else _color("31", f"  ▼ {diff:.2f}"))
        print(f"{e['fecha']:<26} {_fmt(e['iux'])}  {e['nivel']:<11} {e['proyecto']}{trend}")
        previous = e["iux"] if e["iux"] is not None else previous
    return EXIT_OK


def cmd_kb(args: argparse.Namespace) -> int:
    from .kb import search

    results = search(args.consulta, args.n)
    if not results:
        print("Sin resultados.")
    for score, g in results:
        print(_color("1", f"{g.issue}") + f"  [{g.category} · {g.platform} · {g.severity}]  puntuación {score}")
        print(f"  {g.description}")
        print(f"  Do: {g.do}")
        print(f"  Don't: {g.dont}")
        if g.code_good:
            print(f"  Ejemplo: {g.code_good}")
        print()
    return EXIT_OK


# ───────────────────────── parser ─────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="uxaudit", description="UX-Auditor · Índice de Experiencia de Usuario (IUX 0–10).")
    parser.add_argument("--version", action="version", version=f"uxaudit {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="audita una o varias páginas")
    run.add_argument("objetivos", nargs="+", help="URL http(s) o fichero/carpeta HTML local")
    run.add_argument("-c", "--config", help="fichero de configuración (por defecto ./uxaudit.yaml si existe)")
    run.add_argument("-o", "--salida", default="informes", help="carpeta de informes (por defecto: informes)")
    run.add_argument("-f", "--formato", default="html,json", help="html,json,md (por defecto: html,json)")
    run.add_argument("-r", "--respuestas", help="respuestas de la evaluación experta (YAML)")
    group = run.add_mutually_exclusive_group()
    group.add_argument("--sus", type=float, help="puntuación SUS ya calculada (0–100)")
    group.add_argument("--sus-csv", help="CSV con 10 respuestas (1–5) por participante")
    run.add_argument("--umbral", type=float, help="nota mínima; si no se alcanza, código de salida 1")
    run.add_argument("--perfil", choices=sorted(PROFILES), help="viewports a usar")
    run.add_argument("--proyecto", help="nombre del proyecto en el informe")
    run.add_argument("--modo", choices=["estricto", "estandar"], help="exigencia de la puntuación (por defecto: estricto)")
    run.add_argument("--bloquear-redes-privadas", action="store_true", help="impide acceder a localhost y redes privadas (anti-SSRF)")
    run.add_argument("--sin-rendimiento", action="store_true", help="no mide Core Web Vitals")
    run.add_argument("--sin-capturas", action="store_true", help="no incluye capturas de pantalla")
    run.add_argument("--sin-teclado", action="store_true", help="no hace la prueba de navegación con Tab")
    run.add_argument("--urls-completas", action="store_true", help="muestra parámetros de las URLs en los informes")
    run.add_argument("-q", "--silencioso", action="store_true", help="solo errores")
    run.set_defaults(func=cmd_run)

    init = sub.add_parser("init", help="crea uxaudit.yaml y respuestas.yaml de ejemplo")
    init.add_argument("carpeta", nargs="?", default=".")
    init.add_argument("--perfil", choices=sorted(PROFILES), default="web")
    init.add_argument("--forzar", action="store_true", help="sobrescribe ficheros existentes")
    init.set_defaults(func=cmd_init)

    manual = sub.add_parser("manual", help="cuestionario de evaluación experta (interactivo)")
    manual.add_argument("-c", "--config")
    manual.add_argument("-o", "--salida", default="respuestas.yaml")
    manual.set_defaults(func=cmd_manual)

    rules = sub.add_parser("reglas", help="lista las reglas activas")
    rules.add_argument("-c", "--config")
    rules.add_argument("--dimension", choices=sorted(DIMENSIONS))
    rules.add_argument("--tipo", choices=["auto", "metrica", "manual"])
    rules.set_defaults(func=cmd_rules)

    hist = sub.add_parser("historial", help="evolución de las puntuaciones")
    hist.add_argument("-o", "--salida", default="informes")
    hist.add_argument("-n", type=int, default=20)
    hist.set_defaults(func=cmd_history)

    kb = sub.add_parser("kb", help="busca en la base de conocimiento UI UX Pro Max")
    kb.add_argument("consulta")
    kb.add_argument("-n", type=int, default=3)
    kb.set_defaults(func=cmd_kb)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, SecurityError) as exc:
        _err(str(exc))
        return EXIT_USAGE
    except KeyboardInterrupt:
        _err("Cancelado por el usuario.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
