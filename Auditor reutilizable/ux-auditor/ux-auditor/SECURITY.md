# Seguridad del UX-Auditor

## Modelo de amenazas

| Activo | Amenaza | Origen |
|---|---|---|
| Equipo o servidor de CI que ejecuta el auditor | Acceso a la red interna (SSRF), robo de credenciales de la nube, lectura de ficheros locales | Página auditada hostil |
| Fiabilidad de la nota | Una página falsea las mediciones para obtener mejor puntuación | Página auditada |
| Quien abre el informe | XSS, phishing o «Trojan Source» incrustados en el informe | Textos, ids o clases de la página auditada |
| Disponibilidad | Bucles infinitos, páginas enormes o promesas que nunca terminan | Página auditada |
| Sistema de ficheros | Sobrescritura mediante enlaces simbólicos, recorrido de rutas o YAML que ejecuta código | Configuración o carpeta de salida manipuladas |

## Controles

### 1. Entradas

`security.validate_target` acepta únicamente:

- URLs `http` o `https`. Se rechazan las que incluyen usuario o contraseña, los esquemas como `javascript:`, `data:`, `file:` o `ftp:`, los caracteres de control y las URLs de más de 2048 caracteres.
- Ficheros `.html`, `.htm` o `.xhtml` existentes. Si se indica una carpeta, se usa su `index.html`.

La configuración, las respuestas y las reglas extra se cargan con `yaml.safe_load`, con un límite de 256 KB y validación estricta de claves, tipos y rangos. Una etiqueta como `!!python/object` produce un error y nunca se ejecuta.

### 2. Red (anti-SSRF)

`RequestPolicy` decide sobre **todas** las peticiones del navegador, incluidos los WebSockets:

- **Siempre bloqueadas:**
  - Las redes 169.254.0.0/16 (metadatos de AWS, GCP y Azure) y 100.100.100.200 (Alibaba).
  - fe80::/10, multidifusión, 0.0.0.0/8 y los rangos reservados.
  - Las direcciones IPv4 incrustadas en IPv6.
- **Con `--bloquear-redes-privadas`:** también localhost, 10/8, 172.16/12, 192.168/16, 100.64/10 y las direcciones ULA de IPv6. Es la opción recomendada en runners de CI compartidos.
- **Comprobación posterior:** se verifica la IP real a la que se conectó cada respuesta (`remoteIPAddress` de DevTools). Esto cubre:
  - Las redirecciones, que la intercepción de Playwright no ve.
  - El *DNS rebinding*.
- **Si el documento principal acaba en un destino prohibido**, la auditoría se cancela sin capturas ni datos.
- **Si lo hace algún subrecurso**, se desactivan las capturas, porque podrían mostrar contenido interno.
- **Ficheros locales:** solo se puede leer dentro de la carpeta del HTML auditado. Una web remota nunca puede leer `file://`.

### 3. Navegador

- **Contexto nuevo por viewport**, sin perfil persistente, cookies ni caché compartida.
- **Bloqueados:** `accept_downloads=False`, `service_workers="block"`, sin permisos y `ignore_https_errors=False`.
- **Diálogos y ventanas emergentes:** se cierran automáticamente y quedan registrados como aviso en el informe.
- **Sin acciones que cambien estado:** el auditor nunca hace clic, no escribe en campos ni envía formularios. Solo pulsa la tecla Tab y dispara un evento `paste` sintético que no modifica el valor del campo. Tampoco acepta banners de cookies.
- **Emulaciones:** las pruebas de adaptación (espaciado de texto, letra al 200 %, alto contraste, modo oscuro) se hacen con DevTools: una hoja de estilos del inspector, `Page.setFontSizes` y `emulateMedia`. Así no se modifica el HTML de la página ni le afecta su CSP, y todo se deshace después de medir.
- **Sandbox de Chromium:** está activo siempre que no se ejecute como root. Si se ejecuta como root, se muestra un aviso.

### 4. Integridad de las mediciones

- Todo el JavaScript del auditor (axe-core, comprobaciones DOM y observador de rendimiento) se ejecuta en un **mundo aislado** creado con `Page.addScriptToEvaluateOnNewDocument(worldName)`. La página comparte el DOM con ese mundo, pero no sus objetos globales. Por eso no puede sustituir `getComputedStyle`, `Array.prototype`, `PerformanceObserver` ni `document.title` para el auditor; `tests/test_browser.py::test_pagina_hostil_no_engana_ni_escapa` lo comprueba.
- `axe.min.js` se verifica con **SHA-256** (`AXE_SHA256` en `analyzers/browser.py`) antes de cada uso.
- Los datos que devuelve la página se tratan como **no confiables**:
  - Se validan los tipos y se acotan los números.
  - Los textos se truncan y se limpian de caracteres de control y bidireccionales.
  - Se limita el número de evidencias y el tamaño total (5 MB).

### 5. Disponibilidad

- Cada objetivo se audita en un **proceso hijo** (`multiprocessing`, modo *spawn*) con un tiempo máximo estricto. Si se supera, el proceso se termina, el navegador se cierra y la auditoría continúa con la página siguiente.
- Hay límites de 20 páginas por ejecución, 600 elementos para el teclado, 1500 controles y 3000 peticiones registradas.

### 6. Informes y ficheros

- **HTML:**
  - Jinja2 con `autoescape=True` y `StrictUndefined`.
  - CSP `default-src 'none'; style-src 'unsafe-inline'; img-src data:`, sin scripts ni recursos externos.
  - `referrer no-referrer`.
  - Las capturas se incrustan como JPEG propios, y antes se comprueba su cabecera.
- **Markdown:** se escapan los caracteres especiales y el HTML.
- **URLs:** por defecto se muestran sin parámetros ni fragmento (`?…`), para no publicar tokens en artefactos de CI.
- **Escritura:**
  - Atómica: fichero temporal y después `os.replace`.
  - Nombres generados y validados: sin «..» ni barras.
  - Nunca se escribe a través de un enlace simbólico.
  - El histórico se abre con `O_NOFOLLOW` y tiene un límite de tamaño.
- **Sin código peligroso:** no hay `eval`, `exec`, `shell=True`, `pickle` de datos externos ni peticiones de red desde Python.

## Riesgos residuales

- **Ejecutar como root** desactiva el sandbox de Chromium. Usa un usuario sin privilegios para auditar webs desconocidas.
- **Ficheros HTML locales:** pueden cargar recursos de su propia carpeta. Audita solo ficheros de confianza o colócalos en una carpeta aislada.
- **Dependencias:**
  - Mantén Playwright actualizado: incluye Chromium y sus parches de seguridad.
  - Revisa las dependencias periódicamente con `pip-audit`.

## Verificación

```bash
pytest                     # 64 pruebas, incluidas las de seguridad
python -m bandit -r uxaudit   # análisis estático: 0 incidencias
```

## Informar de una vulnerabilidad

Contacta con el equipo de forma privada; no abras un issue público. Indica los pasos para reproducirla y la versión (`uxaudit --version`).
