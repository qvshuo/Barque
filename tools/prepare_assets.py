"""Generate deterministic production assets, or verify them with --check."""

import argparse
import gzip
from pathlib import Path

import rcssmin
import rjsmin

ROOT = Path(__file__).resolve().parent.parent


def prepare(check=False):
    expected = {}
    for name, minify in [("app.js", rjsmin.jsmin), ("app.css", rcssmin.cssmin)]:
        source = (ROOT / "app" / "client" / name).read_text()
        expected[ROOT / "app" / "static" / name] = (minify(source) + "\n").encode()
    for path in (ROOT / "app" / "static").rglob("*"):
        if path.suffix in {".js", ".css"}:
            expected[path.with_name(path.name + ".gz")] = gzip.compress(
                expected.get(path, path.read_bytes()), compresslevel=9, mtime=0
            )
    stale = []
    for path, data in expected.items():
        if check:
            if not path.exists() or path.read_bytes() != data:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.write_bytes(data)
    if stale:
        raise SystemExit("Static assets out of sync: " + ", ".join(stale))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    prepare(parser.parse_args().check)
