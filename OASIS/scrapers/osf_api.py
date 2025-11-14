# OSF API preprint search (paging over API)
import time
import pandas as pd
import httpx

from ..utils import safe_request
from ..config import OSF_API_BASE, OSF_PAGE_SIZE, POLITENESS_CONFIG

class OSFPreprints:
    def __init__(self, provider="psyarxiv", politeness="Normal"):
        self.provider = provider
        self.API = OSF_API_BASE
        self.client = httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, timeout=30.0)
        self.results = []
        self.abort_flag = False
        self.politeness = politeness

    def build_params(self, query=None, page=1):
        params = {
            "filter[provider]": self.provider,
            "page[size]": OSF_PAGE_SIZE,
            "page[number]": page,
        }
        if query:
            params["filter[title][icontains]"] = str(query).strip()
        return params

    def fetch_page(self, query, page=1):
        if self.abort_flag:
            return None
        params = self.build_params(query=query, page=page)
        politeness_delay = POLITENESS_CONFIG.get(self.politeness, POLITENESS_CONFIG["Normal"])["osf_delay"]
        retries = POLITENESS_CONFIG.get(self.politeness, POLITENESS_CONFIG["Normal"])["retries"]

        res = safe_request("GET", self.API, client=self.client, params=params, retries=retries, backoff_factor=2, politeness_delay=politeness_delay)
        return res.json()

    def run(self, query, progress_callback=None):
        self.results = []
        page = 1
        while True:
            if self.abort_flag:
                break
            data = self.fetch_page(query, page)
            if data is None:
                break

            for item in data.get("data", []):
                if self.abort_flag:
                    break
                attrs = item.get("attributes", {}) or {}
                tags = attrs.get("tags", []) if isinstance(attrs.get("tags", []), list) else []
                self.results.append({
                    "ID": item.get("id", ""),
                    "Title": attrs.get("title", "") or "",
                    "Abstract": attrs.get("description", "") or "",
                    "Date Published": attrs.get("date_published", "") or "",
                    "Tags": ",".join([t if isinstance(t, str) else str(t) for t in tags]),
                    "DOI": attrs.get("doi", "") or "",
                    "URL": item.get("links", {}).get("html", "") or "",
                    "Contributors": "",
                    "Provider": self.provider,
                })

            if progress_callback:
                progress_callback.emit(f"Fetched page {page}, {len(self.results)} results so far...")
            links = data.get("links", {}) or {}
            if not links.get("next") or self.abort_flag:
                break
            page += 1

        df = pd.DataFrame(self.results)
        if "ID" not in df.columns:
            df["ID"] = ""
        return df.drop_duplicates(subset="ID")
