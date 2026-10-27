"""TA audit for Assignment 1 (URL shortener): find every problem worth a question.

    python audit_a1.py --url http://HOST:PORT [--report findings.md] [--quick]

This is not the students' grading script. It tries far more cases than
shared/tests/test_api.py, including input that the specification does not
mention, and reports each problem with the request and answer that show it.
FAIL is a violation of the assignment or a bug, WARN a questionable choice to
discuss in the oral exam, INFO an observation. See README.md.

The audit creates many mappings and ends with DELETE /, which (as the course
defines it) removes every mapping in the service: use a test instance.
"""
import argparse
import base64
import concurrent.futures
import hashlib
import sys
import time
from urllib.parse import quote

from audit_common import (
    Client, Context, ServiceUnreachable, base62_length, gives_url, is_5xx, listed, print_report,
    registry, returned_id, run_checks, same_url, shorten, target_of, wait_for, write_json, write_markdown,
)

CHECKS, check = registry()

SPEC = "The specification table of Assignment 1"

# The URLs of the course's read_from.csv and test script: all valid.
COURSE_URLS = [
    "https://en.wikipedia.org/wiki/Dijkstra's_algorithm", "https://en.wikipedia.org/wiki/Ducati",
    "https://en.wikipedia.org/wiki/Caproni", "https://en.wikipedia.org/wiki/Shortest_path_problem",
    "https://en.wikipedia.org/wiki/Cagiva", "https://en.wikipedia.org/wiki/Leonardo_S.p.A.",
    "https://en.wikipedia.org/wiki/Bellman–Ford_algorithm", "https://en.wikipedia.org/wiki/Desmodromic_valve",
    "https://en.wikipedia.org/wiki/AgustaWestland", "https://en.wikipedia.org/wiki/Network_topology",
    "https://en.wikipedia.org/wiki/Clutch#Dry_clutch", "https://en.wikipedia.org/wiki/Alenia_Aermacchi",
    "https://en.wikipedia.org/wiki/Physical_layer", "https://en.wikipedia.org/wiki/Manual_transmission",
    "https://en.wikipedia.org/wiki/OTO_Melara", "https://en.wikipedia.org/wiki/Bitstream",
    "https://en.wikipedia.org/wiki/Torque_converter", "https://en.wikipedia.org/wiki/Saab_AB",
    "https://en.wikipedia.org/wiki/Docker_(software)",
]
VALID_URLS = COURSE_URLS + [
    "https://www.uva.nl",
    "http://example.com/",
    "https://www.uva.nl/en/education?lang=en&page=2#programmes",
    "https://sub.domain.example.co.uk/a/b/c.html",
    "https://example.com/%E2%82%AC/price",
]
# Valid but less common: rejecting them is debatable.
UNCOMMON_VALID_URLS = [
    "HTTPS://WWW.UVA.NL/",
    "http://example.com:8080/index.html",
    "http://127.0.0.1:5000/status",
    "http://localhost:8080/",
    "https://xn--bcher-kva.example/",
    "https://example.com/a_(b)",
    "https://example.com/" + "a" * 2000,
]
# Not URLs under any interpretation: every sensible check rejects them.
INVALID_URLS = [
    "htInvalid_url/", "not a url", "http//example.com", "://example.com", "http:/example.com",
    "http://", "https://", "https://exa mple.com", "javascript:alert(1)", "data:text/html,<b>x</b>",
]
# Questionable: most validators reject them, some reasonable ones do not.
QUESTIONABLE_URLS = [
    "www", "http://example", "http://example..com", "http://-example.com",
    "http://example.com:99999/", "http://256.256.256.256/", "https://example.com/a b",
    "http://exa_mple.com",
]
CONTROL_CHARACTER_URLS = [
    "https://example.com/a\r\nSet-Cookie: audit=1", "https://example.com/\tx",
    "https://exa\nmple.com/", "https://example.com/\u0000",
]
NON_STRING_VALUES = [123, None, ["https://www.uva.nl"], {"url": "https://www.uva.nl"}, True]


class ShortenerContext(Context):
    """Context for the shortener checks.

    api sends the requests that need authentication (in Assignment 2 it carries
    a token), public the ones that do not (GET /:id).
    """

    def __init__(self, api, public, many=1000, collision_search=True):
        super().__init__()
        self.api = api
        self.public = public
        self.many = many
        self.collision_search = collision_search
        self.created = 0

    def create(self, url, require=True):
        response = self.api.post("/", {"value": url})
        short_id = returned_id(response) if response.status == 201 else None
        if short_id is not None:
            self.created += 1
        elif require:
            self.skip(f"POST / did not create a mapping, see METHOD-01 ({shorten(response.exchange, 200)})")
        return short_id, response

    def resolve(self, short_id):
        return self.public.get("/" + quote(short_id, safe="-._~"))

    def points_to(self, short_id, url):
        response = self.resolve(short_id)
        return gives_url(response, url), response

    def keys(self):
        response = self.api.get("/")
        return listed(response.json()), response


@check("METHOD-01", "Methods", "POST / with a valid URL answers 201 and an identifier",
       why=f"{SPEC} lists 201 with the id for POST /.",
       ask="Show how POST / creates a mapping and what it returns.")
def method_post(ctx):
    response = ctx.api.post("/", {"value": ctx.url("post")})
    if response.status != 201:
        ctx.problem(f"expected 201, got {response.status}", response)
    elif not returned_id(response):
        ctx.problem("201, but no identifier found in the answer", response)


@check("METHOD-02", "Methods", "GET /:id answers 301 and gives the stored URL",
       why=f"{SPEC} lists 301 with the value for GET /:id.",
       ask="Show GET /:id: which status, and where is the URL in the answer?")
def method_get(ctx):
    url = ctx.url("get")
    short_id, _ = ctx.create(url)
    response = ctx.resolve(short_id)
    if response.status != 301:
        ctx.problem(f"expected 301, got {response.status}", response)
    elif not gives_url(response, url):
        ctx.problem(f"the answer gives {target_of(response)!r}, expected {url!r}", response)


@check("METHOD-03", "Methods", "301 answers have a Location header, so browsers follow them",
       severity="WARN",
       why="A 301 without Location is not a redirect: a browser shows the body instead of going to the URL. "
           "The course test accepts either, so this is a design point, not a spec violation.",
       ask="What does a browser do with your 301 answer? Why did you choose this?")
def method_location(ctx):
    short_id, _ = ctx.create(ctx.url("location"))
    response = ctx.resolve(short_id)
    if response.status == 301 and not response.headers.get("Location"):
        ctx.problem("the 301 answer has no Location header", response)


@check("METHOD-04", "Methods", "A Location header holds the absolute stored URL",
       why="A relative or different Location sends the browser to the wrong place.",
       ask="Where does your Location header come from?")
def method_location_value(ctx):
    url = ctx.url("location-value") + "?q=1#part"
    short_id, _ = ctx.create(url)
    response = ctx.resolve(short_id)
    location = response.headers.get("Location")
    if location and not same_url(location, url):
        ctx.problem(f"Location is {location!r}, expected {url!r}", response)


@check("METHOD-05", "Methods", "GET /:id answers 404 for an unknown identifier",
       why=f"{SPEC} lists 404 for GET /:id.", ask="When does GET /:id answer 404?")
def method_get_unknown(ctx):
    response = ctx.public.get(f"/unknown{ctx.run}x")
    if response.status != 404:
        ctx.problem(f"expected 404, got {response.status}", response)


@check("METHOD-06", "Methods", "PUT /:id with a valid URL answers 200 and changes the target",
       why=f"{SPEC} lists 200 for PUT /:id.", ask="Show PUT /:id: what does it change?")
def method_put(ctx):
    short_id, _ = ctx.create(ctx.url("put-before"))
    new_url = ctx.url("put-after")
    response = ctx.api.put("/" + quote(short_id, safe=""), {"url": new_url})
    if response.status != 200:
        ctx.problem(f"expected 200, got {response.status}", response)
        return
    ok, answer = ctx.points_to(short_id, new_url)
    if not ok:
        ctx.problem("after PUT, GET /:id does not give the new URL", answer)


@check("METHOD-07", "Methods", "PUT /:id with an invalid URL answers 400 and keeps the old URL",
       why=f"{SPEC} lists 400 \"error\" for PUT /:id.",
       ask="How does PUT /:id validate the URL? Show it with 'htInvalid_url/'.")
def method_put_invalid(ctx):
    url = ctx.url("put-invalid")
    short_id, _ = ctx.create(url)
    for value in ("htInvalid_url/", "not a url"):
        response = ctx.api.put("/" + quote(short_id, safe=""), {"url": value})
        if response.status != 400:
            ctx.problem(f"PUT with {value!r}: expected 400, got {response.status}", response)
    ok, answer = ctx.points_to(short_id, url)
    if not ok:
        ctx.problem("an invalid PUT changed or removed the mapping", answer)


@check("METHOD-08", "Methods", "PUT /:id for an unknown identifier answers 404",
       why=f"{SPEC} lists 404 for PUT /:id.", ask="What does PUT do for an id that does not exist?")
def method_put_unknown(ctx):
    response = ctx.api.put(f"/unknown{ctx.run}x", {"url": ctx.url("put-unknown")})
    if response.status != 404:
        ctx.problem(f"expected 404, got {response.status}", response)
    if ctx.public.get(f"/unknown{ctx.run}x").status != 404:
        ctx.problem("PUT on an unknown id created a mapping")


@check("METHOD-09", "Methods", "DELETE /:id answers 204; afterwards GET and DELETE answer 404",
       why=f"{SPEC} lists 204 and 404 for DELETE /:id.", ask="Show DELETE /:id.")
def method_delete(ctx):
    short_id, _ = ctx.create(ctx.url("delete"))
    path = "/" + quote(short_id, safe="")
    response = ctx.api.delete(path)
    if response.status != 204:
        ctx.problem(f"DELETE: expected 204, got {response.status}", response)
    response = ctx.resolve(short_id)
    if response.status != 404:
        ctx.problem(f"GET after DELETE: expected 404, got {response.status}", response)
    response = ctx.api.delete(path)
    if response.status != 404:
        ctx.problem(f"second DELETE: expected 404, got {response.status}", response)


@check("METHOD-10", "Methods", "204 answers have no body", severity="WARN",
       why="HTTP forbids a body in a 204 answer; clients may misread the next answer.",
       ask="What does your DELETE /:id return as body?")
def method_delete_body(ctx):
    short_id, _ = ctx.create(ctx.url("delete-body"))
    response = ctx.api.delete("/" + quote(short_id, safe=""))
    if response.status == 204 and response.text.strip():
        ctx.problem("the 204 answer has a body", response)


@check("METHOD-11", "Methods", "GET / answers 200 and lists the identifiers",
       why=f"{SPEC} lists 200 with the keys for GET /.", ask="What does GET / return?")
def method_list(ctx):
    created = {}
    for name in ("list-a", "list-b"):
        url = ctx.url(name)
        created[ctx.create(url)[0]] = url
    keys, response = ctx.keys()
    if response.status != 200:
        ctx.problem(f"expected 200, got {response.status}", response)
        return
    missing = [short_id for short_id, url in created.items() if short_id not in keys and url not in keys]
    if missing:
        ctx.problem(f"GET / does not list {missing}", response)


@check("METHOD-12", "Methods", "DELETE / answers 404",
       why=f"{SPEC} lists only 404 for DELETE /.", ask="Why 404, and what does DELETE / do?")
def method_delete_all_status(ctx):
    ctx.create(ctx.url("delete-all-status"))
    response = ctx.api.delete("/")
    if response.status != 404:
        ctx.problem(f"expected 404, got {response.status}", response)


@check("METHOD-13", "Methods", "DELETE / removes the mappings",
       why="The course test script defines DELETE / as \"Deletes all ID/URL pairs\" (returning 404). "
           "In Assignment 2 it removes the caller's mappings.",
       ask="What does DELETE / delete in your service?")
def method_delete_all(ctx):
    created = {ctx.create(ctx.url(name))[0]: ctx.url(name) for name in ("all-a", "all-b")}
    ctx.api.delete("/")
    keys, response = ctx.keys()
    left = [short_id for short_id, url in created.items() if short_id in keys or url in keys]
    if left:
        ctx.problem(f"GET / still lists {left} after DELETE /", response)
    for short_id in created:
        answer = ctx.resolve(short_id)
        if answer.status != 404:
            ctx.problem(f"GET /{short_id} after DELETE /: expected 404, got {answer.status}", answer)


@check("METHOD-14", "Methods", "POST / with an empty or missing URL answers 400",
       why=f"{SPEC} lists 400 \"error\" for POST /.", ask="How does POST / handle a missing URL?")
def method_post_empty(ctx):
    for body in ({"value": ""}, {}, {"value": "   "}):
        response = ctx.api.post("/", body)
        if response.status != 400:
            ctx.problem(f"POST {body}: expected 400, got {response.status}", response)
    response = ctx.api.request("POST", "/")
    if not 400 <= response.status < 500:
        ctx.problem(f"POST without a body: expected a 4xx answer, got {response.status}", response)


@check("METHOD-15", "Methods", "400 answers say what is wrong", severity="WARN",
       why=f"{SPEC} lists 400 with an \"error\" value; an empty answer does not tell the client anything.",
       ask="What does a client see when its URL is rejected?")
def method_error_body(ctx):
    response = ctx.api.post("/", {"value": "not a url"})
    if response.status == 400 and not response.text.strip():
        ctx.problem("the 400 answer is empty", response)


@check("ID-01", "Identifiers", "Many different URLs get different identifiers that each lead to their own URL",
       why="Assignment 1 maps every URL to a unique identifier (rubric: unique ID without conflicts).",
       ask="Explain your identifier algorithm. How do you guarantee uniqueness?")
def ids_unique(ctx):
    pairs = []
    for number in range(ctx.many):
        url = ctx.url(f"many-{number}")
        short_id, _ = ctx.create(url)
        pairs.append((url, short_id))
    ctx.shared["many"] = pairs
    seen = {}
    for url, short_id in pairs:
        if short_id in seen:
            ctx.problem(f"{url!r} and {seen[short_id]!r} both got the id {short_id!r}")
        seen[short_id] = url
    wrong = 0
    for url, short_id in pairs:
        ok, response = ctx.points_to(short_id, url)
        if not ok:
            wrong += 1
            if wrong <= 3:
                ctx.problem(f"/{short_id} does not lead to {url!r}", response)
    if wrong > 3:
        ctx.problem(f"... {wrong} of {len(pairs)} identifiers do not lead to their URL")


@check("ID-02", "Identifiers", "After a delete, a new URL never takes the identifier of an existing mapping",
       why="Schemes such as len(store) + 1 hand out an identifier that is still in use, overwriting a mapping.",
       ask="What happens to your counter or hash after a delete?")
def ids_after_delete(ctx):
    urls = {name: ctx.url(f"conflict-{name}") for name in "abcdefg"}
    ids = {name: ctx.create(urls[name])[0] for name in "abc"}
    ctx.api.delete("/" + quote(ids["b"], safe=""))
    for name in "defg":
        ids[name] = ctx.create(urls[name])[0]
    for name in "defg":
        if ids[name] in (ids["a"], ids["c"]):
            ctx.problem(f"{urls[name]!r} got {ids[name]!r}, which already belongs to another mapping")
    for name in "acdefg":
        ok, response = ctx.points_to(ids[name], urls[name])
        if not ok:
            ctx.problem(f"/{ids[name]} no longer leads to {urls[name]!r}", response)


@check("ID-03", "Identifiers", "The identifier of a deleted mapping is not handed out again", severity="WARN",
       why="If a deleted identifier is reused, old short links silently lead to someone else's URL.",
       ask="Can an old short link ever lead to a different URL? Is that acceptable?")
def ids_not_reused(ctx):
    deleted, _ = ctx.create(ctx.url("reuse-deleted"))
    ctx.api.delete("/" + quote(deleted, safe=""))
    for number in range(30):
        short_id, _ = ctx.create(ctx.url(f"reuse-new-{number}"))
        if short_id == deleted:
            ctx.problem(f"the deleted identifier {deleted!r} was handed out again after {number + 1} new URLs")
            return


@check("ID-04", "Identifiers", "Identifiers stay unique when URLs are created concurrently",
       why="The Flask development server handles requests in threads; an unprotected counter or "
           "check-then-insert can give two URLs the same identifier.",
       ask="What happens when two requests create a mapping at the same moment?")
def ids_concurrent(ctx):
    urls = [ctx.url(f"parallel-{number}") for number in range(100)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda url: ctx.create(url, require=False), urls))
    ids = [short_id for short_id, _ in results]
    failed = [response for short_id, response in results if short_id is None]
    if failed:
        ctx.problem(f"{len(failed)} of {len(urls)} concurrent POSTs failed", failed[0])
    created = [short_id for short_id in ids if short_id]
    duplicates = len(created) - len(set(created))
    if duplicates:
        ctx.problem(f"{duplicates} identifiers were handed out twice among {len(created)} concurrent POSTs")
    wrong = [(url, short_id) for url, short_id in zip(urls, ids)
             if short_id and not ctx.points_to(short_id, url)[0]]
    if wrong:
        ctx.problem(f"{len(wrong)} concurrently created identifiers lead to the wrong URL, e.g. /{wrong[0][1]}")


HASH_NAMES = ("md5", "sha1", "sha224", "sha256", "sha384", "sha512", "blake2b", "blake2s")


def to_base62(number):
    digits = ""
    while True:
        number, remainder = divmod(number, 62)
        digits = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"[remainder] + digits
        if number == 0:
            return digits


ENCODINGS = {
    "hex": (4, lambda digest: digest.hex()),
    "HEX": (4, lambda digest: digest.hex().upper()),
    "base64url": (6, lambda digest: base64.urlsafe_b64encode(digest).decode().rstrip("=")),
    "base64": (6, lambda digest: base64.b64encode(digest).decode().rstrip("=")),
    "base62": (5.95, lambda digest: to_base62(int.from_bytes(digest, "big"))),
}


def hashed(name, encoding, text):
    return ENCODINGS[encoding][1](hashlib.new(name, text.encode("utf-8")).digest())


def detect_hash_scheme(pairs):
    """(hash, encoding, length) if every identifier is a prefix of that hash of its URL."""
    samples = [(url, short_id) for url, short_id in pairs if short_id][:5]
    if len(samples) < 3 or len({len(short_id) for _, short_id in samples}) != 1:
        return None
    length = len(samples[0][1])
    if length < 3:
        return None
    for name in HASH_NAMES:
        for encoding in ENCODINGS:
            if all(hashed(name, encoding, url)[:length] == short_id for url, short_id in samples):
                return name, encoding, length
    return None


def find_collision(name, encoding, length, prefix, attempts=400000):
    seen = {}
    for number in range(attempts):
        url = f"{prefix}{number}"
        key = hashed(name, encoding, url)[:length]
        if key in seen:
            return f"{prefix}{seen[key]}", url
        seen[key] = number
    return None


@check("ID-05", "Identifiers", "Two URLs whose hashes collide still get separate mappings",
       why="Truncated hashes collide (24 bits after ~5,000 URLs on average). Without collision "
           "handling the second URL overwrites the first or gets the first one's identifier.",
       ask="Your identifiers are truncated hashes. What happens when two URLs hash to the same prefix?")
def ids_hash_collision(ctx):
    pairs = ctx.shared.get("many") or []
    scheme = detect_hash_scheme(pairs)
    if scheme is None:
        ctx.skip("the identifiers are not a truncated hash of the URL, so no collision was constructed")
    name, encoding, length = scheme
    bits = ENCODINGS[encoding][0] * length
    ctx.observe(f"identifiers are the first {length} characters of the {encoding} {name} of the URL ({bits:.0f} bits)")
    if not ctx.collision_search or bits > 32:
        ctx.skip(f"identifiers are the first {length} {encoding} characters of {name}(URL); "
                 f"a collision needs about 2^{bits / 2:.0f} URLs, not searched — ask how collisions are handled")
    pair = find_collision(name, encoding, length, ctx.url("collision-"))
    if pair is None:
        ctx.skip("no collision found within the search budget")
    first, second = pair
    first_id, _ = ctx.create(first)
    second_id, response = ctx.create(second)
    ok_first, answer_first = ctx.points_to(first_id, first)
    ok_second, answer_second = ctx.points_to(second_id, second)
    if first_id == second_id:
        ctx.problem(f"{first!r} and {second!r} (same {name} prefix) got the same id {first_id!r}", response)
    if not ok_first:
        ctx.problem(f"after the colliding URL was added, /{first_id} no longer leads to {first!r}", answer_first)
    if not ok_second:
        ctx.problem(f"/{second_id} does not lead to the colliding URL {second!r}", answer_second)


@check("ID-06", "Identifiers", "Identifiers are as short as possible", severity="WARN",
       why="Assignment 1 asks for identifiers that are as short as possible (rubric: report, hash function).",
       ask="How long are your identifiers after N URLs, and what is the minimum possible?")
def ids_short(ctx):
    pairs = [(url, short_id) for url, short_id in ctx.shared.get("many") or [] if short_id]
    if not pairs:
        ctx.skip("no identifiers from ID-01")
    longest = max(len(short_id) for _, short_id in pairs)
    needed = base62_length(ctx.created)
    symbols = set("".join(short_id for _, short_id in pairs))
    if longest > needed + 1:
        ctx.problem(f"identifiers are up to {longest} characters after {ctx.created} new URLs; "
                    f"{needed} characters suffice with 62 symbols")
    if symbols <= set("0123456789abcdef") and len(pairs) > 20:
        ctx.problem("identifiers use only hexadecimal digits (16 symbols); 62 URL-safe symbols give shorter ones")


@check("ID-07", "Identifiers", "Identifiers contain only characters that are safe in a URL path", severity="WARN",
       why="Characters such as / ? # % + or spaces must be encoded in a URL; short links then break or look odd.",
       ask="Which characters can your identifiers contain?")
def ids_url_safe(ctx):
    pairs = ctx.shared.get("many") or []
    unsafe = sorted({short_id for _, short_id in pairs if short_id and not all(
        char.isalnum() and char.isascii() or char in "-._~" for char in short_id)})
    if unsafe:
        ctx.problem(f"{len(unsafe)} identifiers need encoding, e.g. {unsafe[:3]}")


@check("ID-08", "Identifiers", "Observations on the identifiers", severity="INFO")
def ids_observations(ctx):
    pairs = [short_id for _, short_id in ctx.shared.get("many") or [] if short_id]
    if not pairs:
        ctx.skip("no identifiers from ID-01")
    lengths = sorted(len(short_id) for short_id in pairs)
    ctx.observe(f"{len(pairs)} new identifiers, {lengths[0]} to {lengths[-1]} characters, e.g. {pairs[:5]}")
    numeric = [int(short_id) for short_id in pairs if short_id.isdigit()]
    if len(numeric) == len(pairs) and numeric == sorted(numeric):
        ctx.observe("identifiers are increasing numbers: anyone can enumerate all short links")
    elif all(char in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ" for char in "".join(pairs)):
        ctx.observe("identifiers use the 62 alphanumeric symbols")
    url = ctx.url("same-twice")
    first, _ = ctx.create(url)
    second, _ = ctx.create(url)
    ctx.observe("the same URL posted twice got " + ("the same identifier" if first == second else "two identifiers"))


@check("URL-01", "URL validation", "POST / rejects strings that are not URLs (400)",
       why="Assignment 1 (full points): check URL validity with a regular expression before creating a mapping.",
       ask="Show your regular expression. Why does it accept this input?")
def url_post_invalid(ctx):
    for value in INVALID_URLS:
        response = ctx.api.post("/", {"value": value})
        if response.status != 400:
            ctx.problem(f"{value!r}: expected 400, got {response.status}", response)


@check("URL-02", "URL validation", "PUT /:id rejects strings that are not URLs (400) and keeps the old URL",
       why=f"{SPEC} lists 400 \"error\" for PUT /:id; the full-points regex applies to updates too.",
       ask="Does PUT use the same validation as POST?")
def url_put_invalid(ctx):
    url = ctx.url("put-validation")
    short_id, _ = ctx.create(url)
    for value in INVALID_URLS:
        response = ctx.api.put("/" + quote(short_id, safe=""), {"url": value})
        if response.status != 400:
            ctx.problem(f"PUT {value!r}: expected 400, got {response.status}", response)
    ok, response = ctx.points_to(short_id, url)
    if not ok:
        ctx.problem("rejected updates changed the mapping", response)


@check("URL-03", "URL validation", "URLs with control characters (newline, tab, NUL) are rejected",
       why="A URL with CR/LF that reaches a Location header can inject headers; it is never a valid URL.",
       ask="What does your regex do with a newline in the URL?")
def url_control_characters(ctx):
    for value in CONTROL_CHARACTER_URLS:
        response = ctx.api.post("/", {"value": value})
        if response.status != 400:
            ctx.problem(f"{value!r}: expected 400, got {response.status}", response)


@check("URL-04", "URL validation", "Ordinary valid URLs are accepted and stored exactly",
       why="A validator that rejects valid URLs (unicode, apostrophes, fragments, queries, "
           "percent-encoding) breaks the service for real users; the course's own URLs are among them.",
       ask="Why does your regex reject this URL?")
def url_valid(ctx):
    for value in VALID_URLS:
        short_id, response = ctx.create(value, require=False)
        if short_id is None:
            ctx.problem(f"{value!r} was rejected ({response.status})", response)
            continue
        ok, answer = ctx.points_to(short_id, value)
        if not ok:
            ctx.problem(f"{value!r} is not given back exactly", answer)


@check("URL-05", "URL validation", "Less common valid URLs are accepted", severity="WARN",
       why="These are valid URLs (upper case, ports, IP addresses, localhost, punycode, parentheses, long "
           "paths); rejecting them is a defensible choice only if the students can explain it.",
       ask="Your regex rejects this valid URL. Was that deliberate?")
def url_uncommon_valid(ctx):
    for value in UNCOMMON_VALID_URLS:
        short_id, response = ctx.create(value, require=False)
        if short_id is None:
            ctx.problem(f"{shorten(value, 80)!r} was rejected ({response.status})", response)


@check("URL-06", "URL validation", "Questionable input is rejected", severity="WARN",
       why="These strings are not valid URLs (no top-level domain, empty or invalid labels, impossible "
           "ports or IP addresses, spaces), but simple patterns accept them.",
       ask="Your regex accepts this. Is it a valid URL?")
def url_questionable(ctx):
    for value in QUESTIONABLE_URLS:
        response = ctx.api.post("/", {"value": value})
        if response.ok:
            ctx.problem(f"{value!r} was accepted ({response.status})", response)


@check("URL-07", "URL validation", "A URL without scheme (uva.nl) is rejected or completed, never stored as is",
       why="The rubric names \"uva.nl\" as an extempore test. Stored as is, the redirect is relative "
           "and leads to /uva.nl on the shortener itself.",
       ask="What happens with 'uva.nl'? Where does the redirect lead?")
def url_without_scheme(ctx):
    response = ctx.api.post("/", {"value": "uva.nl"})
    if response.status == 400:
        return
    short_id = returned_id(response)
    if response.status != 201 or not short_id:
        ctx.problem(f"expected 400 or 201, got {response.status}", response)
        return
    answer = ctx.resolve(short_id)
    target = target_of(answer) or ""
    if not target.lower().startswith(("http://uva.nl", "https://uva.nl")):
        ctx.problem(f"'uva.nl' was stored as {target!r}", answer)


@check("URL-08", "URL validation", "Other schemes (ftp, mailto)", severity="INFO")
def url_other_schemes(ctx):
    for value in ("ftp://example.com/file.txt", "mailto:someone@example.com"):
        response = ctx.api.post("/", {"value": value})
        ctx.observe(f"{value!r}: {'accepted' if response.ok else 'rejected'} ({response.status})")


@check("URL-09", "URL validation", "Values that are not strings are rejected with 400",
       why="A number, list, object, null or boolean is not a URL; a crash (500) or acceptance is a bug.",
       ask="What does POST / do when the value is not a string?")
def url_non_string(ctx):
    for value in NON_STRING_VALUES:
        response = ctx.api.post("/", {"value": value})
        if response.status != 400:
            ctx.problem(f"value {value!r}: expected 400, got {response.status}", response)


@check("URL-10", "URL validation", "A very long URL does not crash the service",
       why="A 100,000-character value may be rejected (400/413/414) or stored, but must not cause a 500.",
       ask="Do you limit the length of a URL?")
def url_very_long(ctx):
    value = "https://example.com/" + "a" * 100000
    response = ctx.api.post("/", {"value": value})
    if is_5xx(response):
        ctx.problem(f"got {response.status}", response)


@check("ROBUST-01", "Robustness", "Malformed JSON bodies get a 4xx answer, not a crash or a new mapping",
       why="Invalid input must give a client error (400), never a server error (500).",
       ask="How do you parse the request body? What if it is not valid JSON?")
def robust_malformed(ctx):
    short_id, _ = ctx.create(ctx.url("malformed"))
    headers = {"Content-Type": "application/json"}
    for body in ("{bad json", "", "null", "[]", '{"value": '):
        for method, path in (("POST", "/"), ("PUT", "/" + quote(short_id, safe=""))):
            response = ctx.api.request(method, path, data=body, headers=headers)
            if not 400 <= response.status < 500:
                ctx.problem(f"{method} {path} with body {body!r}: expected 4xx, got {response.status}", response)


@check("ROBUST-02", "Robustness", "Bodies without a JSON content type never cause a 500",
       why="Clients such as curl send text/plain or form data unless told otherwise.",
       ask="What does your service do with a form-encoded body?")
def robust_content_types(ctx):
    cases = (
        ('{"value": "' + ctx.url("text-plain") + '"}', {"Content-Type": "text/plain"}),
        ("value=" + ctx.url("form"), {"Content-Type": "application/x-www-form-urlencoded"}),
    )
    for body, headers in cases:
        response = ctx.api.request("POST", "/", data=body, headers=headers)
        if is_5xx(response):
            ctx.problem(f"{headers['Content-Type']}: got {response.status}", response)


@check("ROBUST-03", "Robustness", "Odd identifiers in the path get 404, not a crash",
       why="GET/PUT/DELETE /:id must handle any string, including encoded and very long ones.",
       ask="What does GET /:id do with an id that is not one of yours?")
def robust_odd_ids(ctx):
    for path in ("/" + "a" * 2000, "/%20", "/%25", "/%C3%A9", "/..%2F", "/%00"):
        for method in ("GET", "PUT", "DELETE"):
            client = ctx.public if method == "GET" else ctx.api
            body = {"url": ctx.url("odd")} if method == "PUT" else None
            response = client.request(method, path, json_body=body)
            if not 400 <= response.status < 500:
                ctx.problem(f"{method} {shorten(path, 40)}: expected 4xx, got {response.status}", response)


@check("ROBUST-04", "Robustness", "Unsupported methods get a 4xx answer, not a crash",
       why="PATCH, or POST on /:id, are not part of the API: 405 (or 404) is the right answer.",
       ask="Which methods does your API support?")
def robust_methods(ctx):
    short_id, _ = ctx.create(ctx.url("methods"))
    for method, path in (("PATCH", "/" + short_id), ("POST", "/" + short_id), ("PUT", "/"), ("PATCH", "/")):
        response = ctx.api.request(method, path, json_body={"url": ctx.url("methods-2")})
        if not 400 <= response.status < 500:
            ctx.problem(f"{method} {path}: expected 4xx, got {response.status}", response)


@check("ROBUST-05", "Robustness", "A 1 MB request body does not crash the service",
       why="Large bodies must be rejected or handled, never cause a 500 or bring the service down.",
       ask="Do you limit the request size?")
def robust_large_body(ctx):
    response = ctx.api.post("/", {"value": ctx.url("large"), "padding": "x" * 1000000})
    if is_5xx(response):
        ctx.problem(f"got {response.status}", response)
    if ctx.api.get("/").status >= 500:
        ctx.problem("the service fails after the large request")


@check("ROBUST-06", "Robustness", "JSON answers declare Content-Type: application/json", severity="WARN",
       why="Clients rely on the content type to parse the answer.", ask="How do you build your answers?")
def robust_content_type(ctx):
    for response in (ctx.api.post("/", {"value": ctx.url("content-type")}), ctx.api.get("/")):
        if response.json() is not None and "json" not in response.headers.get("Content-Type", ""):
            ctx.problem(f"a JSON answer has Content-Type {response.headers.get('Content-Type')!r}", response)


@check("DATA-01", "Data integrity", "URLs are given back exactly as they were stored",
       why="Changing a URL (case, trailing slash, order of the query, fragment) can lead to a different page.",
       ask="Do you change URLs before storing them?")
def data_exact(ctx):
    for value in ("https://example.com/Path/To/Page/?b=2&a=1#Frag", "https://example.com/A?x=%20y",
                  "https://example.com/trailing/"):
        short_id, response = ctx.create(value, require=False)
        if short_id is None:
            continue  # rejecting is covered by URL-04/05
        ok, answer = ctx.points_to(short_id, value)
        if not ok:
            ctx.problem(f"{value!r} came back as {target_of(answer)!r}", answer)


@check("DATA-02", "Data integrity", "Updating or deleting one mapping leaves the others unchanged",
       why="An update or delete must touch only its own mapping.", ask="Show how PUT and DELETE find the mapping.")
def data_isolation(ctx):
    urls = [ctx.url(f"isolation-{number}") for number in range(3)]
    ids = [ctx.create(url)[0] for url in urls]
    new_url = ctx.url("isolation-updated")
    ctx.api.put("/" + quote(ids[1], safe=""), {"url": new_url})
    ctx.api.delete("/" + quote(ids[2], safe=""))
    ok, response = ctx.points_to(ids[0], urls[0])
    if not ok:
        ctx.problem("the first mapping changed", response)
    ok, response = ctx.points_to(ids[1], new_url)
    if not ok:
        ctx.problem("the updated mapping does not give the new URL", response)
    if ctx.resolve(ids[2]).status != 404:
        ctx.problem("the deleted mapping still resolves")


@check("ROBUST-07", "Robustness", "The service still answers after all checks",
       why="Earlier input must not have crashed or blocked the service.", ask="Did the service crash? Check its log.")
def robust_alive(ctx):
    response = ctx.api.get("/")
    if response.status != 200:
        ctx.problem(f"GET / answers {response.status}", response)


def main():
    parser = argparse.ArgumentParser(description="TA audit for Assignment 1 (URL shortener).")
    parser.add_argument("--url", default="http://127.0.0.1:5000",
                        help="base URL of the shortener (default: %(default)s)")
    parser.add_argument("--report", metavar="FILE.md", help="also write the findings to a Markdown file")
    parser.add_argument("--json", metavar="FILE.json", help="also write every result to a JSON file")
    parser.add_argument("--quick", action="store_true", help="fewer URLs, no collision search")
    parser.add_argument("--only", nargs="*", help="run only checks whose id starts with these, e.g. A1-URL")
    parser.add_argument("-v", "--verbose", action="store_true", help="show each check while it runs")
    args = parser.parse_args()

    client = Client(args.url)
    try:
        wait_for(client)
    except ServiceUnreachable as error:
        print(f"Cannot reach the shortener: {error}", file=sys.stderr)
        sys.exit(2)
    context = ShortenerContext(client, client, many=200 if args.quick else 1000,
                               collision_search=not args.quick)
    started = time.monotonic()
    results = run_checks(CHECKS, context, "A1", args.only, args.verbose)
    try:
        client.delete("/")
    except ServiceUnreachable:
        pass
    title = "TA audit, Assignment 1 (URL shortener)"
    target = f"Service: {args.url}. {len(results)} checks in {time.monotonic() - started:.0f} s."
    print_report(title, target, results)
    if args.report:
        write_markdown(args.report, title, target, results)
        print(f"Report written to {args.report}")
    if args.json:
        write_json(args.json, title, target, results)
    sys.exit(1 if any(result.status == "FAIL" for result in results) else 0)


if __name__ == "__main__":
    main()
