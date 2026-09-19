import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Config(BaseModel):
    """Resource controls, not guarantees of knowledge completeness."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    allowed_domains: list[str] = []
    allowed_paths: list[str] = ["/"]
    external_document_domains: list[str] = []
    excluded_patterns: list[str] = [r"[?&](?:sort|filter|calendar|sessionid)=", r"/calendar/"]
    max_resources: int = Field(50, ge=1, le=10000)
    max_discovered: int = Field(2000, ge=1, le=100000)
    max_depth: int = Field(3, ge=0, le=30)
    concurrency: int = Field(2, ge=1, le=8)
    timeout_seconds: float = Field(20, gt=0, le=120)
    extraction_timeout_seconds: float = Field(120, gt=0, le=600)
    retries: int = Field(2, ge=0, le=5)
    max_duration_seconds: float = Field(300, gt=0, le=86400)
    per_host_delay: float = Field(1, ge=0, le=60)
    max_download_bytes: int = Field(10_000_000, ge=1024, le=100_000_000)
    max_total_bytes: int = Field(100_000_000, ge=1024, le=2_000_000_000)
    max_sitemaps: int = Field(20, ge=0, le=1000)
    max_links_per_page: int = Field(1000, ge=1, le=10000)
    max_query_variants: int = Field(20, ge=1, le=1000)
    max_redirects: int = Field(5, ge=0, le=20)
    render: Literal["auto", "always", "never"] = "auto"
    render_wait_ms: int = Field(800, ge=0, le=10000)
    max_browser_requests: int = Field(60, ge=1, le=500)
    max_browser_bytes: int = Field(20_000_000, ge=1024, le=100_000_000)
    browser_resource_domains: list[str] = []
    hash_routes: Literal["flag", "follow"] = "flag"
    ocr_enabled: bool = True
    ocr_language: str = "eng"
    max_ocr_pages: int = Field(5, ge=0, le=100)
    max_document_pages: int = Field(100, ge=1, le=1000)
    max_image_pixels: int = Field(20_000_000, ge=1000, le=100_000_000)
    ocr_timeout_seconds: float = Field(20, gt=0, le=120)
    min_ocr_confidence: float = Field(60, ge=0, le=100)
    min_image_width: int = Field(250, ge=1)
    min_image_height: int = Field(100, ge=1)
    include_images: bool = True
    manual_image_urls: list[str] = []
    remove_selectors: list[str] = []
    repetition_ratio: float = Field(0.6, gt=0, le=1)
    user_agent: str = "SitePrep/0.1 (+local public information collection)"

    @field_validator("allowed_domains", "external_document_domains", "browser_resource_domains")
    @classmethod
    def domains(cls, values):
        for value in values:
            if not value or any(c in value for c in "/:@* "):
                raise ValueError("Domains must be exact hostnames, without schemes, ports or wildcards")
        return [v.lower().encode("idna").decode() for v in values]

    @field_validator("allowed_paths")
    @classmethod
    def paths(cls, values):
        if not values or any(not p.startswith("/") for p in values):
            raise ValueError("allowed_paths must contain absolute URL paths")
        return values

    @field_validator("excluded_patterns")
    @classmethod
    def patterns(cls, values):
        for value in values:
            try:
                re.compile(value)
            except re.error as exc:
                raise ValueError(f"Invalid excluded URL pattern: {value}") from exc
        return values

    @field_validator("remove_selectors")
    @classmethod
    def selectors(cls, values):
        from cssselect import HTMLTranslator, SelectorError

        for value in values:
            try:
                HTMLTranslator().css_to_xpath(value)
            except SelectorError as exc:
                raise ValueError(f"Invalid removal selector: {value}") from exc
        return values

    @classmethod
    def load(cls, path: str | Path | None = None):
        return cls.model_validate(yaml.safe_load(Path(path).read_text()) or {}) if path else cls()


class FixtureAccess(BaseModel):
    """Test harness capability; deliberately unavailable in public YAML/CLI/UI."""

    origin: str
