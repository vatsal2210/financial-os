"""Check GitHub for new versions. Runs once per day, fully local cache."""
import json
import urllib.request
from datetime import datetime, timedelta
from database import get_setting, set_setting
from version import VERSION

REPO = "vatsal2210/financial-os"
CHECK_INTERVAL_HOURS = 24


def check_for_update() -> dict:
    """Return update info. Checks GitHub at most once per day."""
    last_check = get_setting("update_last_check", "")
    cached_version = get_setting("update_latest_version", "")
    cached_url = get_setting("update_latest_url", "")

    # Use cache if checked recently
    if last_check:
        try:
            last_dt = datetime.fromisoformat(last_check)
            if datetime.now() - last_dt < timedelta(hours=CHECK_INTERVAL_HOURS):
                if cached_version and cached_version != VERSION:
                    return {
                        "available": True,
                        "current": VERSION,
                        "latest": cached_version,
                        "url": cached_url,
                    }
                return {"available": False, "current": VERSION}
        except ValueError:
            pass

    # Fetch from GitHub
    try:
        url = f"https://api.github.com/repos/{REPO}/releases/latest"
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.v3+json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())

        latest_tag = data.get("tag_name", "").lstrip("v")
        release_url = data.get("html_url", f"https://github.com/{REPO}/releases/latest")

        # Cache result
        set_setting("update_last_check", datetime.now().isoformat())
        set_setting("update_latest_version", latest_tag)
        set_setting("update_latest_url", release_url)

        if latest_tag and latest_tag != VERSION and _is_newer(latest_tag, VERSION):
            return {
                "available": True,
                "current": VERSION,
                "latest": latest_tag,
                "url": release_url,
            }
    except Exception:
        pass  # Offline or rate-limited — silently skip

    return {"available": False, "current": VERSION}


def _is_newer(latest: str, current: str) -> bool:
    """Compare semver strings. Returns True if latest > current."""
    try:
        l_parts = [int(x) for x in latest.split(".")]
        c_parts = [int(x) for x in current.split(".")]
        return l_parts > c_parts
    except (ValueError, AttributeError):
        return False
