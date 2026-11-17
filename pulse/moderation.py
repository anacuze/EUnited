"""
Automatic checks on a new comment, before it is saved.

The checks only sort comments; people decide. There are three outcomes:

    ALLOW   the comment is published at once
    HOLD    the comment is saved but hidden until a moderator approves it
    REJECT  the comment is not saved and the author is told why, so they can fix it

Clear, mechanical rules (too fast, too many links, the same text twice) reject. Anything
that needs judgement (a blocked word, a classifier that flags the text) holds, because
word lists and classifiers both make mistakes and a moderator can put the comment back.
"""
import logging
import re
from dataclasses import dataclass
from datetime import timedelta

import requests
from django.conf import settings
from django.utils import timezone
from django.utils.module_loading import import_string

from .models import BlockedWord, Comment

logger = logging.getLogger(__name__)

ALLOW, HOLD, REJECT = "allow", "hold", "reject"
LINK = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)


@dataclass
class Verdict:
    action: str
    reason: str = ""  # REJECT: shown to the author. HOLD: shown to the moderators.


def check_comment(user, post, body, now=None):
    """Decide what happens to a comment that `user` wants to add to `post`."""
    now = now or timezone.now()

    last = Comment.objects.filter(author=user).order_by("-created_at").first()
    if last:
        wait = settings.PULSE_COMMENT_MIN_SECONDS - (now - last.created_at).total_seconds()
        if wait > 0:
            return Verdict(REJECT, f"You're commenting very fast. Wait {int(wait) + 1} seconds and try again.")

    same = Comment.objects.filter(
        author=user, post=post, created_at__gte=now - timedelta(days=1)
    ).values_list("body", flat=True)
    if _squash(body) in {_squash(b) for b in same}:
        return Verdict(REJECT, "You already posted this comment.")

    if len(LINK.findall(body)) > settings.PULSE_COMMENT_MAX_LINKS:
        return Verdict(REJECT, f"A comment can have at most {settings.PULSE_COMMENT_MAX_LINKS} links.")

    word = find_blocked_word(body)
    if word:
        return Verdict(HOLD, f'Contains the blocked word "{word}".')

    reason = run_classifier(body)
    if reason:
        return Verdict(HOLD, reason)

    return Verdict(ALLOW)


def _squash(text):
    return " ".join(text.casefold().split())


def find_blocked_word(body):
    """The first blocked word found in the text as a whole word, or ''."""
    text = _squash(body)
    for word in BlockedWord.objects.values_list("word", flat=True):
        if re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text):
            return word
    return ""


def run_classifier(body):
    """Ask the configured classifier. Returns why the comment should be held, or ''.

    If the classifier is off or fails, the comment goes through: the Report button and the
    moderators are still there, and a broken outside service must not block every comment.
    """
    path = settings.PULSE_COMMENT_CLASSIFIER
    if not path:
        return ""
    try:
        return (import_string(path)(body) or "")[:300]
    except Exception:
        logger.exception("Comment classifier %s failed; the comment was let through.", path)
        return ""


def openai_classifier(body):
    """Classifier that uses OpenAI's Moderation API. Returns the flagged categories, or ''."""
    response = requests.post(
        "https://api.openai.com/v1/moderations",
        headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
        json={"model": "omni-moderation-latest", "input": body},
        timeout=5,
    )
    response.raise_for_status()
    result = response.json()["results"][0]
    if not result.get("flagged"):
        return ""
    categories = sorted(name for name, hit in result.get("categories", {}).items() if hit)
    return "Flagged by the automatic check: " + (", ".join(categories) or "unspecified") + "."
