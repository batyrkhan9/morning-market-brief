"""SEC EDGAR: filings, company facts (XBRL), and 10-K sections.

Requires a User-Agent header with a contact email. Max 10 requests per second.
"""


def get_recent_filings(cik):
    raise NotImplementedError


def get_company_facts(cik):
    raise NotImplementedError


def get_10k_sections(cik):
    raise NotImplementedError
