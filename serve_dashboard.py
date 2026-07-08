"""
serve_dashboard.py
-------------------
Runs the Part Lookup / Calculator dashboard as a tiny local web app instead
of a static file. dashboard.html on its own (opened via front_end.py's
webbrowser.open) has no way to write a Lead Time correction back to disk —
browsers don't allow a file:// page to silently write shared files. This
server gives the page a same-origin endpoint to do that against, so a
correction saved by one buyer shows up for the next buyer who opens the
tool, and survives reloads.

Run:   python serve_dashboard.py
Then open the printed http://localhost:8765/ URL (it also opens automatically).

Every GET rebuilds the page from stocking_model_output.xlsx +
leadtime_overrides.csv, so it always reflects the latest corrections on
file, even ones saved by someone else since you last opened it.
"""

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module

front_end = import_module("front_end")
leadtime_overrides = import_module("leadtime_overrides")

PORT = 8765


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/dashboard.html"):
            try:
                df = front_end.load_data()
                html = front_end.build_html(df)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Failed to build dashboard: {e}".encode("utf-8"))
                return
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/api/save-override":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            row = leadtime_overrides.upsert_override(
                part_number=payload.get("part_number"),
                corrected_lead_time=payload.get("corrected_lead_time"),
                corrected_by=payload.get("corrected_by"),
                note=payload.get("note", ""),
            )
            self._send_json(200, {"ok": True, "corrected_date": row["corrected_date"]})
        except Exception as e:
            self._send_json(400, {"ok": False, "error": str(e)})


def main():
    server = ThreadingHTTPServer(("localhost", PORT), DashboardHandler)
    url = f"http://localhost:{PORT}/"
    print(f"Serving dashboard at {url}  (Ctrl+C to stop)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
