import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config


def make_session() -> requests.Session:
    """HTTP session with retries and exponential backoff for flaky public APIs."""
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": config.USER_AGENT})
    return session
