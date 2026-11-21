"""One module per screen. This docstring is the short guide to writing one.

Add a screen
    Subclass `DataScreen[T]` from `screens.base`. Set `what` (shown in "Loading the task...") and
    `crumb` (its label in the breadcrumbs, usually the record's id, set in `__init__`). Take ids
    in the constructor, never records: the screen loads its own data. Other screens reach yours
    only through the app's `open_task`, `open_dataset`, `open_run` and `open_episode`, so if you
    add a new kind of screen, add an `open_*` method to `GauntletApp` too.

Load data
    `fetch(self) -> T` runs in a worker thread. Call `self.source` (a `DataSource`) there and
    nothing else. `build(self, data) -> Iterable[Widget]` runs on the UI thread with the result
    and yields the body. Until `fetch` returns the body shows `Loading`; if it raises, it shows
    `ErrorState` with one plain line. A heavy tab (a patch, a trajectory, 5,000 test ids) goes
    in a `widgets.Deferred(fetch, build, what=...)` inside its `TabPane`, so it loads in its own
    thread the first time the tab is shown.

Show things
    Use the shared widgets: `Facts` for the block at the top, `TabbedContent` below it (`[`, `]`,
    `h` and `l` switch tabs on any screen that has one), `DataGrid` for lists, `FilterBar` above a
    list for `/` and `f`, `DiffView` for patches, `StatusBadge` and `RewardText` for status. Take
    colours and symbols from `self.gauntlet.look` (or `Themed.look` in a widget), never literals.
    Agent-written text always goes through `format.safe_text`. Screen layout goes in
    `gauntlet.tcss`; give panes the `pane` class and a `border_title` for the shared frame.

Keys
    Declare `BINDINGS` on the screen or widget with a description: it then shows in the footer
    (unless `show=False`) and in help (`?`) automatically, grouped under the widget's
    `HELP_GROUP` or "This screen". Use the keys from the design brief, and return False from
    `check_action` for a key that does nothing right now, so it drops out of the footer.
    `enter` on a `DataGrid` posts `DataGrid.Opened`; handle it with `on_data_grid_opened` and
    call an `open_*` method. Override `copy_target` to say what `c` copies.

Test
    Build data with `tests/tui/factories.py` (`make_source()`, `empty_source()`,
    `failing_source()` and the `make_*` builders), then
    `async with GauntletApp(source).run_test(size=(120, 36)) as pilot:`, push your screen with
    the app's `open_*` method, `await pilot.pause()`, and assert on widget state and rendered
    text. Cover its keys, its empty and error states, and a resize to 80x24.
"""
