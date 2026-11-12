"""Prebuilt themes a configuration can name.

A theme only changes how login pages look. Its stylesheet loads after the
shared theme stylesheet and must not add, hide, or reword any text.
"""

THEMES = {
    "cloud": {
        "label": "Cloud",
        "description": "Blue buttons and a white card on a pale gray page.",
    },
    "canvas": {
        "label": "Canvas",
        "description": "Dark buttons and soft gray fields on plain white.",
    },
}
