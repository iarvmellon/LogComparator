"""Wrap groups of Tk controls into rows as their container gets narrower."""

def wrap_controls(container, widgets, *, stretch=False):
    widgets = tuple(widgets)
    natural_widths = None
    last_layout = None
    scheduled = None

    def layout():
        nonlocal natural_widths, last_layout, scheduled
        scheduled = None
        if not container.winfo_exists():
            return
        if natural_widths is None:
            natural_widths = [widget.winfo_reqwidth() + 12 for widget in widgets]
        available = max(1, container.winfo_width() - 16)
        positions = []
        row = column = used = 0
        for width in natural_widths:
            if column and used + width > available:
                row += 1
                column = used = 0
            positions.append((row, column))
            column += 1
            used += width
        signature = tuple(positions)
        if signature == last_layout:
            return
        last_layout = signature
        for widget in widgets:
            widget.pack_forget()
            widget.grid_forget()
        for index in range(len(widgets)):
            container.grid_columnconfigure(index, weight=0)
        for widget, (row, column) in zip(widgets, positions):
            widget.grid(row=row, column=column, sticky='ew' if stretch else 'w', padx=6, pady=3)
            if stretch:
                container.grid_columnconfigure(column, weight=1)

    def schedule(event=None):
        nonlocal scheduled
        if event is not None and event.widget is not container:
            return
        if scheduled is None:
            scheduled = container.after_idle(layout)

    container.bind('<Configure>', schedule, add='+')
    schedule()
