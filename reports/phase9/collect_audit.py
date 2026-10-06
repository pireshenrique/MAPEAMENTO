"""Fase 9: coleta real (somente News API) com auditoria. Não altera radar/ nem config/.
Usa as mesmas funções do pipeline; grava requisições, respostas brutas e resultado em reports/phase9/."""
import json, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, ".")
from radar.bootstrap import build_context
from radar.collectors.newsapi import NewsApiCollector
from radar.db.engine import session_scope
from radar.pipeline.runner import run_collection
from radar.settings import EnvSettings, load_config

OUT = Path("reports/phase9"); OUT.mkdir(parents=True, exist_ok=True)
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
db = Path(tempfile.gettempdir()) / "phase9_audit.db"
db.unlink(missing_ok=True)

env = EnvSettings(_env_file=None, database_url=f"sqlite:///{db}", ai_api_key="")
cfg = load_config("config", env=env)
assert env.news_api_key, "NEWS_API_KEY ausente do ambiente"
assert not env.ai_api_key

requests_log = []

def on_response(resp: httpx.Response):
    resp.read()
    try:
        body = resp.json()
    except ValueError:
        body = {}
    p = dict(resp.request.url.params)
    requests_log.append({"q": p.get("q"), "from": p.get("from"), "to": p.get("to"), "language": p.get("language"),
                         "pageSize": p.get("pageSize"), "page": p.get("page"), "sortBy": p.get("sortBy"),
                         "searchIn": p.get("searchIn"), "http": resp.status_code, "status": body.get("status"),
                         "code": body.get("code"), "message": body.get("message"),
                         "totalResults": body.get("totalResults"), "returned": len(body.get("articles", []) or [])})
    if resp.status_code != 200:
        raise RuntimeError(f"News API respondeu {resp.status_code}: {body.get('code')} {body.get('message')}")

client = httpx.Client(timeout=cfg.settings.collection.request_timeout_seconds, event_hooks={"response": [on_response]})
inner = NewsApiCollector(env.news_api_key, cfg.settings.collection, client=client)
raw_by_comp = {}

class Recording:
    name = inner.name
    def fetch(self, competitor, since, until=None):
        raws = inner.fetch(competitor, since, until)
        raw_by_comp[competitor.name] = [r.model_dump(mode="json") for r in raws]
        return raws

ctx = build_context(cfg)
now = datetime.now(timezone.utc)
try:
    with session_scope(ctx.session_factory) as s:
        stats = run_collection(s, [Recording()], cfg, now=now, days=DAYS)
except Exception as e:
    print("ERRO:", type(e).__name__, e); (OUT / "requests.json").write_text(json.dumps(requests_log, indent=1)); raise
(OUT / "requests.json").write_text(json.dumps(requests_log, ensure_ascii=False, indent=1))
(OUT / "raw_articles.json").write_text(json.dumps(raw_by_comp, ensure_ascii=False, indent=1))
(OUT / "meta.json").write_text(json.dumps({"now": now.isoformat(), "days": DAYS, "db": str(db), "errors": stats.errors,
    "found": stats.found, "new": stats.new, "duplicates": stats.duplicates, "possible": stats.possible_duplicates,
    "discarded": dict(stats.discarded)}, indent=1))
print("requisições:", len(requests_log), "| found", stats.found, "new", stats.new, "dups", stats.duplicates,
      "possible", stats.possible_duplicates, "discarded", dict(stats.discarded), "erros", stats.errors)
for r in requests_log: print(r["http"], r["totalResults"], r["returned"], (r["q"] or "")[:90])
