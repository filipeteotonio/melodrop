"""A minimal method + regex router."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Pattern, Tuple

Handler = Callable[..., object]


@dataclass(frozen=True)
class Route:
    method: str
    pattern: Pattern[str]
    handler: Handler


class Router:
    def __init__(self) -> None:
        self._routes: List[Route] = []

    def add(self, method: str, pattern: str, handler: Handler) -> None:
        self._routes.append(Route(method.upper(), re.compile("^" + pattern + "$"), handler))

    def match(self, method: str, path: str) -> Optional[Tuple[Handler, Dict[str, str]]]:
        for route in self._routes:
            if route.method == method.upper():
                found = route.pattern.match(path)
                if found:
                    return route.handler, found.groupdict()
        return None

    def allows(self, path: str) -> bool:
        return any(route.pattern.match(path) for route in self._routes)
