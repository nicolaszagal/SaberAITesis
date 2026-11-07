"""Servidor mínimo para el prototipo: recibe POST/GET en 127.0.0.1 y devuelve bytes recibidos y sha256."""

import hashlib
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Manejador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _responder(self, cuerpo: dict) -> None:
        datos = json.dumps(cuerpo).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        self._responder({"ok": True})

    def do_POST(self):
        restante = int(self.headers.get("Content-Length", "0"))
        h, total = hashlib.sha256(), 0
        while restante > 0:
            bloque = self.rfile.read(min(1 << 20, restante))
            if not bloque:
                break
            h.update(bloque)
            total += len(bloque)
            restante -= len(bloque)
        self._responder({"bytes": total, "sha256": h.hexdigest()})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Manejador).serve_forever()
