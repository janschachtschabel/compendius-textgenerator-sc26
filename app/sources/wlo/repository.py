"""The edu-sharing repository a request names (D45): caller input, so only allowed hosts over https pass.

A request may name the repository its node lives in, and the service then connects to that address - a request
target on the server's side. So only hosts on the allowlist (``EDU_SHARING_REPOSITORIES`` plus the configured
repository) pass, only https on the default port, no credentials in the address, and of the path nothing but the
usual ways of writing the REST root: the service always asks ``https://<host>/edu-sharing/rest``.
"""

from __future__ import annotations

from collections.abc import Set as AbstractSet
from urllib.parse import urlsplit

REST_ROOT = "/edu-sharing/rest"
_ROOT_PATHS = frozenset({"", "/", "/edu-sharing", "/edu-sharing/", REST_ROOT, REST_ROOT + "/"})


class RepositoryNotAllowedError(ValueError):
    """The address names no allowed repository."""


def repository_root(value: str, allowed_hosts: AbstractSet[str]) -> str:
    """The REST root of an allowed repository, from the ways callers write its address."""
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError as exc:  # brackets around no IP address, characters invalid under NFKC, a port that is no number
        raise _refused(value, allowed_hosts) from exc
    host = parts.hostname or ""
    if (
        parts.scheme.lower() != "https"
        or host not in allowed_hosts
        or parts.username is not None
        or parts.password is not None
        or port is not None
        or parts.query
        or parts.fragment
        or parts.path not in _ROOT_PATHS
    ):
        raise _refused(value, allowed_hosts)
    return f"https://{host}{REST_ROOT}"


def _refused(value: str, allowed_hosts: AbstractSet[str]) -> RepositoryNotAllowedError:
    return RepositoryNotAllowedError(
        f"Repository nicht erlaubt: {value!r}; erlaubt sind https-Adressen von {', '.join(sorted(allowed_hosts))}"
    )
