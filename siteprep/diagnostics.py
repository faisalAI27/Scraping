"""Recognize access failures without attempting to solve website challenges."""

import re


def access_issue(status, body, headers=None):
    sample = body[:65536].lower()
    headers = {k.lower(): v.lower() for k, v in (headers or {}).items()}
    cloudflare_marker = b"_cf_chl_opt" in sample or b"/cdn-cgi/challenge-platform/" in sample
    challenge_title = re.search(rb"<title[^>]*>\s*(just a moment|attention required)", sample)
    if headers.get("cf-mitigated") == "challenge" or (cloudflare_marker and challenge_title):
        return "website_challenge"
    if status in {401, 403}:
        return "access_denied"
    if status == 429:
        return "rate_limited"
    return None


def saved_access_issues(store, job_id, sources):
    """Also diagnose old saved jobs, without changing their history or using network."""
    issues = []
    for source in sources:
        if not source.get("resource_id") or source.get("role") == "encoded_transport":
            continue
        issue = source.get("access_issue")
        if not issue:
            try:
                with (store.job_dir(job_id) / source["path"]).open("rb") as stream:
                    body = stream.read(65536)
                issue = access_issue(source["http_status"], body, source.get("headers"))
            except OSError:
                continue
        if issue:
            issues.append(
                {
                    "url": source["final_url"],
                    "http_status": source["http_status"],
                    "issue": issue,
                    "source_id": source["source_id"],
                }
            )
    return issues
