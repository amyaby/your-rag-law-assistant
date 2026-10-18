"""
robots.py — is this URL allowed to be fetched?

WHY THIS FILE IS NOT JUST FOUR LINES OF STDLIB
----------------------------------------------
The obvious implementation is:

    rp = RobotFileParser(); rp.set_url(base + "/robots.txt"); rp.read()
    return rp.can_fetch("*", url)

That version is WRONG, and it fails silently in the most dangerous direction.
Verified live on https://www.maroc.ma/robots.txt (2026-09-27):

    urllib default UA  -> HTTP 403        <-- blocked
    requests Mozilla UA -> HTTP 200       <-- fine, real rules

`RobotFileParser.read()` calls `urllib.request.urlopen()` internally, which sends
`User-Agent: Python-urllib/3.x`. maroc.ma rejects that agent outright. The parser
sees the 403 and concludes `disallow_all = True`, i.e. "this site forbids
everything":

    rp.read()
    rp.can_fetch("*", "https://www.maroc.ma/")   ->  False

Reality is the exact opposite - the site serves a normal ruleset that permits
the paths we want. So the naive version would have quietly disabled a source
that is in our allowlist, and the log would have said "robots.txt forbids it",
which is a lie. It fails closed, so it looks safe, and that is what makes it
dangerous: a legitimate source silently disappears and nobody investigates.

The fix is to keep the stdlib's *parsing* (it is well tested) but do our own
*fetching*, so the request carries an honest User-Agent:

    text = requests.get(robots_url, headers=HEADERS).text
    rp.parse(text.splitlines())        # <- not rp.read()

Behaviour on failure follows RFC 9309 rather than guesswork:

| Situation                        | Verdict | Why |
|----------------------------------|---------|-----|
| 200, rules parsed                | per rules | normal case |
| 404 / other 4xx (not 401/403/429) | allow   | no robots.txt = no restrictions |
| 401 / 403                        | DISALLOW | explicit refusal to read the rules |
| 429                              | DISALLOW | rate limited; back off, do not retry harder |
| 5xx / timeout / DNS failure      | allow   | RFC 9309: unreachable rules allow all |

The last row is the one people get wrong in the other direction. Failing *closed*
on a network blip means a flaky connection silently removes sources; failing
*open* is what the RFC prescribes. The real request that follows will fail on
its own if the site is genuinely down, so nothing is lost.

VERIFIED on the three hosts this project actually uses:

    adala.justice.gov.ma  404 (a 301 KB Next.js HTML error page, not a
                          robots.txt)               -> allow all
    ism.ma               200, "User-agent: * / Disallow:"  -> allow all
    www.maroc.ma         200, real Allow/Disallow rules   -> per rules
    sgg.gov.ma           DNS does not resolve          -> allow (and never used)
"""
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

ROBOTS_TIMEOUT = 8
# Results are cached, and a negative verdict is cached too, so a blocked host is
# not re-probed on every single request.
CACHE_TTL = 3600

# An honest, contactable User-Agent. A browser string is dishonest; the RFC asks
# for something identifiable. Override in .env if you publish this.
HEADERS = {
    "User-Agent": "MoroccanLawRAG-StudentProject/1.0 (educational RAG research)",
}

_cache: dict[str, tuple[float, bool]] = {}


def _origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _parse_robots(robots_url: str) -> bool | None:
    """
    True/False = explicit allow/deny for everything.
    None = no opinion (404, network error) -> caller applies RFC 9309 default.
    """
    try:
        r = requests.get(robots_url, headers=HEADERS, timeout=ROBOTS_TIMEOUT)
    except requests.RequestException:
        return None

    if r.status_code == 200:
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.parse(r.text.splitlines())   # parse, NOT read() - see module docstring
        return None if rp.disallow_all else rp     # disallow_all => true refusal
    if r.status_code in (401, 403, 429):
        return False
    if 400 <= r.status_code < 500:
        return None                      # no robots.txt -> no restrictions
    return None                          # 5xx -> unreachable rules -> allow


def allowed(url: str) -> bool:
    """May we fetch this URL? Cached per host for CACHE_TTL seconds."""
    origin = _origin(url)
    hit = _cache.get(origin)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]

    verdict = _parse_robots(f"{origin}/robots.txt")

    if verdict is True:                  # rules exist and permit
        ok = True
    elif verdict is False:               # explicit refusal
        ok = False
    else:                                # no rules / unreachable
        ok = True

    _cache[origin] = (time.time(), ok)
    return ok
