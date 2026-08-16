'''Loads user-facing guardrail/error message templates from messages.yml, so
wording can be tuned in one place without touching guardrail logic. See that
file's header comment for the template format.'''

from pathlib import Path
from typing import Any

import yaml

_MESSAGES_PATH = Path(__file__).parent / "messages.yml"

with open(_MESSAGES_PATH, "r", encoding="utf-8") as _f:
    _MESSAGES: dict = yaml.safe_load(_f)


def msg(path: str, **kwargs: Any) -> str:
    '''Looks up a dotted path (e.g. "quota_check.exceeded") in messages.yml and
    formats it with the given kwargs. Raises on a typo'd path or a missing/extra
    placeholder rather than silently returning something wrong - these are
    user-facing strings, a broken lookup should fail loudly (and fail a test),
    not ship a blank or malformed chat bubble.'''
    node: Any = _MESSAGES
    for part in path.split("."):
        node = node[part]
    return node.format(**kwargs)
