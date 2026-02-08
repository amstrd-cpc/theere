from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

from services.discogs_client import DiscogsClient

logger = logging.getLogger(__name__)


class DiscogsNotConfigured(RuntimeError):
    pass


def _client(store: Dict[str, Any]) -> DiscogsClient:
    token = store.get("discogs_token")
    if not token:
        raise DiscogsNotConfigured("Discogs token not configured for this store.")
    return DiscogsClient(token)


def search_releases(store: Dict[str, Any], query: str, page: int = 1, per_page: int = 50) -> List[Dict[str, Any]]:
    client = _client(store)
    data = client.get(
        "/database/search",
        params={"q": query, "type": "release", "page": page, "per_page": per_page},
    )
    return data.get("results", [])


def fetch_release(store: Dict[str, Any], release_id: int) -> Dict[str, Any]:
    client = _client(store)
    return client.get(f"/releases/{release_id}")


def fetch_price_suggestions(store: Dict[str, Any], release_id: int) -> Dict[str, Any]:
    client = _client(store)
    return client.get(f"/marketplace/price_suggestions/{release_id}")


def get_identity(store: Dict[str, Any]) -> Dict[str, Any]:
    client = _client(store)
    return client.get_identity()


def create_listing(store: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    client = _client(store)
    return client.post("/marketplace/listings", payload)


def update_listing(store: Dict[str, Any], listing_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    client = _client(store)
    return client.update(f"/marketplace/listings/{listing_id}", payload)


def fetch_listing(store: Dict[str, Any], listing_id: int) -> Dict[str, Any]:
    client = _client(store)
    return client.get(f"/marketplace/listings/{listing_id}")


def add_to_collection(store: Dict[str, Any], release_id: int, *, folder_id: int = 1) -> Dict[str, Any]:
    username = store.get("discogs_username")
    if not username:
        identity = get_identity(store)
        username = identity.get("username")
    if not username:
        raise DiscogsNotConfigured("Discogs username not configured for this store.")
    client = _client(store)
    return client.post(
        f"/users/{username}/collection/folders/{folder_id}/releases/{int(release_id)}",
        {},
    )


def fetch_collection_release_instances(
    store: Dict[str, Any],
    release_id: int,
    *,
    folder_id: int = 1,
) -> List[Dict[str, Any]]:
    username = store.get("discogs_username")
    if not username:
        identity = get_identity(store)
        username = identity.get("username")
    if not username:
        raise DiscogsNotConfigured("Discogs username not configured for this store.")
    client = _client(store)
    try:
        payload = client.get(f"/users/{username}/collection/releases/{int(release_id)}")
    except requests.HTTPError as exc:
        response = exc.response
        if response is not None and response.status_code == 404:
            return []
        raise
    return payload.get("releases", [])


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


def extract_artists(release: Dict[str, Any]) -> str:
    artists = release.get("artists") or []
    names = [artist.get("name") for artist in artists if artist.get("name")]
    return ", ".join(names) if names else "Unknown"


def update_listing_quantity(store: Dict[str, Any], listing_id: int, quantity: int) -> Dict[str, Any]:
    return update_listing(store, listing_id, {"quantity": max(0, int(quantity))})
