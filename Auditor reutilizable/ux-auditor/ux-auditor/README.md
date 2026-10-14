# UX-Auditor

Auditor reutilizable de **experiencia de usuario** que calcula el **Índice IUX (0–10)** de una web o aplicación web y genera un informe con cada problema, dónde está y cómo corregirlo.

Proyecto del **Equipo UX · Digitalización Avanzada 2º DAM**. Implementa el apartado 04 del trabajo, con la métrica del apartado 03.

| Qué mide | Cómo |
|---|---|
| **D1 Accesibilidad** (25 %) | axe-core (WCAG 2.2 AA) y navegación real con la tecla Tab: foco visible, no tapado y en orden, sin trampas. Además: reflujo a 320 px, espaciado de texto de WCAG 1.4.12, letra del navegador al 200 %, alto contraste de Windows, modo oscuro, orientación, «reducir movimiento», calidad de los textos alternativos, nombre accesible que incluye el texto visible, y vídeo y audio controlables |
| **D2 Usabilidad e interacción** (15 %) | Tamaño de objetivos (WCAG 2.5.8, 44 px en móvil), separación, elementos clicables sin semántica, una llamada a la acción principal (ley de Hick), heurísticas de Nielsen |
| **D3 Rendimiento percibido** (15 %) | LCP, CLS y TBT (aproximación de INP) con móvil 4G y CPU 4× más lenta; peso, formato y tamaño de imágenes, fuentes |
| **D4 Diseño visual y contenido** (10 %) | Tamaño de texto e interlineado, roturas en 600/768/1024/1280 px, legibilidad (Fernández-Huerta / Flesch), texto justificado o en mayúsculas, fuentes, colores, emojis como iconos |
| **D5 Formularios** (10 %) | Etiquetas visibles, campos obligatorios indicados, autocompletado, tipo de campo, pegar en contraseñas (WCAG 3.3.8), fieldset/legend, botón de envío |
| **D6 Navegación** (10 %) | Título, landmarks, «saltar al contenido», anclas rotas, texto de enlaces, menús, barra inferior, **consistencia entre páginas** (WCAG 3.2.3/3.2.4/3.2.6) |
| **D7 Satisfacción** (5 %, opcional) | Puntuación SUS de una prueba con usuarios |
| **D8 Ética, privacidad y sostenibilidad** (10 %) | «Rechazar» cookies tan visible como «Aceptar» (AEPD), rastreo antes del consentimiento, casillas premarcadas, confirmshaming, urgencia falsa, CO2 por visita (SWD v4), costes ocultos, bajas y transparencia de IA |

En total hay **100 reglas**: 72 automáticas, 7 de métrica y 21 del cuestionario experto. Se basan en WCAG 2.2, las heurísticas de Nielsen y los principios de **Steve Krug** («No me hagas pensar», «Haz fácil lo imposible»). Cada problema enlaza con su norma y con la corrección propuesta por **UI UX Pro Max** (`ux-guidelines.csv`).

### Qué cubre que no cubren otras herramientas

Lighthouse, axe-core, WAVE y Pa11y analizan la página tal como se ve por defecto, una por una y sin criterios éticos. El UX-Auditor añade:

- **Patrones oscuros y privacidad.** Detecta:
  - banners de cookies sin «Rechazar» o con «Rechazar» menos visible;
  - casillas premarcadas;
  - textos que culpabilizan («No, prefiero pagar más»);
  - cuentas atrás y escasez artificial;
  - rastreadores y cookies `_ga` o `_fbp` antes del consentimiento.
- **Adaptación al usuario.** Repite las mediciones con el espaciado de texto de WCAG 1.4.12, la letra del navegador al 200 %, el modo de alto contraste, el modo oscuro, los tamaños intermedios y el móvil en horizontal.
- **Calidad, no solo presencia.**
  - Detecta `alt="IMG_2034.jpg"`, `alt="imagen"` y botones cuyo `aria-label` no contiene el texto visible (WCAG 2.5.3, regla experimental y desactivada en axe-core).
  - Mide la legibilidad del texto.
- **Varias páginas a la vez.** Comprueba que el menú y la ayuda sean iguales en todas las páginas del sitio.
- **Sostenibilidad.** Calcula los gramos de CO2e por visita y su calificación de A+ a F.
- **Principios de Steve Krug automatizados:**
  - la **prueba del tronco**: ¿qué sitio es?, ¿en qué página estoy?, ¿qué secciones hay?, ¿dónde estoy?, ¿cómo busco?;
  - no castigar al usuario por escribir los datos a su manera (teléfonos con espacios);
  - **omitir las palabras innecesarias**;
  - que lo clicable se vea clicable.
- **Principios de Krug en el cuestionario experto:** «No me hagas pensar», la portada, la reserva de buena voluntad y las pruebas con 3 usuarios al mes.
- **Modo estricto** (por defecto):
  - Un fallo crítico en cualquier dimensión limita la nota a 4,9.
  - Un fallo alto de accesibilidad la limita a 6,9.
  - Para llegar a «Excelente» hace falta el cuestionario experto completo y ninguna regla alta o crítica sin cumplir.

---

## Instalación

Necesitas **Python 3.10 o superior**.

```bash
cd ux-auditor
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .
python -m playwright install chromium                  # descarga el navegador (una sola vez)
```

## Uso rápido

```bash
uxaudit run https://mi-web.com                         # una URL
uxaudit run ./web/index.html                           # un fichero local
uxaudit run https://mi-web.com https://mi-web.com/contacto --umbral 7   # varias páginas + nota mínima
```

Por defecto los informes se guardan en `informes/` en formato **HTML + JSON** (`-f html,json,md` añade Markdown). El HTML es un único fichero autocontenido que puedes abrir sin conexión.

```
■ Reservas · Restaurante La Marea
  D1 Accesibilidad ................................. 10.00
  D2 Usabilidad e interacción ...................... 10.00
  D3 Rendimiento percibido ......................... 10.00
  ...
  IUX = 8.90 / 10  →  BUENA  [modo estricto]   (0 problemas · cobertura 80 %)
  ⛔ «Excelente» exige una auditoría completa y sin fallos graves: 17 reglas de evaluación experta sin responder…
```

### Flujo completo (automático + experto + usuarios)

```bash
uxaudit init                       # crea uxaudit.yaml y respuestas.yaml
uxaudit manual                     # cuestionario guiado de las 21 reglas expertas (Nielsen…)
uxaudit run https://mi-web.com -r respuestas.yaml --sus-csv sus.csv
uxaudit historial                  # evolución de la nota entre auditorías
```

`sus.csv` tiene una fila por participante con las 10 respuestas del cuestionario SUS (de 1 a 5). La cabecera y una primera columna de identificador son opcionales.

### Otros comandos

| Comando | Para qué |
|---|---|
| `uxaudit reglas [--dimension D1] [--tipo manual]` | Lista las reglas activas con su severidad |
| `uxaudit kb "touch target size"` | Busca en la base de conocimiento de UI UX Pro Max |
| `uxaudit historial -o informes` | Muestra el histórico con tendencia ▲▼ |

### Códigos de salida (para CI)

| Código | Significado |
|---|---|
| 0 | Auditoría correcta y, si hay umbral, superado |
| 1 | IUX por debajo del umbral (`--umbral` o `umbral_ci`) |
| 2 | Error de uso, de configuración o entrada rechazada por seguridad |
| 3 | Alguna página no se pudo auditar (error HTTP, bloqueo de seguridad o tiempo agotado) |

---

## Cómo se calcula el IUX

Es la métrica del apartado 03, aplicada tal cual (`uxaudit/scoring.py`):

- **Peso de cada regla según su severidad:** crítica 4, alta 3, media 2, baja 1.
- **Resultado de cada regla:**
  - *Cumple* = 1.
  - *Parcial* = 0,5, cuando al menos el 90 % de los elementos son correctos.
  - *No cumple* = 0.
  - Las métricas (LCP, CLS, TBT, peso, SUS) usan una escala continua por tramos.
- **Nota de una dimensión:** `Nota(Dk) = 10 · Σ(peso · resultado) / Σ peso`. Solo cuentan las reglas aplicables.
- **IUX:** `IUX = Σ(Peso_k · Nota(Dk)) / Σ Peso_k`. Si una dimensión no tiene datos (por ejemplo D7 sin SUS), su peso se reparte entre las demás.
- **Techos (modo estricto, por defecto):**
  - Una regla **crítica** incumplida en cualquier dimensión limita el IUX a **4,9**.
  - Una regla **alta** incumplida en accesibilidad lo limita a **6,9**.
  - **Excelente** (≥ 9) exige cobertura ≥ 90 %, el cuestionario experto completo y ninguna regla alta o crítica sin cumplir del todo. Si no se cumple, el máximo es **8,9**.
- **Más exigencia en modo estricto:**
  - «Parcial» requiere que al menos el 95 % de los elementos sean correctos.
  - Las métricas son más duras: LCP de 1,8 s para 10 puntos, CLS de 0,05 y TBT de 100 ms.
- **Modo estándar** (`--modo estandar` o `modo: estandar`): solo bloquea los fallos críticos de D1 y usa los umbrales de Google. Útil en las primeras iteraciones.
- **Cobertura:** el informe indica qué porcentaje del peso total se ha evaluado. Mientras falten reglas manuales, la nota es **provisional**.

| IUX | Nivel |
|---|---|
| 9 – 10 | Excelente |
| 7 – 8,9 | Buena |
| 5 – 6,9 | Aceptable |
| 3 – 4,9 | Deficiente |
| 0 – 2,9 | Crítica |

`tests/test_unit.py` reproduce el ejemplo resuelto del documento (8,05, «Buena»).

## Configuración (`uxaudit.yaml`)

```yaml
proyecto: Web restaurante
perfil: web                    # web (móvil + escritorio) | movil | escritorio
pesos: {D1: 25, D2: 20, D3: 15, D4: 15, D5: 10, D6: 10, D7: 5}
umbral_ci: 7.0
reglas_desactivadas: [NAV-BARRA-INFERIOR]
severidades: {INT-CURSOR: media}
tiempo_maximo_s: 45
espera_tras_carga_ms: 1500
bloquear_redes_privadas: false # true en servidores de CI compartidos
redactar_urls: true            # oculta ?token=... en los informes
capturas: true
teclado: true
rendimiento: {activado: true, limitar_red_y_cpu: true}
viewports:                     # opcional
  - {nombre: movil, ancho: 375, alto: 812, movil: true, escala: 2}
  - {nombre: escritorio, ancho: 1440, alto: 900, movil: false}
reglas_extra: reglas_equipo.yaml   # reglas manuales propias (mismo formato que data/rules.yaml)
```

La configuración se valida de forma **estricta**. Una clave mal escrita, un tipo incorrecto o un valor fuera de rango producen un error claro en lugar de ignorarse.

## Por qué es reutilizable

- **Configuración en lugar de código.** Cada proyecto ajusta pesos, umbral, viewports y reglas en `uxaudit.yaml`.
- **Reglas como datos.** El catálogo está en `uxaudit/data/rules.yaml`. Puedes añadir reglas manuales propias con `reglas_extra`.
- **Base de conocimiento intercambiable.** Las correcciones se leen de `ux-guidelines.csv` de UI UX Pro Max. Se actualiza sustituyendo el fichero.
- **Tres formas de uso:**
  - Terminal.
  - Librería Python: `from uxaudit.engine import audit`.
  - Integración continua (ver `.github/workflows/uxaudit.yml`).

## Seguridad

El auditor abre páginas de terceros, que pueden ser hostiles. Está diseñado para que no puedan atacar al equipo que audita ni falsear el resultado. Los detalles están en [SECURITY.md](SECURITY.md); este es el resumen:

- **Validación de entradas.**
  - Solo se aceptan URLs `http`/`https` o ficheros `.html` locales.
  - Se rechazan URLs con credenciales y esquemas como `javascript:` o `file:`.
- **Anti-SSRF.**
  - Nunca se accede a direcciones de metadatos de la nube (169.254.169.254…) ni a rangos reservados.
  - Con `--bloquear-redes-privadas` tampoco se accede a localhost ni a redes privadas.
  - Se comprueba la IP real de cada respuesta, lo que cubre redirecciones y *DNS rebinding*.
- **Navegador aislado.**
  - Cada viewport usa un contexto nuevo: sin descargas, service workers ni permisos.
  - Los diálogos y ventanas emergentes se cierran automáticamente.
  - Nunca se hace clic ni se envían formularios.
- **Mediciones a prueba de manipulación.** Nuestro JavaScript se ejecuta en un **mundo aislado** de Chromium. Las pruebas comprueban que una página que sustituye `getComputedStyle`, `Array.prototype` o `document.title` no consigue engañarlo.
- **Integridad del código de terceros.** `axe.min.js` se verifica con **SHA-256** antes de inyectarlo.
- **Tiempo máximo por proceso.** Cada página se audita en un proceso hijo. Un bucle infinito o una página colgada se corta sin afectar al resto.
- **Informes seguros.**
  - HTML con autoescape y una CSP estricta (`default-src 'none'`, sin scripts).
  - Markdown escapado.
  - Se eliminan los caracteres de control y bidireccionales («Trojan Source»).
  - Las URLs aparecen sin parámetros.
- **Ficheros.**
  - Escritura atómica, con nombres validados y sin seguir enlaces simbólicos.
  - YAML cargado con `safe_load` y límites de tamaño.
  - El código no usa `eval` ni `shell=True`.

## Pruebas

```bash
pip install -e ".[dev]"
pytest                    # 64 pruebas (unitarias + integración con Chromium)
pytest -m "not browser"   # solo las que no necesitan navegador
```

Las pruebas de integración usan cinco páginas de `tests/fixtures/`:

- `buena.html`: una página de referencia bien hecha. Saca 9,5 o más con el cuestionario experto completo; sin él, se queda en 8,9.
- `mala.html`: tiene 32 problemas sembrados, y todos deben detectarse.
- `trampas.html`: patrones oscuros, banner de cookies sin «Rechazar», rastreadores, alt y aria-label de mala calidad, vídeo automático y fallos de Krug: prueba del tronco, teléfono con formato rígido, texto de relleno y enlaces que no parecen enlaces.
- `maliciosa.html`: intenta XSS, SSRF, falsear las mediciones, atrapar el foco y abrir ventanas.
- `bucle.html`: ejecuta un bucle infinito.

## Limitaciones conocidas

- Las comprobaciones automáticas detectan solo una parte de los problemas de accesibilidad y usabilidad. Por eso existen las reglas manuales y la nota es provisional hasta completarlas.
- **TBT es una métrica de laboratorio** que se usa como aproximación de INP. El INP real se mide con usuarios reales (CrUX, RUM).
- Solo funciona con **Chromium**: el mundo aislado y las métricas usan el protocolo de DevTools.
- Las páginas que requieren iniciar sesión no se pueden auditar todavía.
- Si se ejecuta como **root** (por ejemplo, en algunos contenedores Docker), Chromium no puede usar su sandbox. El auditor avisa de ello; usa un usuario sin privilegios para auditar webs de terceros.

## Estructura

```
uxaudit/
├── cli.py              # comandos run, init, manual, reglas, historial, kb
├── engine.py           # orquestación, proceso aislado, datos → hallazgos
├── scoring.py          # Índice IUX, techos y modo estricto (apartado 03)
├── readability.py      # legibilidad Fernández-Huerta / Flesch
├── privacy.py          # rastreadores, cookies y CO2 (SWD v4)
├── config.py           # uxaudit.yaml con validación estricta
├── rules.py            # catálogo de reglas, respuestas manuales y SUS
├── kb.py               # base de conocimiento UI UX Pro Max (BM25)
├── security.py         # validación, anti-SSRF, escritura segura
├── analyzers/
│   ├── browser.py      # Chromium endurecido + mundo aislado (CDP)
│   └── js/             # dom_checks.js, gap_checks.js (huecos) y observador de rendimiento
├── reports/            # JSON, Markdown y HTML (plantilla Jinja2)
├── data/               # rules.yaml + ux-guidelines.csv
└── vendor/axe.min.js   # axe-core 4.11.4 (verificado por SHA-256)
```

## Licencias

- **UX-Auditor:** MIT.
- **axe-core:** MPL-2.0 (`uxaudit/vendor/AXE_LICENSE.txt`).
- **UI UX Pro Max:** `ux-guidelines.csv`, MIT (`uxaudit/data/UI_UX_PRO_MAX_LICENSE.txt`).
