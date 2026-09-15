"""Research alerts: public bibliographic metadata, DOI dedup and explicit evidence."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import html, json, re, sqlite3, threading, time
import urllib.parse, urllib.request
from sync_bridge import atomic_json

TOPICS=[]
QUERIES=[]


def clean(value):
    return re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",str(value or "")))).strip()


def zotero_profile(database):
    from contextlib import closing
    path=Path(database).expanduser().resolve()
    with closing(sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=3)) as db:
        collections=[row[0] for row in db.execute("SELECT collectionName FROM collections")]
        rows=db.execute("SELECT d.itemID,f.fieldName,v.value FROM itemData d JOIN fields f ON f.fieldID=d.fieldID "
            "JOIN itemDataValues v ON v.valueID=d.valueID WHERE f.fieldName IN ('title','DOI') "
            "AND d.itemID NOT IN (SELECT itemID FROM deletedItems)").fetchall()
    items={}
    for ident,field,value in rows:items.setdefault(ident,{})[field]=value
    return {"topics":TOPICS,"queries":QUERIES,"zotero_collections":collections,
            "known_dois":sorted({v["DOI"].strip().lower() for v in items.values() if v.get("DOI")}),
            "library_items":len(items),"profile_updated":time.time()}


def parse_work(item):
    doi=str(item.get("DOI","")).strip().lower()
    if not doi.startswith("10.") or any(c.isspace() for c in doi):return None
    title=clean((item.get("title") or [""])[0])
    abstract=clean(item.get("abstract",""))[:10000]
    if not title:return None
    dates=[]
    for key in ("published-online","published-print","published","issued"):
        parts=(item.get(key) or {}).get("date-parts") or []
        try:
            if parts and len(parts[0])==3:dates.append(date(*parts[0]).isoformat())
        except (TypeError,ValueError):pass
    return {"doi":doi,"title":title,"abstract":abstract,"date":min(dates) if dates else "",
            "journal":clean((item.get("container-title") or [""])[0]),
            "url":"https://doi.org/"+urllib.parse.quote(doi,safe="/"),"source":"Crossref"}


def fetch_candidates(profile, now=None, opener=urllib.request.urlopen):
    today=date.fromtimestamp(now or time.time())
    since=(today-timedelta(days=45)).isoformat()
    found={};errors=[]
    for query in profile.get("queries",QUERIES)[:6]:
        params={"query.bibliographic":query,"filter":f"from-pub-date:{since},until-pub-date:{today.isoformat()},type:journal-article",
                "sort":"relevance","order":"desc","rows":50,
                "select":"DOI,title,abstract,container-title,published,published-online,published-print,issued"}
        request=urllib.request.Request("https://api.crossref.org/works?"+urllib.parse.urlencode(params),
            headers={"User-Agent":"ShizukaResearchWatch/0.2 (personal scholarly metadata reader)","Accept":"application/json"})
        try:
            with opener(request,timeout=25) as response:
                raw=response.read(4*1024*1024+1)
                if len(raw)>4*1024*1024:raise ValueError("Metadata response too large")
                items=json.loads(raw).get("message",{}).get("items",[])
            for item in items:
                work=parse_work(item)
                if work and work["date"] and since<=work["date"]<=today.isoformat():found[work["doi"]]=work
        except Exception as exc:errors.append(type(exc).__name__+": "+str(exc)[:180])
    return list(found.values()),errors


class ResearchWatch:
    def __init__(self, data_root):
        self.root=Path(data_root)
        self.profile_path=self.root/"research-profile.json"
        self.state_path=self.root/"research-watch.json"
        self.lock=threading.Lock()
        self.profile={"enabled":False,"check_hours":6,"topics":TOPICS,"queries":QUERIES,"known_dois":[]}
        self.state={"checked_at":0,"evaluated":{},"alerts":[],"errors":[]}
        for path,target in ((self.profile_path,self.profile),(self.state_path,self.state)):
            if path.exists():target.update(json.loads(path.read_text(encoding="utf-8-sig")))
        if self.state.get('assessment_revision',0)<2:
            # Revisit formerly excluded title-only candidates on the first upgraded launch.
            self.state.update(assessment_revision=2,checked_at=0)

    def due(self, now):
        return self.profile.get("enabled",True) and now-self.state.get("checked_at",0)>=max(1,float(self.profile.get("check_hours",6)))*3600

    def scan(self, evaluate, *, force=False, fetch=fetch_candidates):
        if not self.lock.acquire(blocking=False):return []
        try:
            now=time.time()
            if not force and not self.due(now):return []
            profile_error=[]
            if self.profile.get("zotero_database"):
                try:
                    fresh=zotero_profile(self.profile["zotero_database"])
                    # Refresh library exclusion metadata, retaining user-edited topics/queries.
                    self.profile.update({k:v for k,v in fresh.items() if k not in ("topics","queries")})
                    atomic_json(self.profile_path,self.profile)
                except Exception as exc:
                    profile_error=["Zotero 只读刷新失败，使用上次索引："+type(exc).__name__]
            works,errors=fetch(self.profile,now)
            errors=profile_error+errors
            known=set(self.profile.get("known_dois",[]))
            old=self.state.setdefault("evaluated",{})
            pending=[w for w in works if w["doi"] not in known and w["doi"] not in old]
            # Both abstract-backed results and relevant title-only leads are eligible.
            self.state["candidates"]=pending
            shortlist=sorted(pending,key=lambda w:w["date"],reverse=True)[:18]
            alerts=[]
            if shortlist:
                decisions=evaluate(shortlist,self.profile.get("topics",TOPICS))
                if not isinstance(decisions,list):raise ValueError("Invalid research assessment")
                by_doi={w["doi"]:w for w in shortlist}
                for decision in decisions:
                    if not isinstance(decision,dict):continue
                    doi=str(decision.get("doi","")).lower()
                    if doi not in by_doi:continue
                    work=by_doi[doi]
                    quote=clean(decision.get("evidence",""))
                    basis='abstract' if work.get('abstract') else 'title'
                    evidence_source=work.get('abstract') or work['title']
                    if (len(alerts)<3 and decision.get("important") is True and len(quote)>=(15 if basis=='abstract' else 4)
                            and len(quote.split())<=35 and quote.casefold() in evidence_source.casefold()
                            and decision.get("reason") and decision.get("summary")):
                        alerts.append({**work,"reason":str(decision["reason"])[:500],
                            "summary":str(decision["summary"])[:1000],"evidence":quote,
                            "evidence_basis":basis,"comment":str(decision.get('comment') or '')[:1200],
                            "notified":False,"discovered":now})
                    old[doi]=now
            existing={r["doi"] for r in self.state["alerts"]}
            for alert in alerts:
                if alert["doi"] not in existing:self.state["alerts"].append(alert);existing.add(alert["doi"])
            self.state.update(checked_at=now,errors=errors)
            atomic_json(self.state_path,self.state)
            return alerts
        finally:self.lock.release()

    def mark_notified(self, doi):
        with self.lock:
            for alert in self.state["alerts"]:
                if alert["doi"]==doi:alert["notified"]=True
            atomic_json(self.state_path,self.state)
