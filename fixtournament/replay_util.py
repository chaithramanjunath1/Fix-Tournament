"""Helpers for writing replay scripts."""


def blk(path: str, search: str, replace: str) -> str:
    """Format one SEARCH/REPLACE edit block."""
    s = f"{search}\n" if search else ""
    return f"FILE: {path}\n<<<<<<< SEARCH\n{s}=======\n{replace}\n>>>>>>> REPLACE\n"


def reply(note: str, *blocks: str) -> str:
    return note + "\n\n" + "\n".join(blocks)
