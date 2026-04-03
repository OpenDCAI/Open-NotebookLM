## SQLBot Backend

This package contains the vendored SQLBot core code that will be embedded into
Open-NotebookLM as a native structured-data engine.

### Phase 1 status

- Core package copied into `sqlbot_backend/`
- Imports rewritten from `backend.*` to `sqlbot_backend.*`
- Data resources copied:
  - `few_shot_data/examples.json`
  - `terminology_data/terms.json`
  - `templates/`
- Embedded config made tolerant to host-app environment noise
- Runtime wiring is not switched yet

### Next step

Replace the current HTTP-based data extract bridge with an internal adapter that
calls `sqlbot_backend` services directly inside Open-NotebookLM.
