import random
import re
from typing import Any

import jinja2


class SpintaxParser:
    SPINTAX_PATTERN = re.compile(r"\{([^{}|]+(?:\|[^{}|]+)+)\}")

    @classmethod
    def parse_spintax(cls, text: str) -> str:
        while True:
            match = cls.SPINTAX_PATTERN.search(text)
            if not match:
                break
            options = match.group(1).split("|")
            selected = random.choice(options)
            text = text[: match.start()] + selected + text[match.end() :]
        return text

    @classmethod
    def substitute_variables(cls, text: str, variables: dict[str, Any] | None = None) -> str:
        if not variables:
            return text
        for key, value in variables.items():
            pattern = re.compile(rf"\{{{re.escape(str(key))}\}}", re.IGNORECASE)
            val_str = str(value) if value is not None else ""
            text = pattern.sub(val_str, text)
        return text

    @classmethod
    def render_jinja(cls, text: str, variables: dict[str, Any] | None = None) -> str:
        try:
            env = jinja2.Environment(autoescape=False)
            tmpl = env.from_string(text)
            return tmpl.render(**(variables or {}))
        except Exception:
            return text

    @classmethod
    def render(cls, template: str, variables: dict[str, Any] | None = None) -> str:
        rendered_jinja = cls.render_jinja(template, variables)
        substituted = cls.substitute_variables(rendered_jinja, variables)
        return cls.parse_spintax(substituted)
