"""Sesión de navegador endurecida para auditar una página.

Medidas de seguridad:
  * Contexto nuevo por viewport (sin cookies, caché ni perfil persistente).
  * Sin descargas, sin service workers, sin permisos, diálogos y ventanas emergentes cerrados.
  * Cada petición pasa por RequestPolicy (lista blanca de esquemas, anti-SSRF) y,
    además, se verifica la IP REAL a la que se conectó cada respuesta (cubre
    redirecciones y DNS rebinding).
  * Nuestro JavaScript se ejecuta en un mundo aislado (isolated world) de Chromium:
    la página no puede alterar las funciones que usamos para medir.
  * axe-core se verifica con SHA-256 antes de inyectarlo.
  * El sandbox de Chromium se activa siempre que el proceso no se ejecute como root.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from importlib import resources
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from ..config import Config, Viewport
from ..security import RequestPolicy, SecurityError, Target, clean_text, ip_forbidden

WORLD = "uxaudit_isolated"
AXE_SHA256 = "fb83a4378d978ecb7d2dae48a3a3778a84c971ac692f3afd45d714fba89c0f0d"
MOBILE_UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/140.0.0.0 Mobile Safari/537.36 uxaudit/1.0")
MAX_SCREENSHOT_BYTES = 700_000


class AnalyzerError(RuntimeError):
    """Fallo al analizar la página (no es un error de seguridad)."""


def _asset(path: str) -> str:
    return resources.files("uxaudit").joinpath(path).read_text(encoding="utf-8")


def axe_source() -> str:
    data = resources.files("uxaudit").joinpath("vendor/axe.min.js").read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != AXE_SHA256:
        raise SecurityError("axe.min.js no supera la verificación de integridad (SHA-256). "
                            "Reinstala el paquete; no se ejecutará código modificado.")
    return data.decode("utf-8")


PERF_JS = _asset("analyzers/js/perf_observer.js")
DOM_JS = _asset("analyzers/js/dom_checks.js")
GAP_JS = _asset("analyzers/js/gap_checks.js")


class Browser:
    """Navegador Chromium headless compartido por los viewports de un objetivo."""

    def __init__(self, cfg: Config, target: Target, policy: RequestPolicy):
        self.cfg, self.target, self.policy = cfg, target, policy
        self._pw = None
        self.browser = None

    def __enter__(self) -> "Browser":
        args = [
            "--disable-background-networking", "--disable-component-update", "--disable-default-apps",
            "--disable-sync", "--no-first-run", "--disable-extensions", "--disable-client-side-phishing-detection",
            "--disable-features=Translate,OptimizationHints,MediaRouter,AutofillServerCommunication",
            "--metrics-recording-only", "--mute-audio", "--password-store=basic",
        ]
        self._pw = sync_playwright().start()
        try:
            self.browser = self._pw.chromium.launch(
                headless=True,
                chromium_sandbox=(hasattr(os, "geteuid") and os.geteuid() != 0),
                args=args,
            )
        except PlaywrightError as exc:
            self._pw.stop()
            raise AnalyzerError("No se pudo iniciar Chromium. Ejecuta «python -m playwright install chromium».") from exc
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self.browser:
                self.browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    def page(self, viewport: Viewport, throttle: bool) -> "PageRun":
        return PageRun(self, viewport, throttle)


class PageRun:
    """Una carga de la página en un viewport, con un contexto de navegador nuevo."""

    def __init__(self, owner: Browser, viewport: Viewport, throttle: bool):
        self.cfg, self.target, self.policy = owner.cfg, owner.target, owner.policy
        self.viewport = viewport
        self.throttle = throttle
        self.warnings: list[str] = []
        self.resources: dict[str, dict[str, Any]] = {}
        self.forbidden_responses: list[str] = []
        self.main_frame_id: Optional[str] = None
        self._ctx_id: Optional[int] = None
        self.popups_closed = 0
        self.dialogs_dismissed = 0

        self.context = owner.browser.new_context(
            viewport={"width": viewport.width, "height": viewport.height},
            device_scale_factor=viewport.scale,
            is_mobile=viewport.mobile,
            has_touch=viewport.mobile,
            user_agent=MOBILE_UA if viewport.mobile else None,
            locale="es-ES",
            accept_downloads=False,
            service_workers="block",
            ignore_https_errors=False,
            java_script_enabled=True,
            bypass_csp=False,
            permissions=[],
        )
        self.context.set_default_timeout(self.cfg.timeout_s * 1000)
        self.context.set_default_navigation_timeout(self.cfg.timeout_s * 1000)
        self.context.route("**/*", self._route)
        if hasattr(self.context, "route_web_socket"):
            self.context.route_web_socket("**", self._route_ws)
        self.page = self.context.new_page()
        self.context.on("page", self._close_popup)
        self.page.on("dialog", self._dismiss_dialog)
        self.page.on("download", lambda d: d.cancel())

        self.cdp = self.context.new_cdp_session(self.page)
        self.cdp.on("Runtime.executionContextCreated", self._on_context)
        self.cdp.on("Runtime.executionContextsCleared", lambda _e: setattr(self, "_ctx_id", None))
        self.cdp.on("Network.requestWillBeSent", self._on_request)
        self.cdp.on("Network.responseReceived", self._on_response)
        self.cdp.on("Network.loadingFinished", self._on_finished)
        self.cdp.send("Page.enable")
        self.cdp.send("Runtime.enable")
        self.cdp.send("Network.enable", {"maxTotalBufferSize": 1_000_000, "maxResourceBufferSize": 200_000})
        self.main_frame_id = self.cdp.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
        self.cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": PERF_JS, "worldName": WORLD})
        if throttle:
            # Perfil «4G lento» + CPU 4× más lenta (equivalente al modo móvil de Lighthouse).
            self.cdp.send("Network.emulateNetworkConditions", {
                "offline": False, "latency": 150,
                "downloadThroughput": 1_638_400 / 8, "uploadThroughput": 750_000 / 8,
            })
            self.cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})

    # ───── manejadores de eventos ─────
    def _route(self, route) -> None:
        url = route.request.url
        reason = self.policy.check(url)
        if reason:
            self.policy.record_block(url, reason)
            route.abort("blockedbyclient")
        else:
            route.continue_()

    def _route_ws(self, ws) -> None:
        reason = self.policy.check(ws.url)
        if reason:
            # Sin connect_to_server() el WebSocket queda «simulado»: nunca llega a la red.
            # (No se llama a ws.close() aquí: en la API síncrona bloquea el bucle de eventos.)
            self.policy.record_block(ws.url, reason)
        else:
            ws.connect_to_server()

    def _close_popup(self, page) -> None:
        if page != self.page:
            self.popups_closed += 1
            try:
                page.close()
            except PlaywrightError:
                pass

    def _dismiss_dialog(self, dialog) -> None:
        self.dialogs_dismissed += 1
        try:
            dialog.dismiss()
        except PlaywrightError:
            pass

    def _on_context(self, event: dict) -> None:
        ctx = event.get("context", {})
        aux = ctx.get("auxData") or {}
        if ctx.get("name") == WORLD and not aux.get("isDefault") and aux.get("frameId") == self.main_frame_id:
            self._ctx_id = ctx.get("id")

    def _on_request(self, event: dict) -> None:
        if len(self.resources) < 3000:
            self.resources[event.get("requestId", "")] = {
                "url": str(event.get("request", {}).get("url", ""))[:500],
                "type": event.get("type", ""), "frame": event.get("frameId"), "bytes": 0, "mime": "",
            }

    def _on_response(self, event: dict) -> None:
        response = event.get("response", {})
        ip = response.get("remoteIPAddress")
        url = str(response.get("url", ""))
        if ip and urlsplit(url).scheme in ("http", "https"):
            reason = ip_forbidden(ip, self.policy.block_private)
            if reason:
                self.forbidden_responses.append(f"{event.get('type', '?')}: {reason}")
                if event.get("type") == "Document" and event.get("frameId") == self.main_frame_id:
                    self._main_forbidden = reason
        res = self.resources.get(event.get("requestId", ""))
        if res is not None:
            res["mime"] = str(response.get("mimeType", ""))[:80]
            res["status"] = response.get("status")

    def _on_finished(self, event: dict) -> None:
        res = self.resources.get(event.get("requestId", ""))
        if res is not None:
            size = event.get("encodedDataLength")
            res["bytes"] = int(size) if isinstance(size, (int, float)) and size >= 0 else 0

    # ───── navegación ─────
    def navigate(self) -> dict[str, Any]:
        self._main_forbidden = None
        start = time.monotonic()
        try:
            response = self.page.goto(self.target.url, wait_until="load")
        except PlaywrightTimeout as exc:
            raise AnalyzerError(f"La página no terminó de cargar en {self.cfg.timeout_s} s.") from exc
        except PlaywrightError as exc:
            message = str(exc).splitlines()[0]
            if "ERR_BLOCKED_BY_CLIENT" in message:
                raise SecurityError("La navegación se ha bloqueado por la política de red: "
                                    + "; ".join(self.policy.blocked[-3:]))
            raise AnalyzerError(f"No se pudo abrir la página: {clean_text(message, 200)}") from exc
        final_url = self.page.url
        reason = self.policy.check(final_url) or getattr(self, "_main_forbidden", None)
        if reason:
            raise SecurityError(f"La página redirigió a un destino no permitido ({reason}). Auditoría cancelada.")
        status = response.status if response else None
        try:
            self.page.wait_for_load_state("networkidle", timeout=min(10_000, self.cfg.timeout_s * 1000))
        except PlaywrightTimeout:
            self.warnings.append("La red no quedó en reposo (hay peticiones continuas); se mide igualmente.")
        if self.cfg.settle_ms:
            self.page.wait_for_timeout(self.cfg.settle_ms)
        return {"status": status, "final_url": final_url, "load_s": round(time.monotonic() - start, 2)}

    def stop_throttling(self) -> None:
        if self.throttle:
            self.cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
            self.cdp.send("Network.emulateNetworkConditions",
                          {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
            self.throttle = False

    # ───── ejecución en el mundo aislado ─────
    def _context_id(self) -> int:
        deadline = time.monotonic() + 2
        while self._ctx_id is None and time.monotonic() < deadline:
            # Cada llamada a CDP procesa los eventos pendientes (executionContextCreated).
            self.page.wait_for_timeout(50)
        if self._ctx_id is None:
            created = self.cdp.send("Page.createIsolatedWorld", {
                "frameId": self.main_frame_id, "worldName": WORLD, "grantUniveralAccess": False})
            self._ctx_id = created["executionContextId"]
            self.cdp.send("Runtime.evaluate", {"expression": PERF_JS, "contextId": self._ctx_id})
            self.warnings.append("Las métricas de rendimiento pueden ser incompletas (observador tardío).")
        return self._ctx_id

    def evaluate(self, expression: str, timeout_ms: int = 60_000) -> Any:
        result = self.cdp.send("Runtime.evaluate", {
            "expression": expression, "contextId": self._context_id(), "returnByValue": True,
            "awaitPromise": True, "timeout": timeout_ms, "userGesture": False, "silent": True,
        })
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            text = (details.get("exception") or {}).get("description") or details.get("text") or "error"
            raise AnalyzerError(f"Error en el análisis de la página: {clean_text(text, 200)}")
        value = result.get("result", {}).get("value")
        # Límite defensivo del tamaño de los datos devueltos por la página.
        if value is not None and len(json.dumps(value, default=str)) > 5_000_000:
            raise AnalyzerError("La página devolvió un volumen de datos anómalo; análisis cancelado.")
        return value

    def call(self, function: str, *args: Any, timeout_ms: int = 60_000, ns: str = "__ux") -> Any:
        if ns not in ("__ux", "__uxgap") or not function.isidentifier():
            raise AnalyzerError("Llamada interna no permitida.")
        payload = ", ".join(json.dumps(a) for a in args)
        return self.evaluate(f"globalThis.{ns}.{function}({payload})", timeout_ms)

    # ───── hojas de estilo del inspector (no las bloquea la CSP de la página) ─────
    def inject_css(self, css: str) -> None:
        if getattr(self, "_sheet", None) is None:
            self.cdp.send("DOM.enable")
            self.cdp.send("CSS.enable")
            self._sheet = self.cdp.send("CSS.createStyleSheet", {"frameId": self.main_frame_id})["styleSheetId"]
        self.cdp.send("CSS.setStyleSheetText", {"styleSheetId": self._sheet, "text": css})

    def clear_css(self) -> None:
        if getattr(self, "_sheet", None) is not None:
            self.cdp.send("CSS.setStyleSheetText", {"styleSheetId": self._sheet, "text": ""})

    def set_user_font_size(self, standard: int) -> None:
        self.cdp.send("Page.setFontSizes", {"fontSizes": {"standard": standard, "fixed": max(10, round(standard * 13 / 16))}})

    # ───── acciones auxiliares ─────
    def press_tab(self) -> None:
        self.page.keyboard.press("Tab")

    def screenshot(self) -> Optional[bytes]:
        if self.forbidden_responses:
            self.warnings.append("Capturas desactivadas: la página cargó contenido desde una red no permitida.")
            return None
        try:
            data = self.page.screenshot(type="jpeg", quality=55, full_page=False, animations="allow", timeout=15_000)
        except PlaywrightError:
            return None
        return data if len(data) <= MAX_SCREENSHOT_BYTES else None

    def with_viewport(self, width: int, height: int, fn: Callable[[], Any]) -> Any:
        original = {"width": self.viewport.width, "height": self.viewport.height}
        self.page.set_viewport_size({"width": width, "height": height})
        self.page.wait_for_timeout(400)
        try:
            return fn()
        finally:
            self.page.set_viewport_size(original)

    def close(self) -> None:
        try:
            self.context.close()
        except PlaywrightError:
            pass
