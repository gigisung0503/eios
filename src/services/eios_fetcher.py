import requests
import logging
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any
import os

# === CONFIGURATION ===
WHO_TENANT_ID = os.getenv("WHO_TENANT_ID")
EIOS_CLIENT_ID_SCOPE = os.getenv("EIOS_CLIENT_ID_SCOPE")
CONSUMER_CLIENT_ID = os.getenv("CONSUMER_CLIENT_ID")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
FETCH_DURATION_HOURS = int(os.getenv("FETCH_DURATION_HOURS", "1"))

# Optional: fail fast if anything critical is missing
REQUIRED = ["WHO_TENANT_ID", "EIOS_CLIENT_ID_SCOPE", "CONSUMER_CLIENT_ID", "CONSUMER_SECRET"]
_missing = [k for k in REQUIRED if not globals()[k]]
if _missing:
    raise RuntimeError(f"Missing required env vars: {', '.join(_missing)}")

# === LOGGING ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eios_fetcher")

class EIOSFetcher:
    def __init__(self):
        self.access_token = None
    
    def normalize_datetime(self, datetime_string):
        try:
            dt = datetime.fromisoformat(datetime_string.rstrip('Z'))
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            logger.warning(
                "Failed to parse datetime: %s. Using now()", datetime_string)
            return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def get_access_token(self):
        url = f"https://login.microsoftonline.com/{WHO_TENANT_ID}/oauth2/v2.0/token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": CONSUMER_CLIENT_ID,
            "client_secret": CONSUMER_SECRET,
            "scope": EIOS_CLIENT_ID_SCOPE
        }
        logger.info("Authenticating with Azure...")
        res = requests.post(url, data=payload, timeout=60)
        res.raise_for_status()
        self.access_token = res.json()["access_token"]
        return self.access_token

    def get_boards(self, tag: str) -> List[Dict[str, Any]]:
        if not self.access_token:
            self.get_access_token()
        
        headers = {"Authorization": f"Bearer {self.access_token}"}
        url = "https://portal.who.int/eios/API/News/Service/GetBoards"
        params = {"tags": tag, "start": 0, "limit": 5000}
        res = requests.get(url, headers=headers, params=params, timeout=30)
        res.raise_for_status()
        return res.json().get("result", [])

    def get_all_articles(self, board_id: int) -> List[Dict[str, Any]]:
        if not self.access_token:
            self.get_access_token()
        
        headers = {"Authorization": f"Bearer {self.access_token}"}
        url = "https://portal.who.int/eios/API/News/Service/GetBoardArticles"
        all_results = []
        start = 0
        page_size = 300
        while True:
            params = {
                "boardId": board_id,
                "timespan": "now-2h/h",
                "start": start,
                "limit": page_size,
            }
            res = requests.get(url, headers=headers, params=params, timeout=30)
            res.raise_for_status()
            results = res.json().get("result", [])
            all_results.extend(results)
            if len(results) < page_size:
                break
            start += page_size
        return all_results

    def get_pinned_article_ids(self, board_ids: List[int]) -> set:
        if not self.access_token:
            self.get_access_token()
        
        headers = {"Authorization": f"Bearer {self.access_token}"}
        url = "https://portal.who.int/eios/API/News/Service/GetPinnedArticles"
        pin_date_start = (datetime.utcnow() -
                          timedelta(hours=FETCH_DURATION_HOURS)).isoformat() + "Z"
        params = {
            "boardIds": ",".join(map(str, board_ids)),
            "pinDateStart": pin_date_start,
            "start": 0,
            "limit": 5000,
        }
        res = requests.get(url, headers=headers, params=params, timeout=30)
        res.raise_for_status()
        pinned = res.json().get("result", [])
        return {article["id"] for article in pinned if "id" in article}

    def get_unpinned_articles_from_boards(self, board_ids: List[int]) -> List[Dict[str, Any]]:
        pinned_ids = self.get_pinned_article_ids(board_ids)
        logger.info("Pinned articles found: %d", len(pinned_ids))
        unpinned = []
        for board_id in board_ids:
            board_articles = self.get_all_articles(board_id)
            for article in board_articles:
                if article.get("id") not in pinned_ids:
                    unpinned.append(article)
        logger.info("Total unpinned articles found: %d", len(unpinned))
        return unpinned

    def fetch_signals(self, tags: List[str]) -> List[Dict[str, Any]]:
        """
        Fetch signals from EIOS based on provided tags.
        
        Args:
            tags: List of tags to search for
            
        Returns:
            List of unpinned articles/signals
        """
        try:
            all_unpinned_articles = []

            for tag in tags:
                logger.info("Processing tag: %s", tag)
                boards = self.get_boards(tag)
                board_ids = [b['id'] for b in boards]
                if not board_ids:
                    continue

                articles = self.get_unpinned_articles_from_boards(board_ids)
                all_unpinned_articles.extend(articles)

            logger.info("Total signals fetched: %d", len(all_unpinned_articles))
            return all_unpinned_articles

        except requests.RequestException as e:
            logger.error("EIOS request failed: %s", e)
            raise e

