"""Days of Cover: a supply chain stress test.

How long can you keep shipping if a supplier, port or route goes down,
and what is the cheapest fix.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("daysofcover")
except PackageNotFoundError:  # running from a source checkout without an install
    __version__ = "0.0.0"

__all__ = ["__version__"]
