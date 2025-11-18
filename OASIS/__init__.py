# package marker for OASIS
__version__ = "0.1"

# Re-export commonly used API so "from OASIS import X" works for tests
from .scrapers.osf_api import OSFPreprints
from .scrapers.osf_elastic import ElasticPreprints
from .scrapers.arxiv_scraper import scrape_arxiv
from .utils import safe_request

__all__ = [
    "OSFPreprints",
    "ElasticPreprints",
    "scrape_arxiv",
    "safe_request",
    "__version__",
]
