# auditor-ux

Auditor reutilizable de **experiencia de usuario (UX): usabilidad, heurísticas, flujos y tareas**. Puntúa de 0 a 10 con un sistema de métrica propio, reproducible y comparable. Proyecto de la asignatura Digitalización; está pensado para funcionar en **OpenCode**.

## Estado

Fase de diseño: aún no hay código. Se trabaja en [`docs/`](./docs/README.md), en cuatro fases ordenadas:

1. `01-estandares-y-referentes` — estándares y referentes del área.
2. `02-sota` — estado del arte.
3. `03-sistema-de-metrica` — métrica 0–10, basada en 01 y 02.
4. `04-auditor-reutilizable` — requisitos/análisis y diseño.

No pases a una fase sin que la anterior esté razonablemente cerrada; la métrica (03) debe poder justificarse con 01 y 02.

## Reglas

- **Evidencia sobre declaración:** no digas «verificado» sin fuente citada o salida real. Toda afirmación de 01 y 02 lleva enlace y fecha de consulta.
- **Lo no medible no es un fallo:** lo que el auditor no pueda comprobar se declara como desconocido y no penaliza la nota.
- Privacidad por defecto, sin tracking de usuarios finales y sin secretos en el repositorio.
- Documentación en español; diagramas en Mermaid.
- Conventional Commits (`feat:`, `docs:`, `chore:`…).
- No modifiques `.opencode/`, hooks ni configuración de agentes sin que se pida explícitamente.
- Decisiones difíciles de revertir (p. ej. fijar pesos de la métrica): hacer un premortem antes.

## Repositorio

Remoto: `git@github.com:Digital2DAMLaboral/auditor-ux.git` (rama `main`).
