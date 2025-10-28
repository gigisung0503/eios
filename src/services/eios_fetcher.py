"""
EIOS v2 API Fetcher
- Auth via OAuth2 client credentials
- Accept Terms of Use (PUT /UserProfiles/me)
- Find boards by tag(s)
- Get pinned articles from boards
- Compatible with existing application flow
"""

import requests
import logging
import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import os

# === CONFIGURATION ===
WHO_TENANT_ID = os.getenv("WHO_TENANT_ID")
EIOS_CLIENT_ID_SCOPE = os.getenv("EIOS_CLIENT_ID_SCOPE")
CONSUMER_CLIENT_ID = os.getenv("CONSUMER_CLIENT_ID")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
FETCH_DURATION_HOURS = int(os.getenv("FETCH_DURATION_HOURS", "5"))

# API Configuration - Can be overridden with EIOS_BASE_URL environment variable
# Production: https://eios.who.int/portal/api/api/v1.0
# Sandbox: https://eios.who.int/portal-sandbox/api/api/v1.0
BASE_URL = os.getenv("EIOS_BASE_URL", "https://eios.who.int/portal/api/api/v1.0")
PAGE_SIZE_BOARDS = 100
PAGE_SIZE_ARTICLES = 300
MAX_ARTICLES = 5000

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
        self.base_url = BASE_URL
    
    @staticmethod
    def utc_now() -> datetime:
        """Get current UTC datetime."""
        return datetime.now(timezone.utc)
    
    @staticmethod
    def to_iso_z(dt: datetime) -> str:
        """Return Z-suffixed ISO string, e.g. 2025-10-12T10:30:00Z"""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    
    def normalize_datetime(self, datetime_string: Optional[str]) -> Optional[str]:
        """Normalize an ISO-ish string to 'YYYY-MM-DD HH:MM:SS' (UTC) if possible."""
        if not datetime_string:
            return None
        try:
            s2 = datetime_string.rstrip("Z")
            dt = datetime.fromisoformat(s2)
        except Exception:
            logger.warning(f"Failed to parse datetime: {datetime_string}. Using as-is")
            return datetime_string
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    def get_access_token(self):
        """Get OAuth2 access token from Azure AD."""
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
        token_data = res.json()
        self.access_token = token_data.get("access_token")
        if not self.access_token:
            raise RuntimeError("No access_token in token response.")
        return self.access_token
    
    def accept_terms(self):
        """Accept EIOS Terms of Use (required for API v2)."""
        if not self.access_token:
            self.get_access_token()
        
        url = f"{self.base_url}/UserProfiles/me"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        
        try:
            res = requests.put(url, headers=headers, json={"TermsOfUseAccepted": True}, timeout=30)
            res.raise_for_status()
            logger.info("Terms of Use accepted (or already accepted)")
        except Exception as e:
            logger.warning(f"Terms acceptance failed (may already be accepted): {e}")

    def get_boards(self, tag: str) -> List[Dict[str, Any]]:
        """Get boards by tag using EIOS v2 API."""
        if not self.access_token:
            self.get_access_token()
            self.accept_terms()
        
        headers = {"Authorization": f"Bearer {self.access_token}"}
        url = f"{self.base_url}/Boards/by-tags"
        
        start = 0
        all_boards = []
        
        while True:
            params = {
                "start": start,
                "limit": PAGE_SIZE_BOARDS,
            }
            if tag:
                params["tags"] = tag
            
            res = requests.get(url, headers=headers, params=params, timeout=30)
            res.raise_for_status()
            
            js = res.json() or {}
            page = js.get("result") or (js if isinstance(js, list) else [])
            
            if not page:
                break
            
            all_boards.extend(page)
            
            if len(page) < PAGE_SIZE_BOARDS:
                break
            
            start += PAGE_SIZE_BOARDS
        
        logger.info(f"Fetched {len(all_boards)} boards for tag '{tag}'")
        return all_boards

    def get_pinned_articles(self, board_ids: List[str], pinned_since_iso: str) -> List[Dict[str, Any]]:
        """Get pinned articles from boards using EIOS v2 API."""
        if not self.access_token:
            self.get_access_token()
            self.accept_terms()
        
        headers = {"Authorization": f"Bearer {self.access_token}"}
        url = f"{self.base_url}/Items/pinned-to-boards"
        
        start = 0
        all_articles = []
        
        while True:
            params = {
                "boardIds": ",".join(board_ids),
                "start": start,
                "limit": PAGE_SIZE_ARTICLES,
                "pinnedSince": pinned_since_iso,
            }
            
            res = requests.get(url, headers=headers, params=params, timeout=30)
            res.raise_for_status()
            
            js = res.json() or {}
            page = js.get("result") or (js if isinstance(js, list) else [])
            
            if not page:
                break
            
            all_articles.extend(page)
            logger.info(f"Fetched pinned page: {len(page)} articles (total: {len(all_articles)})")
            
            if len(all_articles) >= MAX_ARTICLES:
                logger.warning(f"Reached MAX_ARTICLES cap ({MAX_ARTICLES})")
                break
            
            if len(page) < PAGE_SIZE_ARTICLES:
                break
            
            start += PAGE_SIZE_ARTICLES
        
        return all_articles

    def get_board_articles(self, board_id: str, time_since_iso: str) -> List[Dict[str, Any]]:
        """Get all articles matching board filter (both pinned and unpinned) using EIOS v2 API."""
        if not self.access_token:
            self.get_access_token()
            self.accept_terms()
        
        headers = {"Authorization": f"Bearer {self.access_token}"}
        url = f"{self.base_url}/Items/matching-board/{board_id}"
        
        start = 0
        all_articles = []
        
        while True:
            params = {
                "start": start,
                "limit": PAGE_SIZE_ARTICLES,
                "timeSince": time_since_iso,
            }
            
            res = requests.get(url, headers=headers, params=params, timeout=30)
            res.raise_for_status()
            
            js = res.json() or {}
            page = js.get("result") or (js if isinstance(js, list) else [])
            
            if not page:
                break
            
            all_articles.extend(page)
            logger.info(f"Fetched board articles page: {len(page)} articles (total: {len(all_articles)} for board {board_id})")
            
            if len(all_articles) >= MAX_ARTICLES:
                logger.warning(f"Reached MAX_ARTICLES cap ({MAX_ARTICLES})")
                break
            
            if len(page) < PAGE_SIZE_ARTICLES:
                break
            
            start += PAGE_SIZE_ARTICLES
        
        return all_articles

    def _transform_article_v2_to_v1(self, article: Dict[str, Any]) -> Dict[str, Any]:
        """Transform EIOS v2 article format to match v1 format expected by the application."""
        source = article.get("source", {})
        
        return {
            'id': article.get('id'),
            'title': article.get('title'),
            'originalTitle': article.get('originalTitle'),
            'translatedDescription': article.get('translatedDescription'),
            'description': article.get('description'),
            'abstractiveSummary': article.get('abstractiveSummary'),
            'translatedAbstractiveSummary': article.get('translatedDescription'),  # Use description as fallback
            'link': article.get('link'),
            'languageIso': article.get('languageIso'),
            'pubDate': article.get('pubDate') or article.get('publicationDate') or article.get('publishedAt'),
            'processedOnDate': article.get('processedOnDate'),
            'source': {
                'id': source.get('id'),
                'name': source.get('name'),
                'url': source.get('url'),
                'country': source.get('country', {})
            }
        }

    def get_all_articles(self, board_id: int) -> List[Dict[str, Any]]:
        """Legacy method - not used in v2 API."""
        logger.warning("get_all_articles is deprecated in EIOS v2 API")
        return []

    def get_pinned_article_ids(self, board_ids: List[int]) -> set:
        """Legacy method - returns empty set as v2 API handles pinned differently."""
        logger.warning("get_pinned_article_ids is deprecated in EIOS v2 API")
        return set()

    def get_all_articles_with_pinned_status(self, board_ids: List[int]) -> List[Dict[str, Any]]:
        """
        Get all articles (both pinned and unpinned) from boards with their pinned status.
        
        Args:
            board_ids: List of board IDs to fetch articles from
            
        Returns:
            List of articles with 'is_pinned' field properly set
        """
        # Convert board IDs to strings
        board_id_strings = [str(bid) for bid in board_ids]
        
        # Calculate time window
        time_since = self.utc_now() - timedelta(hours=FETCH_DURATION_HOURS)
        time_since_iso = self.to_iso_z(time_since)
        
        logger.info(f"Fetching articles since {time_since_iso} (UTC)")
        
        # Step 1: Get pinned articles
        logger.info(f"Fetching pinned articles from {len(board_id_strings)} boards")
        pinned_articles = self.get_pinned_articles(board_id_strings, time_since_iso)
        
        # Create a set of pinned article IDs for quick lookup
        pinned_article_ids = {article.get('id') for article in pinned_articles if article.get('id')}
        logger.info(f"Found {len(pinned_article_ids)} pinned articles")
        
        # Step 2: Get all articles matching board filters for each board
        all_board_articles = []
        seen_article_ids = set()
        
        for board_id in board_id_strings:
            logger.info(f"Fetching all articles from board {board_id}")
            board_articles = self.get_board_articles(board_id, time_since_iso)
            
            # Add articles we haven't seen yet
            for article in board_articles:
                article_id = article.get('id')
                if article_id and article_id not in seen_article_ids:
                    all_board_articles.append(article)
                    seen_article_ids.add(article_id)
        
        logger.info(f"Found {len(all_board_articles)} total unique articles from all boards")
        
        # Step 3: Transform articles and mark pinned status
        transformed_articles = []
        for article in all_board_articles:
            transformed = self._transform_article_v2_to_v1(article)
            article_id = article.get('id')
            
            # Check if this article is in the pinned set
            transformed['is_pinned'] = article_id in pinned_article_ids
            
            transformed_articles.append(transformed)
        
        pinned_count = sum(1 for a in transformed_articles if a.get('is_pinned'))
        unpinned_count = len(transformed_articles) - pinned_count
        
        logger.info(f"Total articles: {len(transformed_articles)} (pinned: {pinned_count}, unpinned: {unpinned_count})")
        
        return transformed_articles

    def get_unpinned_articles_from_boards(self, board_ids: List[int]) -> List[Dict[str, Any]]:
        """
        Legacy method for backward compatibility.
        Note: EIOS v2 API primarily provides pinned articles.
        This method now returns an empty list as unpinned articles are not directly accessible.
        """
        logger.info("Note: EIOS v2 API focuses on pinned articles. Unpinned articles not available through this endpoint.")
        return []

    def fetch_articles(self, tags: List[str]) -> List[Dict[str, Any]]:
        """
        Fetch signals from EIOS based on provided tags.
        
        Args:
            tags: List of tags to search for
            
        Returns:
            List of articles/signals with pinned status
        """
        try:
            all_articles = []

            for tag in tags:
                logger.info(f"Processing tag: {tag}")
                boards = self.get_boards(tag)
                board_ids = [b.get('id') for b in boards if b.get('id')]
                
                if not board_ids:
                    logger.warning(f"No boards found for tag '{tag}'")
                    continue

                articles = self.get_all_articles_with_pinned_status(board_ids)
                all_articles.extend(articles)

            logger.info(f"Total signals fetched: {len(all_articles)}")
            return all_articles

        except requests.RequestException as e:
            logger.error(f"EIOS request failed: {e}")
            raise e

