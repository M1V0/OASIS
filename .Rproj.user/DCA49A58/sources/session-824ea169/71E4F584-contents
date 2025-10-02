import httpx
import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import webbrowser
import urllib.parse
import re
import threading

# ----------------- Constants -----------------
PAGE_SIZE = 100
API_BASE = "https://api.osf.io/v2/preprints/"
ELASTIC_URL = "https://share.osf.io/api/v2/search/creativeworks/_search"

# Known OSF providers
OSF_PROVIDERS = {
    "psyarxiv": "PsyArXiv",
    "socarxiv": "SocArXiv",
    "engrxiv": "engrXiv",
    "lawarxiv": "LawArXiv",
    "medrxiv": "MedArXiv",
    "ecsarxiv": "ECSarXiv",
    "thesiscommons": "Thesis Commons"
}

# ----------------- Global Abort Flag -----------------
abort_flag = False

def set_abort(event=None):
    global abort_flag
    abort_flag = True
    feedback_box.insert(tk.END, "⚠️ Aborting requested by user...\n")
    feedback_box.see(tk.END)

# ----------------- OSF API Wrapper -----------------
class OSFPreprints:
    def __init__(self, provider="psyarxiv"):
        self.provider = provider
        self.API = API_BASE
        self.client = httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, timeout=30.0)
        self.results = []

    def build_params(self, query=None, page=1):
        params = {
            "filter[provider]": self.provider,
            "page[size]": PAGE_SIZE,
            "page[number]": page,
        }
        if query:
            params["filter[title][icontains]"] = str(query).strip()
        return params

    def build_url(self, query=None, page=1):
        params = self.build_params(query=query, page=page)
        return self.API + "?" + urllib.parse.urlencode(params, doseq=True)

    def fetch_page(self, query, page=1):
        if abort_flag:
            return None
        params = self.build_params(query=query, page=page)
        res = self.client.get(self.API, params=params)
        res.raise_for_status()
        return res.json()

    def parse_response(self, data):
        rows = []
        for item in data.get("data", []):
            if abort_flag:
                break
            attrs = item.get("attributes", {}) or {}
            title = attrs.get("title", "") or ""
            desc = attrs.get("description", "") or ""
            date = attrs.get("date_published", "") or ""
            tags = attrs.get("tags", []) or []
            doi = attrs.get("doi", "") or ""
            url = item.get("links", {}).get("html", "") or ""
            _id = item.get("id", "") or ""

            rows.append({
                "ID": _id,
                "Title": title,
                "Abstract": desc,
                "Date Published": date,
                "Tags": ",".join([t if isinstance(t, str) else str(t) for t in tags]),
                "DOI": doi,
                "URL": url,
                "Contributors": "",
                "Provider": self.provider,
            })
        return rows

    def run(self, query):
        self.results = []
        page = 1
        while True:
            if abort_flag:
                break
            data = self.fetch_page(query, page)
            if data is None:
                break
            for row in self.parse_response(data):
                if abort_flag:
                    break
                self.results.append(row)
            links = data.get("links", {}) or {}
            if not links.get("next") or abort_flag:
                break
            page += 1
        df = pd.DataFrame(self.results)
        if "ID" not in df.columns:
            df["ID"] = ""
        return df.drop_duplicates(subset="ID")

# ----------------- ElasticSearch Wrapper -----------------
class ElasticPreprints:
    def __init__(self, provider="psyarxiv"):
        self.provider = provider
        self.client = httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, timeout=30.0)

    def run(self, query):
        global abort_flag
        rows = []
        size = 200
        start = 0

        while True:
            if abort_flag:
                break

            payload = {
                "query": {
                    "bool": {
                        "must": {
                            "query_string": {"query": query}
                        },
                        "filter": [
                            {"terms": {"sources": [OSF_PROVIDERS[self.provider]]}}
                        ]
                    }
                },
                "from": start,
                "size": size
            }

            res = self.client.post(ELASTIC_URL, json=payload)
            res.raise_for_status()
            data = res.json()
            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                break

            for h in hits:
                if abort_flag:
                    break
                s = h.get("_source", {})

                # URL
                url = ""
                links = s.get("links", {})
                if isinstance(links, dict):
                    url = links.get("html", "")

                # Contributors: prefer the "lists.contributors" structure
                contributors = []
                lists_contribs = s.get("lists", {}).get("contributors", [])
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
                    "URL": url,
                    "Contributors": ", ".join(contributors),
                    "Provider": self.provider,
                })

            start += size  # fetch next batch

            # Stop if we've fetched fewer than requested (last page)
            if len(hits) < size:
                break

        df = pd.DataFrame(rows)
        if "ID" not in df.columns:
            df["ID"] = ""
        return df.drop_duplicates(subset="ID")



# ----------------- GUI functions -----------------
def run_scraper():
    global abort_flag
    abort_flag = False
    base_filename = filename_entry.get().strip() or "Data_Preprints"
    feedback_box.delete(1.0, tk.END)
    progress_bar['value'] = 0

    query = query_text.get("1.0", tk.END).strip()
    provider = provider_var.get()
    search_mode = search_mode_var.get()

    if not query:
        messagebox.showerror("Error", "Enter a query first.")
        return

    try:
        if search_mode == "api":
            client = OSFPreprints(provider=provider)
        else:
            client = ElasticPreprints(provider=provider)

        df = client.run(query)

        if abort_flag:
            feedback_box.insert(tk.END, "Scraping aborted by user.\n")
            feedback_box.see(tk.END)
            return
        if df.empty:
            messagebox.showwarning("No Results", "No preprints found.")
            feedback_box.insert(tk.END, "No preprints found.\n")
            return

        filename = f"{base_filename}_{provider}_{search_mode}.csv"
        df.to_csv(filename, index=False)
        msg = f"Scraping complete! {len(df)} unique preprints saved to {filename}"
        feedback_box.insert(tk.END, msg + "\n")
        feedback_box.see(tk.END)
        messagebox.showinfo("Done", msg)
    except Exception as e:
        feedback_box.insert(tk.END, f"Error: {e}\n")
        feedback_box.see(tk.END)
        messagebox.showerror("Error", str(e))

def threaded_run_scraper():
    t = threading.Thread(target=run_scraper, daemon=True)
    t.start()

# ----------------- GUI Layout -----------------
root = tk.Tk()
root.title("OSF Scraper with ElasticSearch Option")

root.bind("<Escape>", set_abort)

# Query entry
query_frame = tk.Frame(root)
query_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
tk.Label(query_frame, text="Enter query (keywords, Boolean, wildcards if ElasticSearch):").pack(anchor="w")
query_text = scrolledtext.ScrolledText(query_frame, height=3, width=100)
query_text.pack(padx=5, pady=5)

# Options frame
options_frame = tk.Frame(root)
options_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=5)

tk.Label(options_frame, text="Base filename:").grid(row=0, column=0, padx=5)
filename_entry = tk.Entry(options_frame, width=25)
filename_entry.insert(0, "Data_Preprints")
filename_entry.grid(row=0, column=1, padx=5)

tk.Label(options_frame, text="Provider:").grid(row=0, column=2, padx=5)
provider_var = tk.StringVar(value="psyarxiv")
provider_menu = ttk.Combobox(options_frame, textvariable=provider_var, values=list(OSF_PROVIDERS.keys()), state="readonly")
provider_menu.grid(row=0, column=3, padx=5)

# Search mode radio buttons
search_mode_var = tk.StringVar(value="api")
tk.Label(options_frame, text="Search Mode:").grid(row=0, column=4, padx=5)
tk.Radiobutton(options_frame, text="OSF API (Title only)", variable=search_mode_var, value="api").grid(row=0, column=5, padx=5)
tk.Radiobutton(options_frame, text="ElasticSearch (Title+Abstract)", variable=search_mode_var, value="elastic").grid(row=0, column=6, padx=5)

tk.Button(options_frame, text="Run Scraper", command=threaded_run_scraper).grid(row=0, column=7, padx=5)
tk.Button(options_frame, text="Abort (Esc)", command=set_abort).grid(row=0, column=8, padx=5)

# Feedback and progress
feedback_box = scrolledtext.ScrolledText(root, height=12, width=100)
feedback_box.grid(row=2, column=0, padx=5, pady=5, sticky="nsew")
progress_bar = ttk.Progressbar(root, orient="horizontal", mode="determinate")
progress_bar.grid(row=3, column=0, padx=5, pady=5, sticky="ew")

root.mainloop()
