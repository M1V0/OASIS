# QThread-based ScraperThread that chooses appropriate scraper based on server_config
from PyQt6.QtCore import QThread, pyqtSignal
import pandas as pd
import logging

from ..config import SERVERS
from ..scrapers.arxiv_scraper import scrape_arxiv
from ..scrapers.osf_api import OSFPreprints
from ..scrapers.osf_elastic import ElasticPreprints

class ScraperThread(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(pd.DataFrame)
    error = pyqtSignal(str)

    def __init__(self, server_config, query, search_mode, conditions=None, url=None, politeness="Normal"):
        super().__init__()
        self.server_config = server_config
        self.query = query
        self.search_mode = search_mode
        self.conditions = conditions
        self.url = url
        self.client = None
        self.abort_flag = False
        self.politeness = politeness

    def run(self):
        try:
            if self.server_config["type"] == "arxiv":
                if self.url:
                    final_url = self.url
                else:
                    # build ArXiv URL from conditions
                    terms_list = []
                    first_operator = self.conditions[0]['operator'] if self.conditions else "AND"
                    for cond in (self.conditions or []):
                        val = cond['value'].strip()
                        if val:
                            if not (val.startswith('"') and val.endswith('"')):
                                val = f'"{val}"'
                            terms_list.append(val)
                    terms_str = f" {first_operator} ".join(terms_list)
                    terms_encoded = terms_str.replace(" ", "+")
                    final_url = (
                        f"https://arxiv.org/search/advanced?advanced="
                        f"&terms-0-operator={first_operator}"
                        f"&terms-0-term={terms_encoded}"
                        f"&terms-0-field={self.conditions[0]['field'] if self.conditions else 'all'}"
                        f"&classification-physics_archives=all"
                        f"&classification-include_cross_list=include"
                        f"&date-filter_by=all_dates"
                        f"&date-year=&date-from_date=&date-to_date="
                        f"&date-date_type=submitted_date"
                        f"&abstracts=show"
                        f"&size={200}"
                        f"&order={'-announced_date_first'}"
                    )

                self.progress.emit(f"Starting ArXiv scrape using query: {self.query or 'ArXiv build/paste'}")
                logging.info(f"ArXiv scrape started. URL: {final_url}")
                logging.info(f"using query: {self.query}")
                results = scrape_arxiv(final_url, feedback_callback=self.progress, progress_callback=None, politeness=self.politeness)
                df = pd.DataFrame(results)

            else:
                provider = self.server_config["provider"]
                if self.search_mode == "api":
                    self.client = OSFPreprints(provider=provider, politeness=self.politeness)
                else:
                    self.client = ElasticPreprints(provider=provider, politeness=self.politeness)

                logging.info(f"OSF scrape started on provider={provider}")
                logging.info(f"using query: {self.query}")

                self.progress.emit(f"Starting OSF scrape using query: {self.query}")
                df = self.client.run(self.query, progress_callback=self.progress)

            self.finished.emit(df)
        except Exception as e:
            self.error.emit(str(e))

    def abort(self):
        self.abort_flag = True
        if self.client:
            self.client.abort_flag = True
