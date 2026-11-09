"""Refresh checked-in production assets after editing app/client; no runtime build."""

import gzip
from pathlib import Path

import rcssmin
import rjsmin

ROOT = Path(__file__).resolve().parent.parent
for name, minify in [("app.js", rjsmin.jsmin), ("app.css", rcssmin.cssmin)]:
    source = (ROOT / "app" / "client" / name).read_text()
    (ROOT / "app" / "static" / name).write_text(minify(source) + "\n")

for path in (ROOT / "app" / "static").rglob("*"):
    if path.suffix in {".js", ".css"}:
        path.with_name(path.name + ".gz").write_bytes(
            gzip.compress(path.read_bytes(), compresslevel=9, mtime=0)
        )
