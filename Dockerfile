# Standalone image. As a Vilikon Werkzeug the DMS is not built from this file: the Verwalter runs ADAPTER.json's build
# and start in its own image (Debian, Python 3.11, pip, Node). Both install the same requirements.txt and build the
# same page (oberflaeche/).
FROM node:22-slim AS page
WORKDIR /page
COPY oberflaeche/package.json oberflaeche/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY oberflaeche ./
RUN npm run build

FROM python:3.11-slim

WORKDIR /srv
COPY requirements.txt ./
RUN python -m venv /srv/.venv && /srv/.venv/bin/pip install --no-cache-dir -r requirements.txt

COPY VERSION ./
COPY app ./app
COPY --from=page /page/dist ./oberflaeche/dist

RUN useradd --system --uid 10001 dms && mkdir -p /data && chown dms /data
USER dms
ENV PATH="/srv/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 DATA_DIR=/data HOST=0.0.0.0 PORT=8090
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health')"
CMD ["python", "-m", "app"]
