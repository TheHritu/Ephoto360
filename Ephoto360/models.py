from __future__ import annotations

import re
import requests
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Style:
    label: str
    value: str
    thumb: str

    def __str__(self):
        return self.label


@dataclass(frozen=True)
class TextInput:
    index: int
    field_id: str
    label: str


@dataclass
class EffectInfo:
    slug: str
    text_inputs: list[TextInput]
    # radio_groups maps form-field name -> all available Style options for that group.
    # e.g. {"radio0[radio]": [Style(...), ...], "radio1[radio]": [Style(...), ...]}
    radio_groups: dict[str, list[Style]] = field(default_factory=dict)
    preview_url: str = ""

    @property
    def url(self):
        from .client import BASE_URL

        return BASE_URL + self.slug

    @property
    def name(self):
        stem = Path(self.slug).stem
        stem = re.sub(r"-\d+$", "", stem)
        return stem.replace("-", " ").title()

    @property
    def text_count(self):
        return len(self.text_inputs)

    @property
    def text_labels(self):
        return [t.label for t in self.text_inputs]

    @property
    def has_radio(self):
        return bool(self.radio_groups)

    @property
    def radio_keys(self) -> list[str]:
        """Sorted list of radio group keys: ['radio0[radio]', 'radio1[radio]', ...]"""
        return sorted(self.radio_groups.keys())

    def options_for(self, key: str) -> list[Style]:
        """All Style options for a given radio group key."""
        return self.radio_groups.get(key, [])

    def option_by_label(self, key: str, label: str) -> Optional[Style]:
        """Case-insensitive label lookup within a specific radio group."""
        lower = label.lower()
        return next(
            (s for s in self.radio_groups.get(key, []) if s.label.lower() == lower),
            None,
        )

    def option_by_index(self, key: str, index: int) -> Optional[Style]:
        """Pick an option by position. Returns None if index is out of range."""
        opts = self.radio_groups.get(key, [])
        return opts[index] if 0 <= index < len(opts) else None

    @property
    def styles(self) -> list[Style]:
        """Shorthand: all options for radio0[radio]. Use radio_groups for full access."""
        return self.radio_groups.get("radio0[radio]", [])

    @property
    def style_labels(self) -> list[str]:
        return [s.label for s in self.styles]

    def style_by_label(self, label: str) -> Optional[Style]:
        return self.option_by_label("radio0[radio]", label)

    def __repr__(self):
        groups = ", ".join(f"{k}({len(v)})" for k, v in self.radio_groups.items())
        return f"<EffectInfo {self.name!r} texts={self.text_count} radio=[{groups}]>"


@dataclass
class CreationResult:
    ok: bool
    url: str = ""
    styles: dict[str, str] = field(default_factory=dict)  # key -> label applied
    slug: str = ""
    error: str = ""

    @property
    def style(self) -> str:
        """Legacy shim — label applied to radio0[radio]."""
        return self.styles.get("radio0[radio]", "")

    def save(self, path, session=None) -> Path:
        if not self.ok:
            raise RuntimeError(f"Can't save a failed result: {self.error}")
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        sess = session or requests.Session()
        resp = sess.get(self.url, timeout=30)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return dest

    def __repr__(self):
        if self.ok:
            return f"<CreationResult ok url={self.url!r} styles={self.styles}>"
        return f"<CreationResult FAILED error={self.error!r}>"
