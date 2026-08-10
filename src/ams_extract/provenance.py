"""Build-derived provenance strings for artifacts emitted by ams-extract."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

PACKAGE_NAME = "ams-extract"


def package_version() -> str:
    """Return the version embedded in the installed distribution metadata.

    Emitted datasets and ground truths are auditable artifacts.  They must name
    the build that produced them, rather than silently substituting a source-tree
    placeholder when the package has not been installed.
    """
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError as exc:
        raise RuntimeError(
            "ams-extract must be installed before emitting versioned provenance"
        ) from exc


def producer_name() -> str:
    """Return the producer identifier used in emitted provenance."""
    return f"{PACKAGE_NAME} {package_version()}"
