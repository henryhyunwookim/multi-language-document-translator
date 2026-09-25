"""Equivalent Office representations used for per-occurrence text addresses."""
from copy import deepcopy

S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def expand_shared_cells(root, shared_strings):
    """Inline shared strings per cell while preserving rich-text run properties.

    Shared strings are a storage optimization, not a translation boundary. Two
    cells referring to one string need distinct IDs and independent context.
    The original shared-string part remains untouched as an opaque package part.
    """
    if shared_strings is None:
        return
    entries = shared_strings.findall(f"{{{S}}}si")
    for cell in root.iter(f"{{{S}}}c"):
        value = cell.find(f"{{{S}}}v")
        if cell.get("t") != "s" or value is None or cell.find(f"{{{S}}}f") is not None:
            continue
        index = int(value.text)
        if index < 0 or index >= len(entries):
            raise ValueError("Shared-string reference is out of range.")
        inline = deepcopy(entries[index])
        inline.tag = f"{{{S}}}is"
        position = cell.index(value)
        cell.remove(value)
        cell.insert(position, inline)
        cell.set("t", "inlineStr")
