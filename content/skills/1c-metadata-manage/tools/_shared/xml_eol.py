"""xml_eol.py — keep a metadata file's line endings when a Python tool rewrites it.

The PowerShell writers of this skill keep the input CRLF / LF style and
Configurator's compact empty tags. Their Python peers parse with lxml, and an
XML parser normalises CRLF to LF on the way in (XML 1.0, section 2.11), so a
rewrite came out LF whatever the file had been. Indentation the tools add by
hand still carried "\\r\\n", and lxml serialises a CR in text as the character
reference "&#13;" — every insertion left literal "&#13;" in the file, LF files
included.

Two steps fix both, the same two the PowerShell side takes:

  * ``normalise_layout(root)`` — before serialising, drop CR from the
    whitespace-only text / tail between elements (the indentation). CR inside
    real content is data and is left alone;
  * ``apply(data, eol)`` — after serialising, put the target file's line
    endings back. A file that does not exist yet has no style to keep, and its
    content is written exactly as the tool produced it.

Compact tags need nothing here: lxml already writes ``<Tag/>``.
"""


def target_eol(path):
    """``"\\r\\n"`` or ``"\\n"`` as the existing file uses; ``None`` when there is no file yet."""
    try:
        with open(path, "rb") as handle:
            return "\r\n" if b"\r\n" in handle.read() else "\n"
    except OSError:
        return None


def normalise_layout(tree):
    """Drop CR from whitespace-only text / tail; *tree* is an ElementTree or its root element."""
    root = tree.getroot() if hasattr(tree, "getroot") else tree
    for node in root.iter():
        names = ("text", "tail") if isinstance(node.tag, str) else ("tail",)
        for name in names:
            value = getattr(node, name)
            if value and "\r" in value and not value.strip():
                setattr(node, name, value.replace("\r\n", "\n").replace("\r", "\n"))
    return root


def apply(data, eol):
    """Rewrite the line endings of *data* (``bytes`` or ``str``) to *eol*; ``None`` keeps it as is."""
    if eol is None:
        return data
    if isinstance(data, bytes):
        return data.replace(b"\r\n", b"\n").replace(b"\n", eol.encode("ascii"))
    return data.replace("\r\n", "\n").replace("\n", eol)
