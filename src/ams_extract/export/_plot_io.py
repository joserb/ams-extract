"""Shared PNG save helper for the matplotlib renderers.

Lets every ``render_*_png`` accept either a filesystem :class:`~pathlib.Path`
(the ``rbm extract`` / ``rbm export`` case, which creates parent dirs) or a
binary file-like object (the ``rbm serve`` case, which streams the PNG into
an in-memory buffer without touching disk).
"""

# pyright: reportUnknownMemberType=false

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

if TYPE_CHECKING:
    from matplotlib.figure import Figure


def save_png(fig: Figure, path: Path | BinaryIO, *, dpi: int = 120) -> None:
    """Write ``fig`` as a PNG to a path (creating parents) or a file-like."""
    if isinstance(path, Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=dpi)
    else:
        fig.savefig(path, dpi=dpi, format="png")
