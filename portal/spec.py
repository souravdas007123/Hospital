"""Small description objects used by the registry (no model imports here)."""


class Inline:
    """A table of child rows shown under a form (e.g. test lines).

    ``factory(extra)`` returns a formset class. ``edit_only`` rows appear only
    when editing an existing record (useful when the rows depend on a choice
    made in the main form).
    """

    def __init__(self, prefix, title, factory, hint="", edit_only=False):
        self.prefix = prefix
        self.title = title
        self.factory = factory
        self.hint = hint
        self.edit_only = edit_only


class Action:
    """A button on a list row.

    * ``run(obj, request)`` (or ``run(obj, request, data)`` when ``form`` is
      given) performs the work and returns a success message. It may raise
      ``ValidationError`` to show an error instead.
    * ``link(obj)`` makes it a plain link instead (opens another page).
    * ``visible(obj)`` decides whether the button shows for a row.
    * ``perm`` is a model permission action ("change", "add" ...) or a full
      ``app.codename`` string; it defaults to "change".
    * ``form`` is a Django form class asked before running (a reason, the
      discharge summary ...).
    """

    def __init__(
        self,
        key,
        label,
        run=None,
        link=None,
        visible=None,
        perm="change",
        style="",
        confirm="",
        form=None,
        new_tab=False,
    ):
        self.key = key
        self.label = label
        self.run = run
        self.link = link
        self.visible = visible
        self.perm = perm
        self.style = style
        self.confirm = confirm
        self.form = form
        self.new_tab = new_tab
