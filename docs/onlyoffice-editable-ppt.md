# ONLYOFFICE Editable PPT Deployment

ThinkFlow editable PPT can optionally embed ONLYOFFICE Document Server for manual PPTX editing. If ONLYOFFICE is not configured, users can still download the generated PPTX.

## Required Settings

Configure these in `fastapi_app/.env` or the deployment environment:

```bash
ONLYOFFICE_DOCUMENT_SERVER_URL=/onlyoffice
ONLYOFFICE_THINKFLOW_PUBLIC_URL=http://host.docker.internal:8213
ONLYOFFICE_DOCUMENT_DOWNLOAD_BASE_URL=http://172.18.0.1:3003
ONLYOFFICE_JWT_SECRET=
```

- `ONLYOFFICE_DOCUMENT_SERVER_URL`: browser-side Document Server entry. For local Vite development, use `/onlyoffice` so browser requests go through the frontend proxy.
- `ONLYOFFICE_THINKFLOW_PUBLIC_URL`: ThinkFlow backend URL reachable from the Document Server container. It is used for save callbacks.
- `ONLYOFFICE_DOCUMENT_DOWNLOAD_BASE_URL`: browser-facing URL used by ONLYOFFICE to download the PPTX. In local Vite development this should point at the frontend origin so cache and document URLs stay same-origin.
- `ONLYOFFICE_JWT_SECRET`: set this only when Document Server JWT is enabled, and keep it identical to the Document Server secret.

## Local Docker Deployment

Start Document Server:

```bash
docker run -d --name thinkflow-onlyoffice \
  -p 8082:80 \
  --add-host=host.docker.internal:host-gateway \
  -e JWT_ENABLED=false \
  -e ALLOW_PRIVATE_IP_ADDRESS=true \
  onlyoffice/documentserver:latest
```

For local Vite development, `frontend_zh/vite.config.ts` proxies `/onlyoffice` to `http://localhost:8082`. Configure Document Server cache URLs to stay on the frontend origin:

```bash
docker cp thinkflow-onlyoffice:/etc/onlyoffice/documentserver/local.json /tmp/thinkflow-onlyoffice-local.json
python - <<'PY'
import json
from pathlib import Path

path = Path("/tmp/thinkflow-onlyoffice-local.json")
data = json.loads(path.read_text())
storage = data.setdefault("storage", {})
storage["externalHost"] = "http://localhost:3003/onlyoffice"
storage["useDirectStorageUrls"] = False
path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
PY
docker cp /tmp/thinkflow-onlyoffice-local.json thinkflow-onlyoffice:/etc/onlyoffice/documentserver/local.json
docker exec thinkflow-onlyoffice supervisorctl restart ds:docservice ds:converter
```

This avoids browser-side failures where ONLYOFFICE returns cache URLs such as `localhost:8082/cache/.../Editor.bin` while the editor is embedded from the frontend origin.

## ThinkFlow Endpoints

Editable PPT uses these backend endpoints:

- `GET /api/v1/kb/outputs/{output_id}/onlyoffice/config`
- `GET|HEAD /api/v1/kb/outputs/{output_id}/onlyoffice/download/{document_key}.pptx`
- `POST /api/v1/kb/outputs/{output_id}/onlyoffice/callback`

The callback downloads ONLYOFFICE's saved PPTX and writes it back to the output storage. PPTX edits are not reverse-synced into PresentAgent IR in this version.

## Production Notes

- Put Document Server behind the same HTTPS domain or a trusted internal URL.
- Enable Document Server JWT in production and set `ONLYOFFICE_JWT_SECRET` to the same secret in ThinkFlow.
- Ensure Document Server can reach `ONLYOFFICE_THINKFLOW_PUBLIC_URL` and the browser can reach `ONLYOFFICE_DOCUMENT_SERVER_URL`.
- Do not commit local container dumps such as `.onlyoffice_*.json`, `.oo_*`, or runtime logs. They are debugging artifacts, not deployable config.

## Quick Check

1. Create or generate an `editable_ppt` output.
2. Open the output workspace.
3. Click `在线编辑 PPTX`.
4. Confirm the editor loads and saves back through the callback.

If the editor reports download error `-4`, re-check `storage.externalHost`, `ONLYOFFICE_DOCUMENT_DOWNLOAD_BASE_URL`, and the `/onlyoffice` proxy.
