"""Standard-library HTTP server that exposes MelodropApi and the static UI."""

from __future__ import annotations

import json
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Type
from urllib.parse import quote, unquote, urlparse

from melodrop import __version__
from melodrop.web.api import ApiResponse, MelodropApi
from melodrop.web.router import Router

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY_BYTES = 10 * 1024 * 1024
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}
JOB_ID = r"(?P<job_id>[A-Za-z0-9_-]{1,64})"


def build_router(api: MelodropApi) -> Router:
    router = Router()
    router.add("GET", r"/api/config", lambda body, **_: api.config())
    router.add("POST", r"/api/playlist", lambda body, **_: api.inspect(body))
    router.add("POST", r"/api/jobs", lambda body, **_: api.start_job(body))
    router.add("GET", r"/api/jobs/" + JOB_ID, lambda body, job_id: api.job(job_id))
    router.add("POST", r"/api/jobs/" + JOB_ID + r"/cancel", lambda body, job_id: api.cancel(job_id))
    router.add("POST", r"/api/jobs/" + JOB_ID + r"/open-folder", lambda body, job_id: api.open_folder(job_id))
    router.add("POST", r"/api/open-folder", lambda body, **_: api.open_folder())
    return router


def is_local_host(host_header: Optional[str]) -> bool:
    """Reject DNS-rebinding attacks: only answer requests addressed to this machine."""
    if not host_header:
        return False
    host = host_header.strip().lower()
    host = host.split("]")[0] + "]" if host.startswith("[") else host.split(":")[0]
    return host in LOCAL_HOSTS


def make_handler(api: MelodropApi, static_dir: Path = STATIC_DIR) -> Type[BaseHTTPRequestHandler]:
    router = build_router(api)
    static_root = static_dir.resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "Melodrop/" + __version__

        def log_message(self, format: str, *args: Any) -> None:
            pass

        # ---- responses -------------------------------------------------
        def _send_bytes(
            self, status: int, data: bytes, content_type: str, headers: Optional[Dict[str, str]] = None
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, response: ApiResponse) -> None:
            self._send_bytes(response.status, json.dumps(response.body).encode("utf-8"), "application/json")

        def _fail(self, status: int, message: str) -> None:
            self._send_json(ApiResponse(status, {"error": message}))

        # ---- requests --------------------------------------------------
        def _read_json(self) -> Optional[Mapping[str, Any]]:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                return None
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw or b"{}")
            except ValueError:
                return None
            return data if isinstance(data, dict) else None

        def _guard(self) -> bool:
            if not is_local_host(self.headers.get("Host")):
                self._fail(403, "Melodrop only answers requests made to localhost.")
                return False
            return True

        def do_GET(self) -> None:
            if not self._guard():
                return
            path = urlparse(self.path).path
            if path.startswith("/files/"):
                return self._serve_download(unquote(path[len("/files/") :]))
            if not path.startswith("/api/"):
                return self._serve_static(path)
            self._dispatch("GET", path, {})

        def do_POST(self) -> None:
            if not self._guard():
                return
            # Requiring JSON forces a CORS preflight, so other websites can't trigger downloads.
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._fail(415, "Send JSON.")
            body = self._read_json()
            if body is None:
                return self._fail(400, "Bad request.")
            self._dispatch("POST", urlparse(self.path).path, body)

        def _dispatch(self, method: str, path: str, body: Mapping[str, Any]) -> None:
            found = router.match(method, path)
            if found is None:
                status = 405 if router.allows(path) else 404
                return self._fail(status, "Not found." if status == 404 else "Method not allowed.")
            handler, params = found
            try:
                response = handler(body, **params)
            except Exception as exc:  # last-resort guard so the server never dies
                response = ApiResponse(500, {"error": f"Internal error: {exc}"})
            self._send_json(response)  # type: ignore[arg-type]

        # ---- files -----------------------------------------------------
        def _serve_static(self, path: str) -> None:
            name = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (static_root / name).resolve()
            if static_root not in target.parents or not target.is_file():
                return self._fail(404, "Not found.")
            content_type = CONTENT_TYPES.get(target.suffix, "application/octet-stream")
            self._send_bytes(200, target.read_bytes(), content_type, {"Cache-Control": "no-cache"})

        def _serve_download(self, relative: str) -> None:
            target = api.resolve_file(relative)
            if target is None:
                return self._fail(404, "Not found.")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(target.stat().st_size))
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(target.name))
            self.end_headers()
            with open(target, "rb") as handle:
                shutil.copyfileobj(handle, self.wfile)

    return Handler


def create_server(
    api: MelodropApi, host: str = "127.0.0.1", port: int = 8765, static_dir: Path = STATIC_DIR
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(api, static_dir))
    server.daemon_threads = True
    return server
