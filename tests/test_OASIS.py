# test_oasis.py
import logging
from OASIS import OSFPreprints, ElasticPreprints, scrape_arxiv

def run_tests():
    logging.basicConfig(level=logging.INFO)
    print("Testing OSFPreprints API...")
    osf_api = OSFPreprints(provider="psyarxiv", politeness="Fast")
    df1 = osf_api.run("cognitive therapy")
    print("OSF API results:", len(df1))

    print("Testing ElasticPreprints (weblike)...")
    osf_elastic = ElasticPreprints(provider="psyarxiv", politeness="Fast")
    df2 = osf_elastic.run("cognitive AND therapy")
    print("OSF Elastic results:", len(df2))

    print("Testing ArXiv scrape...")
    url = "https://arxiv.org/search/advanced?advanced=&terms-0-term=deepfake&terms-0-field=all&size=50&order=-announced_date_first"
    results = scrape_arxiv(url, politeness="Fast")
    print("ArXiv results:", len(results))

if __name__ == "__main__":
    run_tests()
