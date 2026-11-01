"""Merge the caokit-managed block into a project .gitignore."""

BEGIN = "# >>> caokit >>>"
END = "# <<< caokit <<<"
# Ignore everything under .company/ except contracts/, which the team tracks.
RULES = [".company/*", "!.company/contracts/"]


def merge_gitignore(existing: str) -> str:
    """Return ``existing`` with the caokit block added or replaced in place.

    Existing content, ordering and line endings are preserved, and the result
    is idempotent: merging twice changes nothing.

    Args:
        existing: Current .gitignore text (may be empty).

    Returns:
        The .gitignore text containing exactly one caokit block.
    """
    # Match the file's own line ending so a CRLF file does not end up mixed.
    nl = "\r\n" if "\r\n" in existing else "\n"
    block = nl.join([BEGIN, *RULES, END])
    lines = existing.split(nl)
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == BEGIN)
        end = next(i for i, line in enumerate(lines) if i > start and line.strip() == END)
    except StopIteration:
        start = end = -1  # no complete block found: append a new one
    if start >= 0:
        # Replace our previous block (possibly stale rules) where it stands.
        lines[start : end + 1] = block.split(nl)
        return nl.join(lines)
    if existing and not existing.endswith(nl):
        existing += nl  # file lacked a trailing newline; do not glue onto the last rule
    return existing + block + nl
