# -*- coding: utf-8 -*-
"""全 sources URL の到達性を確認する（HEAD→失敗時GET、最大2回リトライ）"""
import subprocess, sys, concurrent.futures as cf

sys.path.insert(0, '/home/user/CName-1/data')
from figures_data import FIGURES

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def probe(url):
    for args in (["-I"], ["-r", "0-0"]):
        try:
            r = subprocess.run(
                ["curl", "-sS", "-o", "/dev/null", "-L", "--max-time", "25",
                 "-A", UA, "-w", "%{http_code}"] + args + [url],
                capture_output=True, text=True, timeout=40)
            code = r.stdout.strip()[-3:]
            if code.isdigit() and 200 <= int(code) < 400:
                return url, code, "OK"
        except Exception as e:
            last = str(e)[:60]
    return url, code if code.isdigit() else "ERR", "FAIL"


pairs = []
for f in FIGURES:
    for u in f["sources"]:
        pairs.append((f["id"], u))
    for k in ("quote_alt_source",):
        if f.get(k):
            pairs.append((f["id"], f[k]))

print("checking %d URLs..." % len(pairs))
results = {}
with cf.ThreadPoolExecutor(max_workers=10) as ex:
    for url, code, st in ex.map(lambda p: probe(p[1]), pairs):
        results[url] = (code, st)

bad = []
for fid, u in pairs:
    code, st = results[u]
    if st != "OK":
        bad.append((fid, u, code))

print("\nOK: %d / %d" % (len(pairs) - len(bad), len(pairs)))
if bad:
    print("\n--- FAILED ---")
    for fid, u, code in bad:
        print("  [%s] %s  %s" % (code, fid, u))
