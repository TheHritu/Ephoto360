from __future__ import annotations

import json
import random
from pathlib import Path
import importlib.resources
from typing import Iterator
from .models import EffectInfo, Style, TextInput


class Catalog:
    def __init__(self, config_path: str):
        self._effects: dict[str, EffectInfo] = {}
        self._load(config_path)

    def _load_logo_data(self, filepath) -> dict:
        """Load logourls.json from inside the installed package."""
        ref = importlib.resources.files("Ephoto360").joinpath(filepath)
        with importlib.resources.as_file(ref) as path:
            with open(path, "r") as f:
                return json.load(f)

    def _load(self, path: str):
        raw: dict = self._load_logo_data(path)
        for slug, blob in raw.items():
            inputs = [
                TextInput(index=i, field_id=t["id"], label=t["label"])
                for i, t in enumerate(blob["text_input"]["data"])
            ]

            # radio_data.data is a dict keyed by form-field name.
            # Each key maps to a list of ALL available Style options for that group.
            # e.g. {"radio0[radio]": [{label,value,thumb}, ...], "radio1[radio]": [...]}
            radio_raw = blob["radio_data"]["data"]
            if isinstance(radio_raw, dict):
                radio_groups = {
                    key: [
                        Style(label=s["label"], value=s["value"], thumb=s["thumb"])
                        for s in opts
                    ]
                    for key, opts in radio_raw.items()
                    if opts  # skip empty lists
                }
            else:
                # backwards compat: old flat-list format -> treat as radio0 only
                radio_groups = (
                    {
                        "radio0[radio]": [
                            Style(label=s["label"], value=s["value"], thumb=s["thumb"])
                            for s in radio_raw
                        ]
                    }
                    if radio_raw
                    else {}
                )

            self._effects[slug] = EffectInfo(
                slug=slug,
                text_inputs=inputs,
                radio_groups=radio_groups,
                preview_url=blob.get("preview", ""),
            )

    def all(self) -> list[EffectInfo]:
        return sorted(self._effects.values(), key=lambda e: e.name)

    def search(self, query: str, case_sensitive=False) -> list[EffectInfo]:
        q = query if case_sensitive else query.lower()
        out = []
        for info in self._effects.values():
            name = info.name if case_sensitive else info.name.lower()
            slug = info.slug if case_sensitive else info.slug.lower()
            if q in name + " " + slug:
                out.append(info)
        return sorted(out, key=lambda e: e.name)

    def get(self, slug: str) -> EffectInfo:
        if slug in self._effects:
            return self._effects[slug]
        for key, info in self._effects.items():
            if key.endswith(slug) or key.rstrip(".html").endswith(slug):
                return info
        raise KeyError(f"Effect {slug!r} not found")

    def with_radio(self) -> Iterator[EffectInfo]:
        return (info for info in self._effects.values() if info.has_radio)

    def random(self, require_radio=False) -> EffectInfo:
        pool = list(self.with_radio() if require_radio else self._effects.values())
        return random.choice(pool)

    def summary(self) -> str:
        total = len(self._effects)
        with_r = sum(1 for i in self._effects.values() if i.has_radio)
        multi_r = sum(1 for i in self._effects.values() if len(i.radio_groups) > 1)
        return f"{total} effects ({with_r} with radio, {multi_r} with multiple radio groups)"

    def __len__(self):
        return len(self._effects)
