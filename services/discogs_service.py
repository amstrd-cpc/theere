from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config.settings import load_settings

logger = logging.getLogger(__name__)


class DiscogsNotConfigured(RuntimeError):
    pass


class DiscogsError(RuntimeError):
    pass


def _session() -> requests.Session:
    settings = load_settings()
    if not settings.discogs_token:
        raise DiscogsNotConfigured("DISCOGS_TOKEN not set")
    session = requests.Session()
    session.headers.update({"Authorization": f"Discogs token={settings.discogs_token}"})
    return session


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type(requests.RequestException))
def search_releases(query: str, page: int = 1, per_page: int = 50) -> List[Dict[str, Any]]:
    session = _session()
    response = session.get(
        "https://api.discogs.com/database/search",
        params={"q": query, "type": "release", "page": page, "per_page": per_page},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    return data.get("results", [])


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type(requests.RequestException))
def fetch_release(release_id: int) -> Dict[str, Any]:
    session = _session()
    response = session.get(f"https://api.discogs.com/releases/{release_id}", timeout=15)
    response.raise_for_status()
    return response.json()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type(requests.RequestException))
def fetch_price_suggestions(release_id: int) -> Dict[str, Any]:
    session = _session()
    response = session.get(
        f"https://api.discogs.com/marketplace/price_suggestions/{release_id}",
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def format_tracklist(tracklist: List[Dict[str, Any]]) -> str:
    if not tracklist:
        return ""
    parts = ["<h3>Tracklist</h3>", "<ol>"]
    for track in tracklist:
        title = track.get("title") or ""
        position = track.get("position") or ""
        duration = track.get("duration") or ""
        label = f"{position} {title}".strip()
        if duration:
            parts.append(f"<li>{label} ({duration})</li>")
        else:
            parts.append(f"<li>{label}</li>")
    parts.append("</ol>")
    return "".join(parts)


def safe_join_list(values: Any, default: str = "N/A") -> str:
    if not values:
        return default
    if isinstance(values, list):
        return ", ".join(str(item) for item in values if item)
    return str(values)


def extract_labels(release: Dict[str, Any]) -> str:
    labels = release.get("labels") or []
    return ", ".join(label.get("name") for label in labels if label.get("name")) or "N/A"


def extract_formats(release: Dict[str, Any]) -> str:
    formats = release.get("formats") or []
    parts: List[str] = []
    for fmt in formats:
        chunk = []
        if fmt.get("name"):
            chunk.append(str(fmt.get("name")))
        if fmt.get("descriptions"):
            chunk.extend([str(desc) for desc in fmt.get("descriptions") if desc])
        if chunk:
            parts.append(" ".join(chunk))
    return ", ".join(parts) if parts else "Unknown Format"


def extract_cover_url(release: Dict[str, Any]) -> Optional[str]:
    images = release.get("images") or []
    for image in images:
        if image.get("type") == "primary":
            return image.get("uri")
    if images:
        return images[0].get("uri")
    return None
