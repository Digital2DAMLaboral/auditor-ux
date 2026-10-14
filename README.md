# auditor-ux

Auditor reutilizable de **experiencia de usuario (UX)** que puntúa de 0 a 10 con un sistema de métrica propio, reproducible y comparable.

Trabajo de clase de la asignatura **Digitalización** (CIF La Laboral, 2º DAM vespertino, curso 2026-27). Pensado para funcionar en [OpenCode](https://opencode.ai).

> **Estado: fase de diseño.** Todavía no hay código. Lo que se describe como «previsto» es diseño, no algo ejecutable.

## Cómo se trabaja

La documentación está en [`docs/`](./docs/README.md) y se desarrolla en cuatro fases, en orden:

1. [Estándares y referentes](./docs/01-estandares-y-referentes/README.md)
2. [SOTA (estado del arte)](./docs/02-sota/README.md)
3. [Sistema de métrica](./docs/03-sistema-de-metrica/README.md) (0–10, basado en 1 y 2)
4. [Auditor reutilizable](./docs/04-auditor-reutilizable/README.md) (requisitos/análisis y diseño)

Las reglas del proyecto están en [`AGENTS.md`](./AGENTS.md).

## Flujo de contribución

`main` está protegida: no se empuja ni se mergea directamente. Cada persona trabaja en su rama.

1. `git switch -c <tipo>/<descripcion-corta>` (p. ej. `docs/estandares-referentes`).
2. Commits con [Conventional Commits](https://www.conventionalcommits.org/es/v1.0.0/) (`docs:`, `feat:`, `fix:`…).
3. `git push -u origin <tu-rama>` y abre una Pull Request hacia `main`.
4. El profesor revisa y hace el merge.

## Principios

- **Evidencia sobre declaración:** toda afirmación lleva fuente y fecha de consulta.
- Lo que el auditor no puede medir se declara desconocido y no penaliza.
- Privacidad por defecto y sin secretos en el repositorio.
- Documentación en español; diagramas en Mermaid.

## Licencia

[MIT](./LICENSE).
