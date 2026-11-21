"""Messages the shared widgets post. The app handles `CopyRequested` for every screen."""

from __future__ import annotations

from textual.message import Message


class CopyRequested(Message):
    """Put `text` on the clipboard. `what` names it in the toast, like `id` or `episode id`."""

    def __init__(self, text: str, what: str = "id") -> None:
        super().__init__()
        self.text = text
        self.what = what
