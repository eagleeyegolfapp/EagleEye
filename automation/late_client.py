#!/usr/bin/env python3
"""Late (Zernio) HTTP helper. One secret: LATE_API_KEY. Account IDs are discovered."""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
LATE_BASE = "https://getlate.dev/api/v1"
CTX = ssl.create_default_context()

PLATFORM_ENV = {
    "twitter": "LATE_TWITTER_ACCOUNT_ID",
    "x": "LATE_TWITTER_ACCOUNT_ID",
    "instagram": "LATE_INSTAGRAM_ACCOUNT_ID",
    "reddit": "LATE_REDDIT_ACCOUNT_ID",
    "facebook": "LATE_FACEBOOK_ACCOUNT_ID",
}


def api_key() -> str:
    key = (os.environ.get("LATE_API_KEY") or "").strip()
    if not key:
        raise SystemExit(
            "Missing LATE_API_KEY. Paste it into automation/.env "
            "(and GitHub secret LATE_API_KEY for when this Mac is off)."
        )
    return key


def headers(request_id: str | None = None) -> dict[str, str]:
    h = {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if request_id:
        h["x-request-id"] = request_id
    return h


def request(method: str, path: str, body: dict | None = None, request_id: str | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{LATE_BASE}{path}",
        data=data,
        headers=headers(request_id),
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=45, context=CTX) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode(errors="replace")
        raise RuntimeError(f"Late {method} {path} → HTTP {e.code}: {err[:800]}") from e


def list_profiles() -> list[dict]:
    data = request("GET", "/profiles")
    return data.get("profiles") or data.get("data") or []


def list_accounts(profile_id: str | None = None) -> list[dict]:
    path = "/accounts"
    if profile_id:
        path += f"?profileId={profile_id}"
    data = request("GET", path)
    return data.get("accounts") or data.get("data") or []


def _id_of(obj) -> str:
    if isinstance(obj, dict):
        return str(obj.get("_id") or obj.get("id") or "")
    return str(obj or "")


def resolve_accounts() -> dict[str, str]:
    """LATE_API_KEY is enough. Pulls profile + X/IG/Reddit account ids."""
    profiles = list_profiles()
    profile_id = (os.environ.get("LATE_PROFILE_ID") or "").strip()
    if not profile_id and profiles:
        default = next((p for p in profiles if p.get("isDefault")), profiles[0])
        profile_id = _id_of(default)
    accounts = list_accounts(profile_id or None)
    found: dict[str, str] = {}
    if profile_id:
        found["LATE_PROFILE_ID"] = profile_id
        os.environ["LATE_PROFILE_ID"] = profile_id
    for acc in accounts:
        if acc.get("isActive") is False:
            continue
        plat = str(acc.get("platform") or "").lower()
        env_name = PLATFORM_ENV.get(plat)
        if not env_name:
            continue
        acc_id = _id_of(acc)
        if not acc_id:
            continue
        found[env_name] = acc_id
        os.environ[env_name] = acc_id
        print(f"  Late account {plat:10} {acc.get('username') or acc.get('displayName') or ''} → {acc_id}")
    need = ["LATE_TWITTER_ACCOUNT_ID", "LATE_INSTAGRAM_ACCOUNT_ID", "LATE_REDDIT_ACCOUNT_ID"]
    missing = [n for n in need if not os.environ.get(n)]
    if missing:
        raise SystemExit(
            "Late is missing connected accounts: "
            + ", ".join(missing)
            + ". Connect X, Instagram (Business), and Reddit in the Late dashboard."
        )
    return found


def persist_ids(found: dict[str, str], env_path: Path | None = None) -> None:
    """Write discovered ids back to local .env. No-op on GitHub Actions."""
    if os.environ.get("GITHUB_ACTIONS"):
        return
    path = env_path or (HERE / ".env")
    if not path.exists():
        return
    lines = path.read_text().splitlines()
    keys = set(found)
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        raw = line.strip()
        if raw and not raw.startswith("#") and "=" in line:
            k = line.split("=", 1)[0].strip()
            if k in found:
                out.append(f"{k}={found[k]}")
                seen.add(k)
                continue
        out.append(line)
    for k in keys - seen:
        out.append(f"{k}={found[k]}")
    path.write_text("\n".join(out) + "\n")
    os.chmod(path, 0o600)


def create_post(payload: dict, idempotency_key: str | None = None) -> dict:
    rid = idempotency_key or str(uuid.uuid4())
    return request("POST", "/posts", payload, request_id=rid)


def presign_and_upload(blob: bytes, filename: str, content_type: str = "image/jpeg") -> str:
    data = request(
        "POST",
        "/media/presign",
        {"filename": filename, "contentType": content_type},
    )
    upload_url = data.get("uploadUrl") or data.get("upload_url")
    public_url = data.get("publicUrl") or data.get("public_url")
    if not upload_url or not public_url:
        raise RuntimeError(f"Unexpected presign response: {data}")
    req = urllib.request.Request(
        upload_url,
        data=blob,
        method="PUT",
        headers={"Content-Type": content_type},
    )
    with urllib.request.urlopen(req, timeout=180, context=CTX):
        pass
    return public_url


def delete_post(post_id: str) -> dict:
    return request("DELETE", f"/posts/{post_id}")


def search_tweets(account_id: str, query: str, limit: int = 10) -> list[dict]:
    """Recent X search via Late. Operators pass through (from:, has:videos, …)."""
    if not account_id or not query:
        return []
    q = urllib.parse.quote(query)
    n = max(10, min(int(limit or 10), 100))
    data = request(
        "GET",
        f"/twitter/search?accountId={account_id}&query={q}&limit={n}&sortOrder=recency",
    )
    return data.get("tweets") or []


def list_posts(status: str | None = None, search: str | None = None, limit: int = 20) -> list[dict]:
    q = [f"limit={limit}"]
    if status:
        q.append(f"status={status}")
    if search:
        q.append(f"search={urllib.parse.quote(search)}")
    data = request("GET", "/posts?" + "&".join(q))
    return data.get("posts") or []
