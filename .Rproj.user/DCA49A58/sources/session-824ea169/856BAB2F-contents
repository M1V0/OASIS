import httpx
import pandas as pd
from bs4 import BeautifulSoup
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import re
import webbrowser

# ----------------- Constants -----------------
PAGE_SIZE = 200
SORT_ORDER = "-announced_date_first"

headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/106.0.0.0 Safari/537.36"
}

# ----------------- Scraper Functions -----------------
def extract_text(soup, selector):
    try:
        return soup.select_one(selector).get_text(strip=True)
    except AttributeError:
        return None

def find_data(soup):
    for p in soup.select("p"):
        txt = p.get_text(strip=True)
        if txt.startswith("Submitted"):
            parts = txt.split(";")
            sub = parts[0].replace("Submitted", "").strip()
            ann = parts[-1].replace("originally announced", "").strip()
            return sub, ann
    return None, None

def parse_page(content):
    soup = BeautifulSoup(content, "lxml")
    lis = soup.select("li.arxiv-result")
    results = []
    for li in lis:
        arxiv_id = None
        link = li.find("p", class_="list-title")
        if link:
            a_tag = link.find("a")
            if a_tag and 'href' in a_tag.attrs:
                arxiv_id = a_tag['href'].split("/")[-1]

        title = extract_text(li, "p.title")
        authors = ",".join([a.get_text(strip=True) for a in li.select("p.authors > a")])
        abstract = extract_text(li, "span.abstract-full")
        if abstract:
            abstract = abstract.removesuffix("△ Less")
        comments = extract_text(li, "p.comments > span:nth-of-type(2)")
        sub, ann = find_data(li)

        results.append({
            "ID": arxiv_id,
            "Title": title,
            "Authors": authors,
            "Abstract": abstract,
            "Comments": comments,
            "Submitted": sub,
            "Announce": ann
        })
    return results

def scrape_arxiv(url, feedback_box=None, progress_bar=None):
    client = httpx.Client(headers=headers)
    all_results = {}
    page = 0

    while True:
        page_url = f"{url}&start={page*PAGE_SIZE}"
        msg = f"Fetching page {page+1}..."
        print(msg)
        if feedback_box:
            feedback_box.insert(tk.END, msg + "\n")
            feedback_box.see(tk.END)
            feedback_box.update()

        res = client.get(page_url, timeout=15)
        page_results = parse_page(res.content)
        if not page_results:
            break

        for r in page_results:
            if r["ID"]:
                all_results[r["ID"]] = r

        if progress_bar:
            progress_bar['value'] = min(progress_bar['value'] + 5, 100)
            progress_bar.update()

        page += 1
        if len(page_results) < PAGE_SIZE:
            break

    if progress_bar:
        progress_bar['value'] = 100
        progress_bar.update()

    return list(all_results.values())

# ----------------- URL Builders -----------------
def build_url_from_conditions(conditions):
    if not conditions:
        return ""
    first_operator = conditions[0]['operator']
    field = conditions[0]['field']
    terms_list = []
    for cond in conditions:
        val = cond['value'].strip()
        if val:
            if not (val.startswith('"') and val.endswith('"')):
                val = f'"{val}"'
            terms_list.append(val)
    terms_str = f" {first_operator} ".join(terms_list)
    terms_encoded = terms_str.replace(" ", "+")
    url = (
        f"https://arxiv.org/search/advanced?advanced="
        f"&terms-0-operator={first_operator}"
        f"&terms-0-term={terms_encoded}"
        f"&terms-0-field={field}"
        f"&classification-physics_archives=all"
        f"&classification-include_cross_list=include"
        f"&date-filter_by=all_dates"
        f"&date-year=&date-from_date=&date-to_date="
        f"&date-date_type=submitted_date"
        f"&abstracts=show"
        f"&size={PAGE_SIZE}"
        f"&order={SORT_ORDER}"
    )
    return url

# ----------------- GUI Scraper -----------------
def run_scraper():
    base_filename = filename_entry.get().strip() or "Data_ArXiv"
    feedback_box.delete(1.0, tk.END)
    progress_bar['value'] = 0

    if mode_var.get() == "Build":
        conditions = []
        for row in condition_rows:
            field = row['field_var'].get()
            operator = row['operator_var'].get()
            value = row['value_widget'].get().strip()
            if value:
                conditions.append({'field': field, 'operator': operator, 'value': value})
        if not conditions:
            messagebox.showerror("Error", "Add at least one condition.")
            return
        url = build_url_from_conditions(conditions)
    else:
        url = paste_url_text.get("1.0", tk.END).strip()
        if not url:
            messagebox.showerror("Error", "Paste a valid ArXiv URL.")
            return
        # Force hardcoded page size and order
        url = re.sub(r'size=\d+', f"size={PAGE_SIZE}", url)
        if "order=" in url:
            url = re.sub(r'order=[^&]+', f"order={SORT_ORDER}", url)
        else:
            url += f"&order={SORT_ORDER}"

    feedback_box.insert(tk.END, f"Scraping URL: {url}\n")
    feedback_box.see(tk.END)
    feedback_box.update()

    try:
        results = scrape_arxiv(url, feedback_box, progress_bar)
        if results:
            df = pd.DataFrame(results)
            filename = f"{base_filename}.csv"
            df.to_csv(filename, index=False)
            msg = f"Scraping complete! {len(df)} unique results saved to {filename}"
            feedback_box.insert(tk.END, msg + "\n")
            feedback_box.see(tk.END)
            messagebox.showinfo("Done", msg)
        else:
            feedback_box.insert(tk.END, "No papers found for this query.\n")
            messagebox.showwarning("No Results", "No papers found for this query.")
    except Exception as e:
        feedback_box.insert(tk.END, f"Error: {e}\n")
        messagebox.showerror("Error", str(e))

# ----------------- GUI Layout -----------------
root = tk.Tk()
root.title("ArXiv Systematic Scraper")

# Server selection (for future expansion)
server_var = tk.StringVar(value="ArXiv")
server_frame = tk.Frame(root)
server_frame.grid(row=0, column=0, sticky="w", padx=5, pady=5)
tk.Label(server_frame, text="Preprint Server: ArXiv").pack(side="left")

# Mode selection
mode_var = tk.StringVar(value="Build")
mode_frame = tk.Frame(root)
mode_frame.grid(row=1, column=0, sticky="w", padx=5, pady=5)
tk.Radiobutton(mode_frame, text="Build Query", variable=mode_var, value="Build", command=lambda: toggle_mode()).pack(side="left")
tk.Radiobutton(mode_frame, text="Paste URL", variable=mode_var, value="Paste", command=lambda: toggle_mode()).pack(side="left")

# Query frames container
query_frame = tk.Frame(root)
query_frame.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)

# Build frame
build_frame = tk.Frame(query_frame)
build_frame.grid(row=0, column=0, sticky="nsew")
condition_rows = []

def add_condition():
    row = {}
    idx = len(condition_rows)
    lbl = tk.Label(build_frame, text=f"Condition {idx+1}")
    lbl.grid(row=idx, column=0, padx=5)
    row['label'] = lbl

    op_var = tk.StringVar(value="AND")
    op_menu = ttk.Combobox(build_frame, textvariable=op_var, values=["AND", "OR"], width=5)
    op_menu.grid(row=idx, column=1, padx=5)
    row['operator_var'] = op_var
    row['operator_widget'] = op_menu

    field_var = tk.StringVar(value="all")
    field_menu = ttk.Combobox(build_frame, textvariable=field_var, values=["all","title","abstract","author"], width=10)
    field_menu.grid(row=idx, column=2, padx=5)
    row['field_var'] = field_var
    row['field_widget'] = field_menu

    entry = tk.Entry(build_frame, width=40)
    entry.grid(row=idx, column=3, padx=5)
    row['value_widget'] = entry

    condition_rows.append(row)

def remove_condition():
    if condition_rows:
        last = condition_rows.pop()
        for widget_key in ['label', 'operator_widget', 'field_widget', 'value_widget']:
            if widget_key in last:
                last[widget_key].destroy()

tk.Button(build_frame, text="Add Condition", command=add_condition).grid(row=999, column=0, pady=5)
tk.Button(build_frame, text="Remove Last Condition", command=remove_condition).grid(row=999, column=1, pady=5)
add_condition()

# Paste URL frame
paste_frame = tk.Frame(query_frame)
paste_frame.grid(row=0, column=0, sticky="nsew")
tk.Label(paste_frame, text="Paste full ArXiv search URL:").pack()
paste_url_text = tk.Text(paste_frame, height=3, width=80)
paste_url_text.pack()
paste_frame.grid_remove()

def toggle_mode():
    if mode_var.get() == "Build":
        build_frame.grid()
        paste_frame.grid_remove()
    else:
        build_frame.grid_remove()
        paste_frame.grid()

# Options frame
options_frame = tk.Frame(root)
options_frame.grid(row=3, column=0, sticky="ew", padx=5, pady=5)
tk.Label(options_frame, text="Base filename:").grid(row=0, column=0, padx=5)
filename_entry = tk.Entry(options_frame, width=25)
filename_entry.insert(0,"Data_ArXiv")
filename_entry.grid(row=0, column=1, padx=5)

tk.Button(options_frame, text="Run Scraper", command=run_scraper).grid(row=0, column=2, padx=5)
tk.Button(options_frame, text="Preview URL", command=lambda: preview_url()).grid(row=0, column=3, padx=5)

# Feedback and progress
feedback_box = scrolledtext.ScrolledText(root, height=10, width=100)
feedback_box.grid(row=4, column=0, padx=5, pady=5, sticky="nsew")
progress_bar = ttk.Progressbar(root, orient="horizontal", mode="determinate")
progress_bar.grid(row=5, column=0, padx=5, pady=5, sticky="ew")

# ----------------- Preview URL with Visit Option -----------------
def preview_url():
    if mode_var.get() != "Build":
        messagebox.showinfo("Preview URL", "Preview works only in Build Query mode.")
        return

    conditions = []
    for row in condition_rows:
        field = row['field_var'].get()
        operator = row['operator_var'].get()
        value = row['value_widget'].get().strip()
        if value:
            conditions.append({'field': field, 'operator': operator, 'value': value})

    if not conditions:
        messagebox.showwarning("Preview URL", "Add at least one condition first.")
        return

    url = build_url_from_conditions(conditions)

    popup = tk.Toplevel(root)
    popup.title("Generated ArXiv URL")
    tk.Label(popup, text="Preview of the generated URL:").pack(pady=5)

    url_box = scrolledtext.ScrolledText(popup, width=120, height=5)
    url_box.pack(padx=5, pady=5)
    url_box.insert(tk.END, url)
    url_box.configure(state="disabled")

    def visit_link():
        webbrowser.open(url)

    btn_frame = tk.Frame(popup)
    btn_frame.pack(pady=5)
    tk.Button(btn_frame, text="Visit URL", command=visit_link).pack(side="left", padx=5)
    tk.Button(btn_frame, text="Close", command=popup.destroy).pack(side="left", padx=5)

root.mainloop()
