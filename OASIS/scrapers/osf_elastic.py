# OSF Elastic (weblike) search implementation (uses share.osf elastic endpoint)
import re
import pandas as pd
import httpx

from ..utils import safe_request
from ..config import OSF_ELASTIC_URL, POLITENESS_CONFIG, OSF_PROVIDERS

class ElasticPreprints:
    def __init__(self, provider="psyarxiv", politeness="Normal"):
        self.provider = provider
        self.client = httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, timeout=30.0)
        self.abort_flag = False
        self.politeness = politeness

    def normalize_query(self, query: str) -> str:
        if not query:
            return query
        query = query.replace("|", " OR ").replace("&", " AND ")
        query = re.sub(r"\band\b", "AND", query, flags=re.IGNORECASE)
        query = re.sub(r"\bor\b", "OR", query, flags=re.IGNORECASE)
        query = re.sub(r"\bnot\b", "NOT", query, flags=re.IGNORECASE)
        query = re.sub(r"\s+", " ", query).strip()
        return query

    def run(self, query, progress_callback=None):
        rows = []
        size = 200
        start = 0

        query = self.normalize_query(query)

        politeness_delay = POLITENESS_CONFIG.get(self.politeness, POLITENESS_CONFIG["Normal"])["osf_delay"]
        retries = POLITENESS_CONFIG.get(self.politeness, POLITENESS_CONFIG["Normal"])["retries"]

        while True:
            if self.abort_flag:
                break

            payload = {
                "query": {
                    "bool": {
                        "must": {
                            "query_string": {
                                "query": query,
                                "fields": ["*"],
                                "lenient": True
                            }
                        },
                        "filter": [
                            {"terms": {"sources": [OSF_PROVIDERS.get(self.provider, self.provider)]}},
                            {"terms": {"types": ["preprint"]}}
                        ]
                    }
                },
                "from": start,
                "size": size
            }

            res = safe_request("POST", OSF_ELASTIC_URL, client=self.client, json=payload, retries=retries, backoff_factor=2, politeness_delay=politeness_delay)
            data = res.json()
            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                break

            for h in hits:
                if self.abort_flag:
                    break
                s = h.get("_source", {})
                contributors = []
                lists_contribs = s.get("lists", {}).get("contributors", []) if isinstance(s.get("lists", {}).get("contributors", []), list) else []
                for c in lists_contribs:
                    name = c.get("name")
                    if name:
                        contributors.append(name)
                rows.append({
                    "ID": s.get("id", ""),
                    "Title": s.get("title", ""),
                    "Abstract": s.get("description", ""),
                    "Date Published": s.get("date_published", ""),
                    "Tags": ",".join(s.get("tags", []) if isinstance(s.get("tags", []), list) else []),
                    "DOI": s.get("doi", ""),
                    "URL": s.get("links", {}).get("html", ""),
                    "Contributors": ", ".join(contributors),
                    "Provider": self.provider,
                })

            if progress_callback:
                progress_callback.emit(f"Fetched {len(rows)} results so far...")

            start += size
            if len(hits) < size:
                break

        df = pd.DataFrame(rows)
        if "ID" not in df.columns:
            df["ID"] = ""
        return df.drop_duplicates(subset="ID")
