<h1>Welcome to the OASIS - Open ArXiv Scraper for Implementing Systematic Reviews</h1>

With this lightweight tool you can construct and run queries to be used to scrape preprint servers of the necessary metadata for the screening stage of a systematic review.

<h2>Included preprint servers:</h2>

ArXiv,

PsyArXiv,

SocArXiv,

engrXiv,

LawArXiv,

MedArXiv,

ECSarXiv, and

Thesis Commons

<h2>To install</h2>

First get all necessary modules
```
pip3 install -r requirements.txt
```

Then launch it via:
```
python3 OASIS.py
```

<h2>Scraping procedures</h2>
There are two (well, three) different ways in which OASIS can generate and scrape the preprint servers. 

1) For ArXiv it is relatively straight forward. It either generates the query string in-app or you can provide it with the URL that you created yourself in the advanced search of ArXiv. It then uses the URL to procedurally scrape each returned search page until it runs out of preprints to record. Simply, straightfoward, and dare I say, elegant.

2) For OSF-hosted *ArXivs (e.g. PsyArXiv), there is a) a stable, official version that uses the OSF API, and b) an unofficial, perhaps less stable version that uses the ElasticSearch API.

   a) The offocial version. This uses https://api.osf.io/v2/preprints/ as the API. One limitation is that it can only search for a keyword in the title, not elsewhere, and not multiple keywords either. So, when a query like ("cognition" and "memory") is sent, it will go through all possible terms to search independently, and then filter the returned items locally (in title and abstract) for the other keyword. So, for example it would query the API for any items with cognition in the title, before filtering and keeping items that also have memory in the title or abstract. It then flips these and searches memory first and filtering on cognition. It treats AND operators in this way, for OR operators it just runs another API call. The OSF API cannot accept wildcards, but it does search for substrings regardless and not exact matches, so "cognitiv" will return all matches for "cognitive", "cognition", "metacognition", "recognition" etc. So be careful when writing a query that starts to return many, many pages.

   b) The unofficial, but more comprehensive version. The web search function (e.g. https://osf.io/preprints/psyarxiv/discover) uses a different API, ElasticSearch. This enables searching of title and abstract properly, so that's what this strategy does. It's a better and more thorough search, but is more likely to be broken by any changes by ElasticSearch or OSF simply because OSF has the official API (used in option A). This can take boolean operators as: `AND`, `&`, `and`, `OR`, `|`, `or`. It will also take wildcards as `*` or as `?`. `?` can be effective when considering differences in potential spelling, such as "behaviour" or "behavior" - searching with "behavio?r" will retrieve both spelling variants.
