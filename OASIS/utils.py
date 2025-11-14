# Utility helpers used across modules

import os
import time
import random
import logging
import httpx

from .config import POLITENESS_CONFIG

def unique_filename(path):
    """If path exists, append _1, _2, ... before extension."""
    base, ext = os.path.splitext(path)
    counter = 1
    new = path
    while os.path.exists(new):
        new = f"{base}_{counter}{ext}"
        counter += 1
    return new


def safe_request(method, url, client=None, retries=4, backoff_factor=2, politeness_delay=0.5, **kwargs):
    """
    Perform an HTTP request with retry/backoff for 429 and basic RequestError handling.
    - client: httpx.Client instance (optional)
    """
    attempt = 0
    while True:
        try:
            if client is not None:
                res = client.request(method, url, **kwargs)
            else:
                res = httpx.request(method, url, **kwargs)

            # handle 429 / rate-limit
            if res.status_code == 429:
                wait = (backoff_factor ** attempt) + random.uniform(0, 1)
                logging.warning(f"429 received for {url}. Backing off {wait:.1f}s (attempt {attempt + 1}/{retries}).")
                time.sleep(wait)
                attempt += 1
                if attempt >= retries:
                    res.raise_for_status()
                continue

            res.raise_for_status()

            # politeness delay after successful request
            if politeness_delay and politeness_delay > 0:
                time.sleep(politeness_delay)

            return res

        except httpx.RequestError as e:
            # network-level failure
            wait = (backoff_factor ** attempt) + random.uniform(0, 1)
            logging.warning(f"Request error: {e}. Retrying in {wait:.1f}s (attempt {attempt + 1}/{retries}).")
            time.sleep(wait)
            attempt += 1
            if attempt >= retries:
                raise
