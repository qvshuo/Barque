"""Validate two built Docker images with disposable volumes and no external network.

python -m tests.docker_validation --before IMAGE --after IMAGE --output /tmp/docker.json
"""

import argparse
import json
import platform
import statistics
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from tests.fixtures import configuration


def docker(*args, source=None):
    result = subprocess.run(
        ["docker", *args], input=source, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def execute(container, source):
    return json.loads(docker("exec", "-i", container, "python", "-", source=source))


def request_script(password, operations=False, persisted=False):
    return f"""
import gzip, http.client, json, re
from http.cookies import SimpleCookie
from pathlib import Path

password = {password!r}
cookie_path = Path('/app/data/.validation-cookie')
cookie = cookie_path.read_text() if cookie_path.exists() else ''
checks = []
def request(path, method='GET', data=None, expected=200, headers=None, authenticated=True):
    connection = http.client.HTTPConnection('127.0.0.1', 8080, timeout=10)
    request_headers = {{'Accept-Encoding':'identity'}}
    if authenticated and cookie: request_headers['Cookie'] = cookie
    if method in {{'POST','PUT','PATCH','DELETE'}} and data is None: data = {{}}
    if data is not None: request_headers.update({{'Content-Type':'application/json','X-Barque-Request':'1'}})
    request_headers.update(headers or {{}})
    connection.request(method, path, None if data is None else json.dumps(data), request_headers)
    response = connection.getresponse()
    body = response.read()
    result = {{'status':response.status,'headers':dict((k.lower(),v) for k,v in response.getheaders()),'body':body}}
    connection.close()
    assert result['status'] == expected, (path, result['status'], body[:300])
    return result

def api(path, method='GET', data=None, expected=200, **kwargs):
    result = request('/api'+path, method, data, expected, **kwargs)
    return json.loads(result['body']) if result['body'] else None

assert api('/auth/session',authenticated=False) == {{'authenticated':False}}
request('/api/settings',expected=401,authenticated=False)
checks.append('authentication isolation')
if {persisted!r}:
    assert api('/auth/session') == {{'authenticated':True}}
    assert api('/configuration') == {configuration()!r}
    assert api('/dashboard')['category_groups'][0]['subscription_items'][0]['button_state']['status_kind'] == 'renewed'
    checks.append('existing session, settings, seven subscriptions, order and renewal marker persist')
else:
    api('/auth/login','POST',{{'password':'wrong-password'}},expected=401,authenticated=False)
    result = request('/api/auth/login','POST',{{'password':password}},authenticated=False)
    jar = SimpleCookie(); jar.load(result['headers']['set-cookie'])
    cookie = '; '.join(f'{{key}}={{value.value}}' for key,value in jar.items())
    cookie_path.write_text(cookie)
    assert api('/auth/session') == {{'authenticated':True}}
    checks.append('login and session cookie')
assert api('/configuration') == {configuration()!r}
assert api('/dashboard')['summary']['total_subscription_count'] == 7
request('/health')
for path in ['/', '/admin/', '/?page=subscriptions', '/?page=settings']:
    result = request(path)
    assert result['headers']['cache-control'] == 'no-store'
checks.append('production pages, health and dynamic no-store')
html = request('/')['body'].decode()
assets = list(dict.fromkeys(re.findall(r'(?:src|href)="(/assets/[^" ]+)"', html)))
assert assets
for path in assets:
    plain = request(path)
    assert 'immutable' in plain['headers']['cache-control']
    head = request(path, 'HEAD')
    assert not head['body']
    assert head['headers']['content-length'] == plain['headers']['content-length']
    request(path,expected=304,headers={{'If-None-Match':plain['headers']['etag']}})
    if '.js' in path or '.css' in path:
        packed = request(path,headers={{'Accept-Encoding':'gzip'}})
        assert packed['headers']['content-encoding'] == 'gzip'
        assert gzip.decompress(packed['body']) == plain['body']
        assert int(packed['headers']['content-length']) == len(packed['body'])
        head = request(path,'HEAD',headers={{'Accept-Encoding':'gzip'}})
        assert not head['body'] and head['headers']['content-length'] == packed['headers']['content-length']
        request(path,expected=304,headers={{'Accept-Encoding':'gzip','If-None-Match':packed['headers']['etag']}})
checks.append('asset integrity, gzip, HEAD and ETag/304 through Waitress')
if 'data-page=' in html:
    assert '我的订阅' in html and '订阅1' in html
    assert 'Bark 推送地址' in request('/?page=settings')['body'].decode()
    anonymous = request('/?page=settings',authenticated=False)['body'].decode()
    assert 'login-form' in anonymous and 'Bark 推送地址' not in anonymous
    packed = request('/',headers={{'Accept-Encoding':'gzip'}})
    assert gzip.decompress(packed['body']) == request('/')['body']
    css_path = next(path for path in assets if '.css' in path)
    plain = request(css_path)
    ranged = request(css_path,expected=206,headers={{'Range':'bytes=0-15','Accept-Encoding':'gzip'}})
    assert ranged['body'] == plain['body'][:16] and 'content-encoding' not in ranged['headers']
    for path in ['/assets/logo.webp','/favicon.ico']:
        assert 'content-encoding' not in request(path,headers={{'Accept-Encoding':'gzip'}})['headers']
    request('/',expected=406,headers={{'Accept-Encoding':'br, identity;q=0'}})
    checks.append('SSR, sensitive-page isolation, dynamic gzip, Range, binary and 406')
if {operations!r}:
    groups = api('/subscription-groups')
    original_revision = groups['revision']
    first = groups['categories'][0]['subscriptions'][0]
    first.update(name='Docker 验证订阅',billing_cycle='quarter',payment_date='2024-02-29',amount=12.34,currency='ZZZ',notify_enabled=False)
    saved = api('/subscription-groups','PUT',groups)
    assert saved['categories'][0]['subscriptions'][0]['currency'] == 'ZZZ'
    api('/subscription-groups','PUT',{{'categories':groups['categories'],'revision':original_revision}},expected=409)
    api('/configuration','PUT',{configuration()!r})
    item = api('/subscriptions','POST',{{'name':'容器新增','category':'分类1','billing_cycle':'week','payment_date':'2024-02-29','amount':23.45,'currency':'CNY','notify_enabled':False}},expected=201)
    item['amount'] = 24.55
    assert api('/subscriptions/'+item['id'],'PUT',item)['amount'] == 24.55
    api('/subscriptions/'+item['id'],'DELETE',expected=204)
    api('/order','PUT',{{'kind':'category','target':'分类1','direction':'backward'}},expected=204)
    api('/configuration','PUT',{configuration()!r})
    settings = api('/settings'); settings['timezone'] = 'UTC'
    assert api('/settings','PUT',settings)['timezone'] == 'UTC'
    api('/configuration','PUT',{configuration()!r})
    api('/test-notification','POST',{{'notify_url':'invalid'}},expected=400)
    dashboard = api('/dashboard'); first = dashboard['category_groups'][0]['subscription_items'][0]
    payload = dict(subscription_id=first['subscription_id'],payment_date=first['payment_date'],renewal_date=first['renewal_date'],renewed=True)
    api('/renewal-status','PUT',payload)
    assert api('/dashboard')['category_groups'][0]['subscription_items'][0]['button_state']['status_kind'] == 'renewed'
    payload['renewed'] = False; api('/renewal-status','PUT',payload)
    payload['renewed'] = True; api('/renewal-status','PUT',payload)
    assert api('/configuration') == {configuration()!r}
    checks.append('batch edit/conflict, CRUD, sorting, settings, import/export, invalid Bark, renewal and undo')
print(json.dumps({{'checks':checks,'subscription_count':7}},ensure_ascii=False))
"""


def memory(container):
    values = []
    for _ in range(5):
        result = execute(
            container,
            "import json; from pathlib import Path; print(json.dumps(int(next(line.split()[1] for line in Path('/proc/1/status').read_text().splitlines() if line.startswith('VmRSS:')))))",
        )
        values.append(result)
        time.sleep(0.1)
    return {"rss_kib_samples": values, "rss_kib_median": statistics.median(values)}


def wait_healthy(container):
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline:
        state = json.loads(docker("inspect", container))[0]["State"]
        if state.get("Health", {}).get("Status") == "healthy":
            return
        if not state["Running"]:
            raise RuntimeError(docker("logs", container))
        time.sleep(1)
    raise RuntimeError("Container did not pass the Dockerfile healthcheck")


def schema(container):
    return execute(
        container,
        """import json,sqlite3
with sqlite3.connect('/app/data/barque.sqlite3') as connection:
 print(json.dumps({'schema':connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name").fetchall(),'user_version':connection.execute('PRAGMA user_version').fetchone()[0],'integrity':connection.execute('PRAGMA integrity_check').fetchone()[0]}))
""",
    )


def validate(args):
    suffix = uuid4().hex[:10]
    names, volumes = [], []
    password = "validation-" + uuid4().hex
    result = {
        "environment": {
            "host": platform.node(),
            "architecture": platform.machine(),
            "docker": json.loads(docker("version", "--format", "{{json .Server}}"))["Version"],
            "network": "none; HTTP requests run on container loopback",
            "subscriptions": 7,
            "production_entrypoint": "python -m app.main; eight Waitress threads and scheduler enabled",
        },
        "images": {},
        "runtime": {},
    }
    original_name = None
    original_volume = None
    try:
        for label, image in [("before", args.before), ("after", args.after)]:
            info = json.loads(docker("image", "inspect", image))[0]
            result["images"][label] = {
                "tag": image,
                "id": info["Id"],
                "size_bytes": info["Size"],
                "architecture": info["Architecture"],
                "os": info["Os"],
                "user": info["Config"]["User"],
                "rootfs_layers": info["RootFS"]["Layers"],
            }
            volume, name = (
                f"barque-validation-{suffix}-{label}-data",
                f"barque-validation-{suffix}-{label}",
            )
            docker("volume", "create", volume)
            volumes.append(volume)
            seed = f"""from app.database import Database
from app.currencies import DEFAULT_CURRENCIES
from app.scheduler import today_in_timezone
from pathlib import Path
config = {configuration()!r}
database = Database(Path('/app/data'))
database.import_config(config)
today = today_in_timezone(config['settings']['timezone']).isoformat()
database.write_state('currency_catalog',{{'date':today,'currencies':DEFAULT_CURRENCIES}})
database.write_state('exchange_rates',{{'base':'CNY','date':today,'updated_at':today+'T09:00:00+08:00','rates':{{'CNY':1.0}}}})
"""
            docker(
                "run",
                "--rm",
                "-i",
                "--network",
                "none",
                "--mount",
                f"type=volume,src={volume},dst=/app/data",
                "--entrypoint",
                "python",
                image,
                "-",
                source=seed,
            )
            docker(
                "run",
                "-d",
                "--name",
                name,
                "--network",
                "none",
                "--env",
                f"BARQUE_PASSWORD={password}",
                "--mount",
                f"type=volume,src={volume},dst=/app/data",
                image,
            )
            names.append(name)
            wait_healthy(name)
            print(f"{label}: production healthy", flush=True)
            runtime = {"health": "healthy", "idle": memory(name)}
            runtime["checks"] = execute(name, request_script(password, operations=True))
            runtime["operations"] = memory(name)
            runtime["schema"] = schema(name)
            assert runtime["schema"]["integrity"] == "ok"
            runtime["runtime_tools"] = json.loads(
                docker(
                    "exec",
                    name,
                    "python",
                    "-c",
                    "import json,os,shutil; print(json.dumps({'uid':os.getuid(),'node':shutil.which('node'),'npm':shutil.which('npm')}))",
                )
            )
            assert runtime["runtime_tools"]["uid"] == 10001
            assert (
                runtime["runtime_tools"]["node"] is None and runtime["runtime_tools"]["npm"] is None
            )
            docker("restart", name)
            wait_healthy(name)
            runtime["restart"] = execute(name, request_script(password, persisted=True))
            result["runtime"][label] = runtime
            print(f"{label}: HTTP, operations and restart passed", flush=True)
            if label == "before":
                original_name, original_volume = name, volume
        docker("stop", original_name)
        upgraded = f"barque-validation-{suffix}-upgrade"
        docker(
            "run",
            "-d",
            "--name",
            upgraded,
            "--network",
            "none",
            "--env",
            f"BARQUE_PASSWORD={password}",
            "--mount",
            f"type=volume,src={original_volume},dst=/app/data",
            args.after,
        )
        names.append(upgraded)
        wait_healthy(upgraded)
        result["upgrade"] = execute(upgraded, request_script(password, persisted=True))
        result["upgrade"]["schema_unchanged"] = (
            schema(upgraded) == result["runtime"]["before"]["schema"]
        )
        assert result["upgrade"]["schema_unchanged"]
        result["success"] = True
    finally:
        for name in reversed(names):
            subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)
        for volume in volumes:
            subprocess.run(["docker", "volume", "rm", volume], check=False, capture_output=True)
    result["cleanup"] = {"containers_removed": names, "volumes_removed": volumes}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(args.output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--output", type=Path, required=True)
    validate(parser.parse_args())


if __name__ == "__main__":
    main()
