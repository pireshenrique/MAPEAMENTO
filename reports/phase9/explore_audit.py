"""Buscas exploratórias amplas (somente registro). Passa cada artigo pelo normalize/validate/match ATUAIS."""
import json, os, sys
from datetime import datetime, timezone
import httpx
sys.path.insert(0, ".")
from radar.pipeline.match import match_all
from radar.pipeline.normalize import normalize
from radar.pipeline.validate import validate
from radar.domain.models import RawArticle
from radar.collectors.newsapi import _parse_dt
from radar.settings import EnvSettings, load_config

cfg = load_config("config", env=EnvSettings(_env_file=None))
now = datetime.now(timezone.utc)
H = {"X-Api-Key": os.environ["NEWS_API_KEY"]}
Q = [  # (rótulo, q, language)
 ("Deca","\"Deca\"","pt"),("Deca","\"Deca\" AND (banheiro OR louça OR metais OR sanitário)","pt"),
 ("Deca","\"Deca\" Dexco","pt"),
 ("Roca","\"Roca\"","pt"),("Roca","\"Roca\" AND (banheiro OR louças OR sanitários)","pt"),
 ("Celite","Celite","pt"),("Docol","Docol","pt"),
 ("Tigre","\"Tigre\"","pt"),("Tigre","\"Tigre\" AND (tubos OR conexões OR hidráulica OR construção)","pt"),
 ("Kohler","Kohler","pt"),("Dexco","Dexco","pt"),("Dexco","Duratex","pt"),
 ("setor","\"louças sanitárias\"","pt"),("setor","\"metais sanitários\"","pt"),
 ("setor","\"material de construção\" AND (Deca OR Docol OR Roca OR Tigre OR Dexco OR Celite OR Kohler)","pt"),
 ("sem-idioma","Docol","")," ".join([]) and None,
] 
Q = [q for q in Q if q]
Q += [("sem-idioma","Dexco",""),("sem-idioma","Kohler bathroom OR Kohler Brasil",""),("sem-idioma","Celite","")]
out, log = [], []
for label, q, lang in Q:
    p = {"q": q, "sortBy": "publishedAt", "pageSize": 30, "searchIn": "title,description,content"}
    if lang: p["language"] = lang
    r = httpx.get("https://newsapi.org/v2/everything", params=p, headers=H, timeout=25)
    b = r.json()
    if r.status_code != 200:
        print("ERRO", r.status_code, b.get("code"), b.get("message")); log.append({"q": q, "http": r.status_code, "code": b.get("code")}); break
    arts = b.get("articles", [])
    log.append({"label": label, "q": q, "lang": lang, "http": 200, "totalResults": b.get("totalResults"), "returned": len(arts)})
    print(r.status_code, f"total={b.get('totalResults')}", f"ret={len(arts)}", label, q[:70])
    for a in arts:
        raw = RawArticle(source_collector="newsapi", title=a.get("title"), description=a.get("description"), url=a.get("url"),
            source_name=(a.get("source") or {}).get("name"), published_at=_parse_dt(a.get("publishedAt")), content=a.get("content"))
        n = normalize(raw, now)
        reason = validate(n, now, cfg.settings.validation, cfg.settings.collection)
        ms = [] if reason else match_all(n, cfg.competitors, cfg.settings.matching)
        out.append({"label": label, "q": q, "lang": lang, "title": n.title, "source": n.source_name, "domain": n.source_domain,
                    "published_at": a.get("publishedAt"), "url": n.url, "desc": (n.description or "")[:300], "invalid": reason,
                    "matches": [{"c": m.competitor, "conf": round(m.confidence, 2), "ev": m.evidence} for m in ms]})
json.dump(out, open("reports/phase9/explore.json", "w"), ensure_ascii=False, indent=1)
json.dump(log, open("reports/phase9/explore_requests.json", "w"), ensure_ascii=False, indent=1)
print("artigos exploratórios:", len(out), "| requisições:", len(log))
