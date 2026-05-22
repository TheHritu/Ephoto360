from __future__ import annotations

import json
import random
import logging
from pathlib import Path
from typing import Optional
from .catalog import Catalog
from .session import Session
from bs4 import BeautifulSoup
from .models import CreationResult, EffectInfo, Style

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

BASE_URL = "https://en.ephoto360.com"
CREATE_ENDPOINT = f"{BASE_URL}/effect/create-image"


class Ephoto360:
    def __init__(
        self,
        retry_count: int = 3,
        retry_delay: float = 1.5,
        timeout: float = 30.0,
    ):

        config_path: str = "logourls.json"
        self.catalog = Catalog(config_path)
        self._http = Session(retry_count, retry_delay, timeout)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self._http.close()

    def list_effects(self):
        return self.catalog.all()

    def search(self, query: str, *, case_sensitive=False):
        return self.catalog.search(query, case_sensitive=case_sensitive)

    def get_effect(self, slug: str) -> EffectInfo:
        return self.catalog.get(slug)

    def random_effect(self, *, require_radio=False) -> EffectInfo:
        return self.catalog.random(require_radio)

    def create(
        self,
        slug: str,
        texts: list[str],
        *,
        styles: Optional[dict[str, str]] = None,
        random_style: bool = False,
    ) -> CreationResult:
        """
        Parameters
        ----------
        slug:
            Effect slug, e.g. "/create-colorful-neon-light-text-effects-online-797.html".
        texts:
            One string per text field. Extra values are silently dropped.
        styles:
            Dict mapping radio group key → style label, e.g.
                {"radio0[radio]": "Jennie"}
                {"radio0[radio]": "Bg 6", "radio1[radio]": "Style 2"}
            Groups not mentioned fall back to the first available option.
        random_style:
            When True, unspecified radio groups pick a random option instead
            of always defaulting to the first one.
        """
        try:
            info = self.catalog.get(slug)
        except KeyError as exc:
            return CreationResult(ok=False, error=str(exc), slug=slug)

        texts_length = len(texts)
        if texts_length == 1 and " " in str(texts[0]) and not info.text_count == 1:
            texts = texts[0].split(" ")
        if texts_length > info.text_count:
            texts = texts[: info.text_count]
        if texts_length < info.text_count:
            times_to_append = info.text_count - texts_length
            texts.extend(["?"] * times_to_append)
        resolved: dict[str, Optional[Style]] = {}
        for key in info.radio_keys:
            opts = info.options_for(key)
            label = (styles or {}).get(key)
            if label:
                found = info.option_by_label(key, label)
                if not found:
                    return CreationResult(
                        ok=False,
                        slug=slug,
                        error=(
                            f"Style {label!r} not found in {key!r}. "
                            f"Available: {[s.label for s in opts]}"
                        ),
                    )
                resolved[key] = found
            elif opts:
                resolved[key] = random.choice(opts) if random_style else opts[0]
            else:
                resolved[key] = None

        return self._build(info, texts, resolved)

    def create_all_styles(
        self,
        slug: str,
        texts: list[str],
        *,
        radio1_label: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[CreationResult]:
        """
        Generate one image per radio0 option, keeping other groups fixed.

        Some effects have hundreds of options (e.g. 322 LoL ranks) LOL.
        Use `limit` to cap how many images are generated.

        Parameters
        ----------
        radio1_label:
            Pin radio1[radio] to this label while iterating radio0.
            Defaults to the first radio1 option when not set.
        limit:
            Stop after this many results. None = no limit (use carefully).
        """
        try:
            info = self.catalog.get(slug)
        except KeyError as exc:
            return [CreationResult(ok=False, error=str(exc), slug=slug)]
        texts_length = len(texts)
        if texts_length == 1 and " " in str(texts[0]) and not info.text_count == 1:
            texts = texts[0].split(" ")
        if texts_length > info.text_count:
            texts = texts[: info.text_count]
        if texts_length < info.text_count:
            times_to_append = info.text_count - texts_length
            texts.extend(["?"] * times_to_append)
        r0_opts = info.options_for("radio0[radio]")
        if not r0_opts:
            return [self._build(info, texts, {})]

        # Resolve every group except radio0 once, outside the loop
        others: dict[str, Optional[Style]] = {}
        for key in info.radio_keys:
            if key == "radio0[radio]":
                continue
            opts = info.options_for(key)
            if key == "radio1[radio]" and radio1_label:
                found = info.option_by_label(key, radio1_label)
                if not found:
                    return [
                        CreationResult(
                            ok=False,
                            slug=slug,
                            error=(
                                f"radio1 label {radio1_label!r} not found. "
                                f"Available: {[s.label for s in opts]}"
                            ),
                        )
                    ]
                others[key] = found
            else:
                others[key] = opts[0] if opts else None

        to_run = r0_opts[:limit] if limit else r0_opts
        if limit and len(r0_opts) > limit:
            logger.info(
                "create_all_styles: capped at %d/%d radio0 options for %s",
                limit,
                len(r0_opts),
                slug,
            )

        results = []
        for opt in to_run:
            resolved = {"radio0[radio]": opt, **others}
            results.append(self._build(info, texts, resolved))
        return results

    def batch_create(self, requests_: list[dict]) -> list[CreationResult]:
        """
        Run multiple independent creation requests.

        Each dict keys:
            slug         (str)            required
            texts        (list[str])      required
            styles       (dict[str,str])  optional
            random_style (bool)           optional, default False
        """
        return [
            self.create(
                r["slug"],
                r["texts"],
                styles=r.get("styles"),
                random_style=r.get("random_style", False),
            )
            for r in requests_
        ]

    def _build(
        self,
        info: EffectInfo,
        texts: list[str],
        resolved: dict[str, Optional[Style]],
    ) -> CreationResult:
        effect_url = info.url
        self._http.get(referer=effect_url)

        applied_labels = {key: style.label for key, style in resolved.items() if style}

        try:
            # Step 1 : GET the effect page for tokens
            page = self._http.request("GET", effect_url)
            soup = BeautifulSoup(page.text, "html.parser")

            token = _input(soup, "token")
            build_server = _input(soup, "build_server")
            build_server_id = _input(soup, "build_server_id")

            # Step 2 : POST the form with text fields + all radio groups
            form: dict[str, str] = {
                "submit": "GO",
                "token": token,
                "build_server": build_server,
                "build_server_id": build_server_id,
                **{f"text[{i}]": t for i, t in enumerate(texts)},
            }

            for key, style in resolved.items():
                if style:
                    form[key] = style.value
                else:
                    default = _page_radio_default(soup, key)
                    if default:
                        form[key] = default

            post = self._http.request("POST", effect_url, data=form)
            doc = BeautifulSoup(post.text, "html.parser")

            # Step 3 : Extract hidden state JSON
            fv = doc.select_one("input[id=form_value_input]")
            if not fv:
                return CreationResult(
                    ok=False,
                    slug=info.slug,
                    styles=applied_labels,
                    error="form_value_input missing from POST response",
                )

            state: dict = json.loads(fv["value"])

            # Step 4 : Call create-image endpoint
            create_body = {f"text[{i}]": t for i, t in enumerate(texts)}
            create_body.update(
                {
                    "id": state["id"],
                    "token": state["token"],
                    "build_server": state["build_server"],
                    "build_server_id": state["build_server_id"],
                }
            )

            for key in info.radio_keys:
                style = resolved.get(key)
                if style:
                    create_body[key] = style.value
                else:
                    # state keys are like "radio0", "radio1" (no brackets)
                    state_key = key.split("[")[0]
                    fallback = state.get(state_key, {}).get("radio", "")
                    if fallback:
                        create_body[key] = fallback

            res = self._http.request("POST", CREATE_ENDPOINT, data=create_body)
            data = res.json()

            if not data.get("success"):
                return CreationResult(
                    ok=False,
                    slug=info.slug,
                    styles=applied_labels,
                    error=f"API returned success=false: {data}",
                )

            return CreationResult(
                ok=True,
                url=f"{state['build_server']}{data['image']}",
                styles=applied_labels,
                slug=info.slug,
            )

        except Exception as exc:
            return CreationResult(
                ok=False,
                slug=info.slug,
                styles=applied_labels,
                error=str(exc),
            )

    def __repr__(self):
        return f"<Ephoto360 effects={len(self.catalog)}>"

    def __len__(self):
        return len(self.catalog)


def _input(soup: BeautifulSoup, name: str) -> str:
    tag = soup.select_one(f"input[name={name}]")
    if not tag:
        raise ValueError(f"Missing form input: {name!r}")
    return tag["value"]


def _page_radio_default(soup: BeautifulSoup, key: str) -> str:
    """Get the checked radio value for a given group key from the scraped page."""
    checked = soup.select_one(f"input[name='{key}'][checked]")
    if checked:
        return checked.get("value", "")
    first = soup.select_one(f"input[name='{key}']")
    return first.get("value", "") if first else ""
