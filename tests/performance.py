"""Compare the current app with a baseline checkout using identical browser/data/network.

python -m tests.performance --baseline /tmp/barque-baseline --output /tmp/performance.json
"""

import argparse
import gzip
import json
import os
import platform
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from tests.fixtures import configuration


def serve(root, port):
    sys.path.insert(0, str(root))
    from waitress import serve as run

    from app.database import Database
    from app.scheduler import Scheduler
    from app.web import create_app

    with tempfile.TemporaryDirectory(prefix="barque-perf-") as directory:
        database = Database(Path(directory))
        database.import_config(configuration())
        app = create_app(database, Scheduler(database), initial_password="browser-test-password")
        run(app, host="127.0.0.1", port=port, threads=4)


def rss(pid):
    return int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)], text=True).strip())


def source_stats(root, baseline):
    paths = list((root / "app" / "client").rglob("*")) + list(
        (root / "app" / "templates").rglob("*")
    )
    paths = [path for path in paths if path.suffix in {".tsx", ".ts", ".js", ".css", ".html"}]
    maintained = [path for path in paths if path.name != "shadcn.css"]
    return {
        "files": len(paths),
        "lines": sum(len(path.read_text().splitlines()) for path in paths),
        "maintained_files": len(maintained),
        "maintained_lines": sum(len(path.read_text().splitlines()) for path in maintained),
    }


def asset_stats(root, baseline):
    directory = root / "app" / "static"
    result = {}
    for kind, suffixes in {
        "js": {".js"},
        "css": {".css"},
        "images": {".png", ".webp", ".ico"},
    }.items():
        paths = [path for path in directory.rglob("*") if path.suffix in suffixes]
        result[kind] = {
            "raw": sum(path.stat().st_size for path in paths),
            "gzip": sum(
                len(gzip.compress(path.read_bytes(), compresslevel=9, mtime=0)) for path in paths
            ),
        }
    return result


def measure(root, baseline, browser, runs):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-m", "tests.performance", "--serve", str(root), "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        url = f"http://127.0.0.1:{port}"
        probe = browser.new_context(base_url=url)
        for _ in range(100):
            try:
                if probe.request.get("/api/auth/session").ok:
                    break
            except Exception:
                time.sleep(0.05)
        else:
            raise RuntimeError("Performance server failed to start")
        probe.close()
        result = {
            "source": source_stats(root, baseline),
            "assets": asset_stats(root, baseline),
            "idle_rss_kib": rss(process.pid),
            "pages": {},
        }
        for page_name, target, heading in [
            ("home", "/", "我的订阅"),
            (
                "subscriptions",
                "/?page=subscriptions",
                "管理订阅" if baseline else "订阅",
            ),
            ("settings", "/?page=settings", "设置"),
        ]:
            samples = {"cold": [], "warm": []}
            for _ in range(runs):
                context = browser.new_context(
                    base_url=url,
                    viewport={"width": 1440, "height": 1000},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    color_scheme="light",
                )
                assert context.request.post(
                    "/api/auth/login",
                    headers={"X-Barque-Request": "1"},
                    data={"password": "browser-test-password"},
                ).ok
                page = context.new_page()
                page.on("dialog", lambda dialog: dialog.accept())
                page.add_init_script(
                    "window.lastLCP=0;new PerformanceObserver(list=>{for(const e of list.getEntries())window.lastLCP=e.startTime}).observe({type:'largest-contentful-paint',buffered:true})"
                )
                cdp = context.new_cdp_session(page)
                cdp.send("Network.enable")
                cdp.send("Page.bringToFront")
                cdp.send(
                    "Network.emulateNetworkConditions",
                    {
                        "offline": False,
                        "latency": 40,
                        "downloadThroughput": 10 * 1024 * 1024 / 8,
                        "uploadThroughput": 10 * 1024 * 1024 / 8,
                    },
                )
                cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
                requests, transfers = [], []
                cdp.on(
                    "Network.requestWillBeSent",
                    lambda event: (
                        requests.append(event["request"]["url"])
                        if event["request"]["url"].startswith(url + "/")
                        else None
                    ),
                )
                cdp.on(
                    "Network.loadingFinished",
                    lambda event: transfers.append(event["encodedDataLength"]),
                )
                for cache in ["cold", "warm"]:
                    requests.clear()
                    transfers.clear()
                    if cache == "cold":
                        page.goto(target)
                    else:
                        page.reload()
                    page.get_by_role("heading", name=heading, exact=True).wait_for()
                    if page_name == "home":
                        page.get_by_text("订阅7", exact=True).wait_for()
                    elif page_name == "subscriptions":
                        page.get_by_role("group", name="订阅7", exact=True).wait_for()
                    else:
                        page.locator('input[placeholder="e.g. Asia/Shanghai"]').wait_for()
                    page.wait_for_timeout(400)
                    page.wait_for_function("() => window.lastLCP > 0", timeout=5000)
                    timing = page.evaluate(
                        "({fcp:performance.getEntriesByName('first-contentful-paint')[0]?.startTime,lcp:window.lastLCP,html:performance.getEntriesByType('navigation')[0].decodedBodySize,htmlTransferred:performance.getEntriesByType('navigation')[0].encodedBodySize})"
                    )
                    timing.update(
                        requests=len(requests),
                        network_requests=sum(size > 0 for size in transfers),
                        transfer_bytes=sum(transfers),
                        heap_bytes=cdp.send("Runtime.getHeapUsage")["usedSize"],
                    )
                    # Include event handling and the subsequent browser frame, measured in-page.
                    if page_name == "home":
                        timing["interaction_ms"] = page.evaluate(
                            "async()=>{const input=document.querySelector('input[placeholder=\"搜索订阅\"]');const start=performance.now();const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;setter.call(input,'订阅7');input.dispatchEvent(new Event('input',{bubbles:true}));await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));return performance.now()-start}"
                        )
                    elif page_name == "subscriptions":
                        timing["interaction_ms"] = page.evaluate(
                            "async()=>{const button=[...document.querySelectorAll('button')].find(b=>b.textContent.includes('添加分类'));const start=performance.now();button.click();await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));return performance.now()-start}"
                        )
                    else:
                        timing["interaction_ms"] = page.evaluate(
                            "async()=>{const button=document.querySelector('[aria-label=\"显示推送地址\"]');const start=performance.now();button.click();await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));return performance.now()-start}"
                        )
                    samples[cache].append(timing)
                context.close()
            result["pages"][page_name] = {
                cache: {
                    key: round(statistics.median(sample[key] for sample in values), 2)
                    for key in values[0]
                }
                for cache, values in samples.items()
            }
        result["operations_rss_kib"] = rss(process.pid)
        return result
    finally:
        process.terminate()
        process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path, default=Path("/tmp/barque-performance.json"))
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--serve", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.port)
        return
    if not args.baseline:
        parser.error("--baseline is required")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        options = {"headless": True}
        if os.environ.get("BARQUE_TEST_CHROMIUM"):
            options["executable_path"] = os.environ["BARQUE_TEST_CHROMIUM"]
        browser = playwright.chromium.launch(**options)
        result = {
            "environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "browser": browser.version,
                "viewport": "1440x1000",
                "network": "40 ms latency, 10 Mibit/s",
                "cpu": "4x slowdown",
                "runs": args.runs,
                "subscriptions": 7,
            },
            "before": measure(args.baseline.resolve(), True, browser, args.runs),
            "after": measure(Path(__file__).resolve().parent.parent, False, browser, args.runs),
        }
        browser.close()
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(args.output)


if __name__ == "__main__":
    main()
