
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    __version__ = _version("echo-mem")
except PackageNotFoundError:  # a source checkout with nothing installed
    __version__ = "0+unknown"
