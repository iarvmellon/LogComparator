from pathlib import Path

from nicegui import app, ui

ASSETS = Path(__file__).with_name('assets')


def register_assets():
    app.add_static_files('/logcomparator-assets', ASSETS)


class DiffView(ui.element, component='diff_view.js'):
    """A local, read-only diff2html comparison with synchronized panes."""
    def __init__(self, diff: str):
        super().__init__()
        self.props['diff'] = diff
        self.classes('w-full')

    def next_difference(self):
        self.run_method('navigate', 1)

    def previous_difference(self):
        self.run_method('navigate', -1)
