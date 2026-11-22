"""`KeyFooter`: Textual's footer, where the keys that matter most keep their place.

The keys a screen shows come first, then the app's own (Back, Help, Quit). On a narrow terminal
the last ones fall off the end, so the Workbench shortcuts, which are extras, give way first: when
every key won't fit, the footer leaves those out. They still work and help still lists them.
"""

from __future__ import annotations

from rich.cells import cell_len
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Footer
from textual.widgets._footer import FooterKey

EXTRA_ACTION = "app.workbench("
KEY_PADDING = 3
PALETTE_ROOM = 11
"""The palette key on the right: a divider, `^p` and `Palette`."""


def is_extra(binding: Binding) -> bool:
    return binding.action.startswith(EXTRA_ACTION)


class KeyFooter(Footer):
    """See the module docstring."""

    def key_width(self, binding: Binding) -> int:
        return cell_len(self.app.get_key_display(binding)) + cell_len(binding.description) + KEY_PADDING

    def compose(self) -> ComposeResult:
        if not self._bindings_ready:
            return
        shown: dict[str, tuple[Binding, bool, str]] = {}
        for _node, binding, enabled, tooltip in self.screen.active_bindings.values():
            if binding.show and binding.action not in shown:
                shown[binding.action] = (binding, enabled, tooltip)
        room = self.app.size.width - (PALETTE_ROOM if self.show_command_palette else 0)
        if sum(self.key_width(b) for b, _, _ in shown.values()) > room:
            shown = {action: entry for action, entry in shown.items() if not is_extra(entry[0])}
        self.styles.grid_size_columns = len(shown)
        for binding, enabled, tooltip in shown.values():
            yield FooterKey(
                binding.key,
                self.app.get_key_display(binding),
                binding.description,
                binding.action,
                disabled=not enabled,
                tooltip=tooltip,
            ).data_bind(compact=Footer.compact)
        if self.show_command_palette and self.app.ENABLE_COMMAND_PALETTE:
            palette = self.screen.active_bindings.get(self.app.COMMAND_PALETTE_BINDING)
            if palette is not None:
                _node, binding, enabled, tooltip = palette
                yield FooterKey(
                    binding.key,
                    self.app.get_key_display(binding),
                    binding.description,
                    binding.action,
                    classes="-command-palette",
                    disabled=not enabled,
                    tooltip=binding.tooltip or binding.description,
                )
