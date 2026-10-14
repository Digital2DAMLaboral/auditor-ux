# AGENTS.md — auditor-ux

Auditor reutilizable de **experiencia de usuario (UX)**: puntúa de 0 a 10 con una métrica propia, reproducible y comparable. Trabajo de clase de Digitalización (CIF La Laboral, 2º DAM vespertino, curso 2026-27), para OpenCode.

**Estado: fase de diseño, sin código.** Lo que se produce ahora es documentación en `docs/`. No inventes código, comandos ni herramientas que no existan en el repositorio.

## Antes de tocar nada

OpenCode no sigue referencias automáticamente: lee estos ficheros tú, según lo que vayas a hacer.

| Si vas a… | Lee primero |
|---|---|
| Saber en qué fase estamos y qué toca | [`ROUTEMAP.md`](./ROUTEMAP.md) |
| Trabajar en una fase | `docs/<fase>/README.md` y los ficheros de las fases anteriores |
| Entender qué es el proyecto y su alcance | [`README.md`](./README.md) |
| Registrar un cambio de versión | [`CHANGELOG.md`](./CHANGELOG.md) |

## Fases (en orden estricto)

1. `docs/01-estandares-y-referentes` — qué estándares y referentes existen.
2. `docs/02-sota` — estado del arte.
3. `docs/03-sistema-de-metrica` — métrica 0–10, **basada en 01 y 02**.
4. `docs/04-auditor-reutilizable` — `requisitos-analisis.md` y `diseno.md`.

- No avances de fase sin que la anterior cumpla su criterio de cierre (en [`ROUTEMAP.md`](./ROUTEMAP.md)).
- Una fase posterior no puede contradecir una anterior sin corregir la anterior en la misma Pull Request.
- Trabaja solo en la fase que se te indique. Si la petición mezcla fases, di cuál toca primero.

## Fuentes y evidencia

- **No afirmes nada sin fuente.** Cada dato de 01 y 02 lleva enlace a fuente **primaria** (norma, especificación, artículo, documentación oficial) y fecha de consulta.
- Formato de cita: `[Título](URL) — organismo, versión, consultado AAAA-MM-DD`.
- Si no puedes verificar algo, **dilo** y márcalo `TODO(fuente)`. No lo rellenes de memoria ni lo des por cierto.
- Distingue siempre **verificado** (con fuente consultada) de **declarado** (afirmado sin comprobar).
- Los referentes citados abajo son **candidatos de partida, sin verificar**; confirma versión vigente y alcance en la fase 01: Heurísticas de usabilidad de Nielsen, ISO 9241-11 (usabilidad), ISO 9241-210 (diseño centrado en las personas), System Usability Scale (SUS), recorrido cognitivo (cognitive walkthrough).

## Reglas de la métrica (fases 03 y 04)

- **`unknown` no es fallo:** lo que no se pueda medir se declara y no penaliza la nota.
- Cada categoría, peso, umbral o tope se justifica con una fuente de 01 o 02.
- Un fallo puntúa una sola vez, en una sola categoría.
- Una misma web auditada dos veces con la misma versión de la métrica da la misma nota. Incluye siempre un ejemplo de cálculo resuelto.
- Cambiar pesos, umbrales o checks ya fijados exige anotarlo en `CHANGELOG.md` y subir la versión de la métrica.

## Límites con los otros auditores

No invadas su terreno; si algo cae en otra área, referénciala en vez de duplicarla.

- [`auditor-ui`](https://github.com/Digital2DAMLaboral/auditor-ui) y [`auditor-wcag`](https://github.com/Digital2DAMLaboral/auditor-wcag) cubren las otras dos áreas de la familia (ver `README.md`, apartado «Qué no hace»).

## Estilo de documentación

- Español. Títulos claros, frases cortas, tablas para comparar, listas para enumerar.
- Diagramas en **Mermaid**, nunca capturas ni binarios.
- Enlaces relativos entre ficheros del repo. Comprueba que los enlaces que añades apuntan a ficheros que existen.
- Un fichero, un tema. No dupliques contenido: enlaza al fichero que ya lo explica.

## Git y colaboración

- `main` está protegida (o lo estará): **no hagas push ni merge a `main`**. Trabaja en tu rama: `<tipo>/<descripcion-corta>` (p. ej. `docs/estandares-referentes`) y abre una Pull Request. Mergea el profesor.
- **Conventional Commits:** `docs:`, `feat:`, `fix:`, `chore:`, `refactor:`.
- No hagas commit ni push sin que te lo pidan expresamente.
- No reescribas el historial de commits ya publicados (`--force`, `rebase` sobre ramas compartidas).

## Seguridad y privacidad

- **Nunca secretos** en el repositorio: ni tokens, ni claves, ni `.env`, ni en commits ni en ejemplos.
- Privacidad por defecto: sin tracking de usuarios finales, minimización de datos. No incluyas datos personales de alumnado en ficheros públicos (el repositorio es público).
- No modifiques `.opencode/`, hooks ni configuración de agentes sin que se pida de forma explícita.
- Licencia MIT: no copies contenido con derechos de terceros (textos de normas, imágenes) más allá de la cita breve; enlaza a la fuente.

## Cuando dudes

Pregunta antes de decidir si afecta al alcance, a los pesos de la métrica, al orden de fases o a lo que se publica. Es más barato preguntar que rehacer.
