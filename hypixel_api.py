import logging
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

API_KEY = os.getenv("HYPIXEL_API_KEY")

ELECTION_URL = "https://api.hypixel.net/v2/resources/skyblock/election"

MAX_RETRIES = 3
RETRY_BACKOFF = 2  # seconds, doubles each retry


def _is_retryable(status):
    """Rate limits (429) and 5xx server errors are worth retrying."""
    return status is not None and (status == 429 or status >= 500)


def get_election_data():
    """Fetch SkyBlock election data from the Hypixel API.

    Retries up to MAX_RETRIES times with exponential backoff on
    transient failures (network errors, rate limits, server errors).
    Raises the last exception if all attempts fail.
    """
    headers = {
        "API-Key": API_KEY
    }

    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                ELECTION_URL,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            last_error = e
            # Only 429 and 5xx are worth retrying; everything else is fatal.
            status = e.response.status_code if e.response is not None else None
            if not _is_retryable(status):
                raise
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            last_error = e

        if attempt < MAX_RETRIES - 1:
            backoff = RETRY_BACKOFF * (2 ** attempt)
            logger.warning(
                "Hypixel API request failed (attempt %d/%d), retrying in %ds: %s",
                attempt + 1, MAX_RETRIES, backoff, last_error
            )
            time.sleep(backoff)

    logger.error("Hypixel API request failed after %d attempts", MAX_RETRIES)
    raise RuntimeError(f"Hypixel API request failed after {MAX_RETRIES} attempts") from last_error
