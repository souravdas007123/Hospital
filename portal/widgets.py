from django import forms
from django.urls import reverse

from .lookups import LOOKUPS


class LookupSelect(forms.Select):
    """A select that only contains the chosen record; the rest is fetched
    from the server while typing (see ``lookups.py`` and the script in
    ``base.html``)."""

    def __init__(self, key, attrs=None):
        super().__init__(attrs)
        self.key = key

    def get_context(self, name, value, attrs):
        attrs = dict(attrs or {})
        attrs["data-lookup"] = reverse("portal:lookup", kwargs={"key": self.key})
        return super().get_context(name, value, attrs)

    def optgroups(self, name, value, attrs=None):
        empty = self.create_option(name, "", "— type to search —", False, 0)
        options = [empty]

        chosen = [v for v in (value or []) if v not in (None, "")]
        if chosen:
            label = LOOKUPS[self.key]["label"]
            queryset = self.choices.queryset.filter(pk__in=chosen)

            for index, obj in enumerate(queryset, start=1):
                options.append(
                    self.create_option(
                        name, obj.pk, label(obj), True, index
                    )
                )

        return [(None, options, 0)]
