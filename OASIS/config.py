# Constants and configuration for OASIS

ARXIV_PAGE_SIZE = 200
ARXIV_SORT_ORDER = "-announced_date_first"
ARXIV_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/106.0.0.0 Safari/537.36"
}

OSF_PAGE_SIZE = 100
OSF_API_BASE = "https://api.osf.io/v2/preprints/"
OSF_ELASTIC_URL = "https://share.osf.io/api/v2/search/creativeworks/_search"

SERVERS = {
    "ArXiv": {
        "type": "arxiv",
        "display_name": "ArXiv",
        "fields": ["all", "title", "abstract", "author"],
        "operators": ["AND", "OR"]
    },
    "OSF": {
        "type": "osf",
        "display_name": "Open Science Framework (Multi-server)"
    },
    "PsyArXiv": {"type": "osf", "display_name": "PsyArXiv", "provider": "psyarxiv"},
    "SocArXiv": {"type": "osf", "display_name": "SocArXiv", "provider": "socarxiv"},
    "LawArXiv": {"type": "osf", "display_name": "LawArXiv", "provider": "lawarxiv"},
    "Thesis Commons": {"type": "osf", "display_name": "Thesis Commons", "provider": "thesiscommons"},
}

OSF_PROVIDERS = {
    "psyarxiv": "PsyArXiv",
    "socarxiv": "SocArXiv",
    "lawarxiv": "LawArXiv",
    "thesiscommons": "Thesis Commons"
}

POLITENESS_CONFIG = {
    "Fast": {"osf_delay": 0.0, "arxiv_delay": 0.5, "retries": 2},
    "Normal": {"osf_delay": 0.5, "arxiv_delay": 3.0, "retries": 4},
    "Slow": {"osf_delay": 1.0, "arxiv_delay": 5.0, "retries": 6},
}
