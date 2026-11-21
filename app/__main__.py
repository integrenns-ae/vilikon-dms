"""`python -m app`: how the Werkzeug-Verwalter (and the standalone image) start the DMS. The Verwalter runs it with `cwd`
= the released repository and a clean environment (`HOST`, `PORT`, `DATA_DIR`, …), after `pip install -r
requirements.txt` into `.venv`; the project itself is not installed, `app/__init__.py` reads `VERSION` beside it.

One worker: the store, the page budget and the background fetch live in this one process."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST") or "127.0.0.1",
        port=int(os.environ.get("PORT") or 8090),
        workers=1,
        proxy_headers=True,
        access_log=False,  # paths carry search words from letters; the tool's output ends in the cockpit's logs
    )


if __name__ == "__main__":
    main()
