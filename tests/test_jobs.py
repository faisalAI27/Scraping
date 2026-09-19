import pytest
from pydantic import ValidationError
from siteprep.config import Config
from siteprep.storage import Store


def test_durable_jobs_are_isolated_and_cancellable(tmp_path):
    store = Store(tmp_path)
    a = store.create("https://example.com", Config())
    b = store.create("https://example.com", Config())
    store.enqueue(a, "https://example.com/")
    Store(tmp_path).cancel(a)
    assert Store(tmp_path).job(a)["status"] == "cancelled"
    assert store.resources(b) == []
    assert len(store.resources(a)) == 1


def test_configuration_errors_are_explicit():
    with pytest.raises(ValidationError):
        Config(max_resources=0)
    with pytest.raises(ValidationError):
        Config(allow_private=True)
    with pytest.raises(ValidationError):
        Config(allowed_domains=["https://example.com"])


def test_invalid_regex_and_css_selectors_are_configuration_errors():
    with pytest.raises(ValidationError, match="Invalid excluded URL pattern"):
        Config(excluded_patterns=["["])
    with pytest.raises(ValidationError, match="Invalid removal selector"):
        Config(remove_selectors=["???"])


def test_site_profiles_require_exact_host_and_ignore_unscoped_defaults(tmp_path):
    from siteprep.config import site_profile

    (tmp_path / "config.example.yaml").write_text("browser_resource_domains: [wrong.example]\n")
    (tmp_path / "config.site.yaml").write_text(
        "allowed_domains: [site.example]\nbrowser_resource_domains: [cdn.example]\ntimeout_seconds: 90\n"
    )
    assert site_profile("https://site.example/path", tmp_path).browser_resource_domains == ["cdn.example"]
    assert site_profile("https://sub.site.example/", tmp_path) is None
    assert site_profile("https://site.example.evil.test/", tmp_path) is None
    assert site_profile("https://other.example/", tmp_path) is None
    assert site_profile("https://[", tmp_path) is None
