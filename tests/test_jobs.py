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
