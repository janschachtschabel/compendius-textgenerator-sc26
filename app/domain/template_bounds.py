"""The bounds of a template's id and blocks, which the requests check as the templates do."""

from __future__ import annotations

# A template id names the file it is stored in: letters, digits, underscore and hyphen, nothing that leads out of
# the directory (audit 2026-09-27, SE-09)
TEMPLATE_ID_PATTERN = r"^[\w-]{1,80}$"
# Bounds of a template's blocks, and of the names regenerate_sections may send (audit 2026-09-28, SE-15): sc26
# has 13 blocks, and a block id is as short as a template id
MAX_SLOTS = 60
SLOT_ID_MAX_CHARS = 80
