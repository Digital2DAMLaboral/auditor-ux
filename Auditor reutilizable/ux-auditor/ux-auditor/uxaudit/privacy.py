"""Rastreo antes del consentimiento y huella de carbono (datos de red ya recogidos)."""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlsplit

from .security import clean_text, redact_url

# Dominios de analítica y publicidad que requieren consentimiento previo (RGPD art. 6/7, LSSI art. 22.2).
TRACKER_DOMAINS = (
    "google-analytics.com", "analytics.google.com", "googletagmanager.com", "doubleclick.net",
    "googleadservices.com", "googlesyndication.com", "adservice.google.com", "connect.facebook.net",
    "hotjar.com", "hotjar.io", "clarity.ms", "bat.bing.com", "analytics.tiktok.com", "snap.licdn.com",
    "px.ads.linkedin.com", "ads-twitter.com", "analytics.twitter.com", "criteo.com", "criteo.net",
    "taboola.com", "outbrain.com", "cdn.segment.com", "api.segment.io", "mixpanel.com", "amplitude.com",
    "fullstory.com", "mouseflow.com", "crazyegg.com", "quantserve.com", "scorecardresearch.com",
    "adnxs.com", "rubiconproject.com", "pubmatic.com", "mc.yandex.ru", "yandex.ru/metrika",
    "tr.snapchat.com", "ct.pinterest.com", "s.pinimg.com/ct", "static.hotjar.com", "smartlook.com",
)
TRACKING_COOKIES = ("_ga", "_gid", "_gat", "_gcl_au", "_fbp", "_fbc", "_hjsession", "_hjid", "_clck", "_clsk",
                    "_uetsid", "_uetvid", "_ttp", "_pin_unauth", "ajs_anonymous_id", "mp_", "amplitude_id", "_ym_")
_MULTI_TLD = {"co", "com", "org", "gob", "gov", "ac", "edu", "net", "nom"}

# Sustainable Web Design Model v4 (sustainablewebdesign.org): 0,300 kWh/GB · 494 gCO2e/kWh (media mundial).
SWD_KWH_PER_GB = 0.055 + 0.012 + 0.059 + 0.013 + 0.080 + 0.081
SWD_GRID_G_PER_KWH = 494
CARBON_RATINGS = ((0.040, "A+"), (0.079, "A"), (0.145, "B"), (0.209, "C"), (0.278, "D"), (0.359, "E"))


def site_domain(host: str) -> str:
    parts = [p for p in (host or "").lower().strip(".").split(".") if p]
    if len(parts) >= 3 and parts[-2] in _MULTI_TLD and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _matches_tracker(url: str) -> Optional[str]:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    target = host + parts.path.lower()
    for domain in TRACKER_DOMAINS:
        if "/" in domain:
            if target.startswith(domain) or ("." + domain) in ("." + target):
                return domain
        elif host == domain or host.endswith("." + domain):
            return domain
    if host.endswith("facebook.com") and parts.path.startswith("/tr"):
        return "facebook.com/tr"
    return None


def trackers_before_consent(network: list[dict[str, Any]], cookies: list[dict[str, Any]], page_host: str) -> dict[str, Any]:
    own = site_domain(page_host)
    hits: list[dict[str, str]] = []
    seen = set()
    for res in network[:3000]:
        if not isinstance(res, dict):
            continue
        match = _matches_tracker(str(res.get("url", "")))
        if match and match not in seen:
            seen.add(match)
            hits.append({"s": redact_url(str(res.get("url", ""))), "d": f"petición a {match} antes de cualquier consentimiento"})
    for c in cookies[:500]:
        if not isinstance(c, dict):
            continue
        name = clean_text(c.get("name"), 80)
        domain = clean_text(c.get("domain"), 120).lstrip(".").lower()
        third = bool(own) and not (domain == own or domain.endswith("." + own))
        tracking = any(name.lower().startswith(p) for p in TRACKING_COOKIES)
        if (third or tracking) and (name, domain) not in seen:
            seen.add((name, domain))
            kind = "de terceros" if third else "de analítica/publicidad"
            hits.append({"s": f"cookie {name}", "d": f"cookie {name} {kind} ({domain}) instalada sin consentimiento"})
    return {"count": len(hits), "items": hits[:25]}


def carbon_grams(total_bytes: int) -> tuple[float, str]:
    grams = total_bytes / 1e9 * SWD_KWH_PER_GB * SWD_GRID_G_PER_KWH
    rating = next((name for limit, name in CARBON_RATINGS if grams <= limit), "F")
    return round(grams, 3), rating
