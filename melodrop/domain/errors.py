"""Turns raw yt-dlp errors into messages a person can act on."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

MAX_RAW_LENGTH = 300


class MelodropError(Exception):
    """An error whose message is safe and useful to show to the user."""


@dataclass(frozen=True)
class ErrorContext:
    message: str
    browser: str = ""

    @property
    def lower(self) -> str:
        return self.message.lower()

    @property
    def browser_name(self) -> str:
        return self.browser.capitalize()


@dataclass(frozen=True)
class ErrorRule:
    applies: Callable[[ErrorContext], bool]
    explain: Callable[[ErrorContext], str]


def _contains(*needles: str) -> Callable[[ErrorContext], bool]:
    return lambda ctx: any(n in ctx.lower for n in needles)


def _cookie_problem(ctx: ErrorContext) -> bool:
    return bool(ctx.browser) and _contains("cookie", "operation not permitted", "keyring")(ctx)


def _explain_cookie_problem(ctx: ErrorContext) -> str:
    if ctx.browser == "safari":
        return (
            "Couldn't read Safari's login. Allow Full Disk Access for the app running Melodrop "
            "(System Settings > Privacy & Security), or pick Chrome or Firefox instead."
        )
    name = ctx.browser_name
    return (
        f"Couldn't read {name}'s login. Make sure {name} is installed and you're signed in to "
        "YouTube there. If macOS asks for keychain access, click Always Allow."
    )


def _explain_bot_check(ctx: ErrorContext) -> str:
    if ctx.browser:
        return (
            f"YouTube still wants to confirm you're not a bot. Open youtube.com in {ctx.browser_name}, make sure "
            "you're signed in and play any video, then click Retry failed."
        )
    return (
        'YouTube wants to confirm you\'re not a bot. Under "Use browser login", pick a browser '
        "where you're signed in to YouTube, then click Retry failed."
    )


DEFAULT_RULES: Sequence[ErrorRule] = (
    ErrorRule(_cookie_problem, _explain_cookie_problem),
    ErrorRule(_contains("not a bot"), _explain_bot_check),
    ErrorRule(
        _contains("confirm your age", "age-restricted"),
        lambda ctx: (
            'This song is age-restricted. Under "Use browser login", pick a browser where '
            "you're signed in to YouTube, then click Retry failed."
        ),
    ),
    ErrorRule(_contains("private video"), lambda ctx: "This video is private."),
    ErrorRule(
        _contains("not available", "unavailable"),
        lambda ctx: "This song isn't available (removed, private, or blocked in your country).",
    ),
)


class ErrorTranslator:
    def __init__(self, rules: Iterable[ErrorRule] = DEFAULT_RULES) -> None:
        self._rules = tuple(rules)

    def translate(self, raw: str, browser: str = "") -> str:
        ctx = ErrorContext(message=raw or "", browser=browser or "")
        for rule in self._rules:
            if rule.applies(ctx):
                return rule.explain(ctx)
        return ctx.message[:MAX_RAW_LENGTH]
