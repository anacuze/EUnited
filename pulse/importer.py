"""
The importer: reads news from the university websites and puts them in the review queue.

Each active Source is either an RSS/Atom feed or a web page that lists news ("scraping").
Every new item becomes a draft news Post linked to its Source. Nothing is published here:
an admin opens the draft in the Review queue, fixes the type, dates and tags, and publishes.

A post is recognised by its `source_url`, so running the importer again never creates the
same post twice. That also holds for rejected and hidden posts, as long as they aren't deleted.
"""
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlsplit

import feedparser
import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Post, Source

logger = logging.getLogger(__name__)

USER_AGENT = "EUnitedImporter/1.0 (student platform of the EUPeace alliance)"
TIMEOUT = 15  # seconds, for each request
MAX_BYTES = 3 * 1024 * 1024  # bigger pages are cut off
BLOCK_TAGS = ["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre"]

TITLE_MAX = Post._meta.get_field("title").max_length
SUMMARY_MAX = Post._meta.get_field("summary").max_length
URL_MAX = Post._meta.get_field("source_url").max_length
IMAGE_MAX = Post._meta.get_field("image_url").max_length


class ImporterError(Exception):
    """A source could not be read. The message is shown to the admin."""


@dataclass
class Item:
    """One news item found on a source, before it becomes a Post."""

    url: str
    title: str
    summary: str = ""
    body: str = ""
    image_url: str = ""
    language: str = ""


@dataclass
class Result:
    source: Source
    created: list = field(default_factory=list)  # Posts (unsaved ones on a dry run)
    errors: list = field(default_factory=list)  # messages, one per problem

    @property
    def failed(self):
        """True when the source itself could not be read (not just one of its items)."""
        return bool(self.errors) and not self.created


# --- small helpers ------------------------------------------------------------


def fetch(url):
    """Download a page or feed and return its bytes. Tests replace this function."""
    try:
        with requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, stream=True
        ) as response:
            response.raise_for_status()
            return response.raw.read(MAX_BYTES, decode_content=True)
    except requests.RequestException as exc:
        raise ImporterError(f"Could not open {url}: {exc}") from exc


def html_to_text(html):
    """Turn HTML into plain text, one paragraph per block, separated by empty lines."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "form", "figure"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    blocks = [
        tag.get_text().strip()
        for tag in soup.find_all(BLOCK_TAGS)
        if not tag.find(BLOCK_TAGS)  # skip a block that only wraps other blocks
    ]
    blocks = [re.sub(r"[ \t\r\f\v]*\n\s*", "\n", re.sub(r"[ \t]+", " ", b)) for b in blocks if b]
    if blocks:
        return "\n\n".join(blocks)
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def shorten(text, limit):
    """Cut text to `limit` characters at a word boundary, ending with an ellipsis."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut[limit // 2:]:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-–") + "…"


def language_code(value):
    """'it-IT' -> 'it'. Empty when the value doesn't look like a language code."""
    code = (value or "").strip().lower().replace("_", "-").split("-")[0]
    return code if re.fullmatch(r"[a-z]{2,3}", code) else ""


def _host(url):
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def normalise_url(url, source):
    """Absolute URL without #fragment. Uses https when the source itself is on https."""
    url = urldefrag(urljoin(source.url, (url or "").strip()))[0]
    if url.startswith("http://") and source.url.startswith("https://") and _host(url) == _host(source.url):
        url = "https://" + url[len("http://"):]
    return url


# --- reading a source ---------------------------------------------------------


def read_feed(source, content):
    """Items of an RSS or Atom feed, newest first (the order of the feed)."""
    parsed = feedparser.parse(content)
    if not parsed.entries:
        if parsed.bozo or not parsed.get("version"):
            raise ImporterError(f"{source.url} is not a valid RSS/Atom feed.")
        return []
    feed_language = language_code(parsed.feed.get("language"))
    items = []
    for entry in parsed.entries:
        link = entry.get("link")
        title = html_to_text(entry.get("title"))
        if not link or not title:
            continue
        full_html = entry.content[0].get("value", "") if entry.get("content") else ""
        summary_html = entry.get("summary", "")
        body = html_to_text(full_html)
        summary = html_to_text(summary_html) or body
        items.append(Item(
            url=normalise_url(link, source),
            title=title,
            summary=summary,
            body=body if body and body != summary else "",
            image_url=_feed_image(entry, full_html or summary_html, source),
            language=feed_language,
        ))
    return items


def _feed_image(entry, html, source):
    candidates = [m.get("url") for m in entry.get("media_thumbnail", [])]
    candidates += [
        m.get("url") for m in entry.get("media_content", [])
        if m.get("medium") == "image" or (m.get("type") or "").startswith("image/")
    ]
    candidates += [
        e.get("href") for e in entry.get("enclosures", []) if (e.get("type") or "").startswith("image/")
    ]
    if html:
        img = BeautifulSoup(html, "html.parser").find("img", src=True)
        if img:
            candidates.append(img["src"])
    for url in candidates:
        if url:
            return normalise_url(url, source)
    return ""


def read_listing(source, content):
    """Links to single news pages found on a page that lists news, in page order."""
    soup = BeautifulSoup(content, "html.parser")
    listing = normalise_url(source.url, source)
    pattern = re.compile(source.link_pattern) if source.link_pattern else None
    prefix = listing.rstrip("/") + "/"
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = normalise_url(href, source)
        if _host(url) != _host(listing) or url.rstrip("/") == listing.rstrip("/"):
            continue
        if pattern:
            if not pattern.search(url):
                continue
        elif not url.startswith(prefix) or "?" in url:
            # Without a pattern: only pages "below" the listing, e.g. /news/some-title/
            continue
        if url not in links:
            links.append(url)
    return links


def read_article(source, url, content):
    """Read one news page. Uses the Open Graph tags that sites add for social networks."""
    soup = BeautifulSoup(content, "html.parser")

    def meta(*names):
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if tag and tag.get("content", "").strip():
                return tag["content"].strip()
        return ""

    h1 = soup.find("h1")
    title = (
        meta("og:title", "twitter:title")
        or (h1.get_text(" ", strip=True) if h1 else "")
        or (soup.title.get_text(" ", strip=True) if soup.title else "")
    )
    # Many sites end the title with their own name ("Some news – EUPeace"): drop that part.
    site_name = meta("og:site_name")
    heading = h1.get_text(" ", strip=True) if h1 else ""
    if heading and title.startswith(heading):
        title = heading
    elif site_name:
        title = re.sub(r"\s*[–—|·-]\s*" + re.escape(site_name) + r"\s*$", "", title) or title
    container = soup.find("article") or soup.find("main")
    body = html_to_text(str(container)) if container else ""
    if h1 and body.startswith(h1.get_text(" ", strip=True)):
        body = body[len(h1.get_text(" ", strip=True)):].lstrip()
    summary = meta("og:description", "description", "twitter:description") or body
    image = meta("og:image", "twitter:image")
    html_tag = soup.find("html")
    return Item(
        url=url,
        title=html_to_text(title),
        summary=html_to_text(summary),
        body=body,
        image_url=normalise_url(image, source) if image else "",
        language=language_code(meta("og:locale") or (html_tag.get("lang") if html_tag else "")),
    )


# --- importing ------------------------------------------------------------------


def _known_urls(urls):
    return set(Post.objects.filter(source_url__in=urls).values_list("source_url", flat=True))


def find_new_items(source, limit, errors):
    """The newest items of a source that are not in the database yet (at most `limit`)."""
    content = fetch(source.url)
    if source.kind == Source.Kind.RSS:
        items = read_feed(source, content)
        known = _known_urls([item.url for item in items])
        return [item for item in items if item.url not in known][:limit]

    links = read_listing(source, content)
    if not links:
        raise ImporterError(
            f"No news links found on {source.url}. Check the address and the link pattern of this source."
        )
    known = _known_urls(links)
    items = []
    for url in [u for u in links if u not in known][:limit]:
        try:
            item = read_article(source, url, fetch(url))
        except ImporterError as exc:
            errors.append(str(exc))
            continue
        if item.title:
            items.append(item)
        else:
            errors.append(f"No title found on {url}.")
    return items


def build_post(source, item):
    summary = shorten(item.summary, SUMMARY_MAX) or shorten(item.title, SUMMARY_MAX)
    return Post(
        type=Post.Type.NEWS,
        status=Post.Status.DRAFT,
        title=shorten(item.title, TITLE_MAX),
        summary=summary,
        body=item.body,
        image_url=item.image_url if len(item.image_url) <= IMAGE_MAX else "",
        source_url=item.url,
        language=item.language or source.language,
        university=source.university,
        source=source,
    )


def import_source(source, limit=None, dry_run=False):
    """Import the new items of one source as drafts. Never raises: problems go in Result.errors."""
    limit = limit or settings.PULSE_IMPORT_LIMIT
    result = Result(source=source)
    try:
        items = find_new_items(source, limit, result.errors)
    except ImporterError as exc:
        result.errors.append(str(exc))
        items = []
    except Exception as exc:  # a broken page must not stop the other sources
        logger.exception("Importer failed on source %s", source)
        result.errors.append(f"Unexpected error on {source.url}: {exc}")
        items = []

    # Oldest first, so the Review queue lists them in the order they were published.
    for item in reversed(items):
        if len(item.url) > URL_MAX:
            result.errors.append(f"Skipped, address too long: {item.url}")
            continue
        post = build_post(source, item)
        try:
            post.full_clean()
            if not dry_run:
                with transaction.atomic():
                    post.save()
        except ValidationError as exc:
            result.errors.append(f"Skipped {item.url}: {'; '.join(exc.messages)}")
            continue
        except IntegrityError:
            continue  # imported by another run in the meantime
        result.created.append(post)

    if not dry_run:
        source.last_checked_at = timezone.now()
        source.save(update_fields=["last_checked_at"])
    return result


def import_all(sources=None, limit=None, dry_run=False):
    """Import from every active source (or from the given ones). Returns a list of Results."""
    if sources is None:
        sources = Source.objects.filter(active=True).select_related("university")
    return [import_source(source, limit=limit, dry_run=dry_run) for source in sources]
