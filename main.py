from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from core.servers import load_server_lines, parse_server, check_server

app = FastAPI(title="MUUN RECOVERY API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {
        "ok": True,
        "service": "MUUN RECOVERY API",
        "endpoints": ["/api/servers", "/api/servers/check?limit=10"],
    }


@app.get("/api/servers")
def list_servers():
    lines = load_server_lines()
    return {"total": len(lines), "servers": lines}


@app.get("/api/servers/check")
def check_servers(limit: int = Query(10, ge=1, le=25)):
    lines = load_server_lines()[:limit]
    parsed = []
    for line in lines:
        try:
            p = parse_server(line)
            if p:
                parsed.append((line, p))
        except ValueError:
            continue

    def _probe(item):
        line, (host, port, use_ssl) = item
        status = check_server(host, port, use_ssl)
        return {"server": line, "host": host, "port": port, "ssl": use_ssl, **status}

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(_probe, parsed))

    results.sort(key=lambda r: (not r["ok"], r["latency"] if r["latency"] is not None else 10**6))
    online_count = sum(1 for r in results if r["ok"])
    return {"checked": len(results), "online": online_count, "results": results}
