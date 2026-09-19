from siteprep.diagnostics import access_issue
from siteprep.fetch import Response


def test_challenge_is_identified_even_with_success_status():
    body = b'<title>Just a moment...</title><script src="/cdn-cgi/challenge-platform/test"></script>'
    for status in (200, 403, 503):
        assert access_issue(status, body) == "website_challenge"
        assert (
            Response(body, "https://example.com/", status, {}).metadata()["access_issue"]
            == "website_challenge"
        )
    assert access_issue(403, b"<p>Forbidden</p>") == "access_denied"
    assert access_issue(200, b"<p>Article about Cloudflare and _cf_chl_opt.</p>") is None
