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

            # Contributors
            contributors = []
            try:
                rels = item.get("relationships", {}) or {}
                if "contributors" in rels and "links" in rels["contributors"]:
                    contrib_url = rels["contributors"]["links"]["related"]["href"]
                    if contrib_url:
                        contrib_resp = self.client.get(contrib_url)
                        if contrib_resp.status_code == 200:
                            contrib_data = contrib_resp.json().get("data", [])
                            for c in contrib_data:
                                if abort_flag:
                                    break
                                name = None
                                if "embeds" in c and "users" in c["embeds"]:
                                    u = c["embeds"]["users"].get("data", {})
                                    if isinstance(u, dict):
                                        name = u.get("attributes", {}).get("full_name")
                                if not name:
                                    name = c.get("attributes", {}).get("full_name") if isinstance(c.get("attributes", {}), dict) else None
                                if name:
                                    contributors.append(name)
            except Exception:
                pass

            rows.append({
                "ID": _id,
                "Title": title,
                "Abstract": desc,
                "Date Published": date,
                "Tags": ",".join([t if isinstance(t, str) else str(t) for t in tags]),
                "DOI": doi,
                "URL": url,
                "Contributors": ", ".join(contributors)
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

# ----------------- Boolean query parsing -----------------
def tokenize(query):
    return re.findall(r'\"[^\"]+\"|\(|\)|AND|OR|[^\s()]+', query, flags=re.IGNORECASE)

def parse_tokens(tokens):
    idx = 0
    n = len(tokens)
    def consume():
        nonlocal idx
        t = tokens[idx]
        idx += 1
        return t
    def parse_factor():
        nonlocal idx
        if idx >= n:
            raise ValueError("Unexpected end of query")
        t = tokens[idx]
        if t == '(':
            consume()
            node = parse_expr()
            if idx >= n or tokens[idx] != ')':
                raise ValueError("Unmatched '(' in query")
            consume()
            return node
        else:
            token = consume()
            if token.startswith('"') and token.endswith('"'):
                return ('TERM', token[1:-1])
            else:
                return ('TERM', token)
    def parse_term():
        node = parse_factor()
        while idx < n and tokens[idx].upper() == 'AND':
            consume()
            right = parse_factor()
            if node[0] == 'AND':
                node[1].append(right)
            else:
                node = ('AND', [node, right])
        return node
    def parse_expr():
        node = parse_term()
        while idx < n and tokens[idx].upper() == 'OR':
            consume()
            right = parse_term()
            if node[0] == 'OR':
                node[1].append(right)
            else:
                node = ('OR', [node, right])
        return node
    ast = parse_expr()
    if idx != n:
        raise ValueError("Unexpected tokens after parsing")
    return ast

def ast_to_conjunctions(node):
    if node[0] == 'TERM':
        return [[node[1]]]
    if node[0] == 'OR':
        out = []
        for child in node[1]:
            out.extend(ast_to_conjunctions(child))
        return out
    if node[0] == 'AND':
        lists = [ast_to_conjunctions(child) for child in node[1]]
        result = lists[0]
        for nxt in lists[1:]:
            new = []
            for a in result:
                for b in nxt:
                    new.append(a + b)
            result = new
        return result
    raise ValueError("Unknown AST node")

def choose_seed_term(conj):
    """Pick the longest term as seed, but strip '*' before sending to API."""
    cleaned = [(t, len(t.replace('*',''))) for t in conj]
    chosen = max(cleaned, key=lambda x: x[1])[0]
    return chosen.replace('*', '')  # remove wildcards for API fetch

def filter_df_for_conjunction(df, conj):
    if df.empty:
        return df
    mask_all = pd.Series([True] * len(df), index=df.index)
    for term in conj:
        term = str(term)
        if '*' in term:
            pieces = [re.escape(p) for p in term.split('*')]
            pattern = '.*'.join(pieces)
            term_mask = df['Title'].str.contains(pattern, case=False, na=False, regex=True) | \
                        df['Abstract'].str.contains(pattern, case=False, na=False, regex=True)
        else:
            esc = re.escape(term)
            term_mask = df['Title'].str.contains(esc, case=False, na=False, regex=True) | \
                        df['Abstract'].str.contains(esc, case=False, na=False, regex=True)
        mask_all &= term_mask
        if not mask_all.any():
            return df.iloc[0:0]
    return df[mask_all]

def keep_latest_versions(df):
    if df.empty or "ID" not in df.columns:
        return df
    def split_id(id_str):
        m = re.match(r"^(.*)_v(\d+)$", id_str)
        if m:
            return m.group(1), int(m.group(2))
        else:
            return id_str, 0
    df[['base_id', 'version']] = df['ID'].apply(lambda x: pd.Series(split_id(x)))
    idx = df.groupby('base_id')['version'].idxmax()
    df_latest = df.loc[idx].drop(columns=['base_id', 'version']).reset_index(drop=True)
    return df_latest

def evaluate_boolean_query(query, feedback_box=None, progress_bar=None):
    tokens = tokenize(query)
    ast = parse_tokens(tokens)
    conjunctions = ast_to_conjunctions(ast)
    client = OSFPreprints(provider="psyarxiv")
    all_parts = []
    total = len(conjunctions)
    if feedback_box:
        feedback_box.insert(tk.END, f"Expanded to {total} conjunction(s): {conjunctions}\n")
        feedback_box.see(tk.END)
    for i, conj in enumerate(conjunctions, start=1):
        if abort_flag:
            if feedback_box:
                feedback_box.insert(tk.END, "Aborted by user.\n")
                feedback_box.see(tk.END)
            break
        if feedback_box:
            feedback_box.insert(tk.END, f"-- Conjunction {i}/{total}: {conj}\n")
            feedback_box.see(tk.END)
        seed = choose_seed_term(conj)
        if feedback_box:
            feedback_box.insert(tk.END, f"   Using seed '{seed}' for API fetch (then local filter)\n")
            feedback_box.see(tk.END)
        df_seed = client.run(seed)
        df_filtered = filter_df_for_conjunction(df_seed, conj)
        all_parts.append(df_filtered)
        if progress_bar:
            progress_bar['value'] = min(100, int(100 * (i / total)))
            progress_bar.update()

    if all_parts:
        result_df = pd.concat(all_parts, ignore_index=True).drop_duplicates(subset="ID")
    else:
        result_df = pd.DataFrame(columns=["ID", "Title", "Abstract", "Date Published", "Tags", "DOI", "URL", "Contributors"])
    result_df = keep_latest_versions(result_df)
    return result_df, conjunctions

def build_preview_urls_from_query(query):
    tokens = tokenize(query)
    ast = parse_tokens(tokens)
    conjunctions = ast_to_conjunctions(ast)
    client = OSFPreprints()
    urls = []
    for conj in conjunctions:
        seed = choose_seed_term(conj)  # already strips '*'
        urls.append((conj, client.build_url(query=seed, page=1)))
    return urls

# ----------------- GUI functions -----------------
def run_scraper():
    global abort_flag
    abort_flag = False
    base_filename = filename_entry.get().strip() or "Data_PsyArXiv"
    feedback_box.delete(1.0, tk.END)
    progress_bar['value'] = 0

    query = query_text.get("1.0", tk.END).strip()
    if not query:
        messagebox.showerror("Error", "Enter a Boolean query first.")
        return

    try:
        df, conj = evaluate_boolean_query(query, feedback_box, progress_bar)
        if abort_flag:
            feedback_box.insert(tk.END, "Scraping aborted by user.\n")
            feedback_box.see(tk.END)
            return
        if df.empty:
            messagebox.showwarning("No Results", "No preprints found (after local filtering).")
            feedback_box.insert(tk.END, "No preprints found.\n")
            return
        filename = f"{base_filename}.csv"
        df.to_csv(filename, index=False)
        msg = f"Scraping complete! {len(df)} unique preprints (latest versions only) saved to {filename}"
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

def preview_url():
    query = query_text.get("1.0", tk.END).strip()
    if not query:
        messagebox.showwarning("Preview URL", "Enter a Boolean query first.")
        return
    try:
        urls = build_preview_urls_from_query(query)
    except Exception as e:
        messagebox.showerror("Error parsing query", str(e))
        return

    popup = tk.Toplevel(root)
    popup.title("Preview PsyArXiv API URLs (per conjunction)")
    tk.Label(popup, text="These seed API calls will be executed; each will then be filtered locally to satisfy the full conjunction:").pack(pady=5)
    url_box = scrolledtext.ScrolledText(popup, width=120, height=10)
    url_box.pack(padx=5, pady=5)
    for combined, u in urls:
        url_box.insert(tk.END, f"Conjunction terms: {combined}\nSeed API call: {u}\n\n")
    url_box.configure(state="disabled")

    def visit_first():
        if urls:
            webbrowser.open(urls[0][1])

    btn_frame = tk.Frame(popup)
    btn_frame.pack(pady=5)
    tk.Button(btn_frame, text="Visit First Seed URL", command=visit_first).pack(side="left", padx=5)
    tk.Button(btn_frame, text="Close", command=popup.destroy).pack(side="left", padx=5)

# ----------------- GUI Layout -----------------
root = tk.Tk()
root.title("PsyArXiv Boolean Scraper (with Abort & Latest Version)")

root.bind("<Escape>", set_abort)

# Query entry
query_frame = tk.Frame(root)
query_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
tk.Label(query_frame, text='Enter Boolean query (use AND, OR, parentheses, * wildcards). Example: (deepfake OR "deep fake") AND abuse').pack(anchor="w")
query_text = scrolledtext.ScrolledText(query_frame, height=3, width=100)
query_text.pack(padx=5, pady=5)

# Options frame
options_frame = tk.Frame(root)
options_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
tk.Label(options_frame, text="Base filename:").grid(row=0, column=0, padx=5)
filename_entry = tk.Entry(options_frame, width=25)
filename_entry.insert(0, "Data_PsyArXiv")
filename_entry.grid(row=0, column=1, padx=5)

tk.Button(options_frame, text="Run Scraper", command=threaded_run_scraper).grid(row=0, column=2, padx=5)
tk.Button(options_frame, text="Preview URLs", command=preview_url).grid(row=0, column=3, padx=5)
tk.Button(options_frame, text="Abort (Esc)", command=set_abort).grid(row=0, column=4, padx=5)

# Feedback and progress
feedback_box = scrolledtext.ScrolledText(root, height=12, width=100)
feedback_box.grid(row=2, column=0, padx=5, pady=5, sticky="nsew")
progress_bar = ttk.Progressbar(root, orient="horizontal", mode="determinate")
progress_bar.grid(row=3, column=0, padx=5, pady=5, sticky="ew")

root.mainloop()
