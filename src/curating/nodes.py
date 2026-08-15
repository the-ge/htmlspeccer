import logging
import re
from collections.abc import Iterator

from bs4 import element

from config import SPEC_BASE_URL
from util.transforming import normalize_url

logger = logging.getLogger(__name__)

_WHITESPACE_REGEX = re.compile(r'\s+')


def concat_text_nodes(nodes: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Merge contiguous (text, '') tuples in `nodes` into a single tuple, joined by a single space.

    Linked (text, url) tuples (url != '') are left as-is and break up merge runs.

    Returns:
        `nodes` with contiguous plain-text runs merged
    """
    result: list[tuple[str, str]] = []
    if nodes[0][0] in {'A', 'An'}:
        del nodes[0]  # remove leading common sentece parts
    if nodes[-1][0] == '.':
        del nodes[-1]  # remove last dot
    for text, url in nodes:
        stripped = re.sub(_WHITESPACE_REGEX, ' ', text)
        if not url and result and not result[-1][1]:
            result[-1] = (f'{result[-1][0]} {stripped}', '')
        else:
            result.append((stripped, url))

    return result


def gen_nodes(nodes: Iterator) -> Iterator[tuple[str, str]]:
    """Recursively decompose a node stream into (text, url) leaf nodes.

    An <a> tag is an atomic (text, url) leaf using its own href, not descended into. Any other tag is
    transparent: recurse into its children instead of emitting a node for it. Bare text runs become
    (text, '') nodes; whitespace-only text nodes are dropped. Concatenating the first elements with
    spaces approximately restores the source text (whitespace is not preserved exactly).

    Yields:
        (text, url) tuples in document order
    """
    for child in nodes:
        if isinstance(child, element.Tag):
            if child.name == 'a':
                text = child.get_text().strip()
                if text:
                    yield text, normalize_url(child['href'].strip(), SPEC_BASE_URL)
            else:
                yield from gen_nodes(child.children)
        else:
            text = str(child).strip()
            if text:
                yield text, ''


def gen_cell_nodes(cell: element.Tag) -> Iterator[tuple[str, str]]:
    """Recursively decompose `cell` into (text, url) leaf nodes; see gen_nodes() for the rules.

    Yields:
        (text, url) tuples in document order
    """
    yield from gen_nodes(cell.children)


def is_link(node: tuple[str, str]) -> bool:
    return bool(node[1])


def is_text(node: tuple[str, str], text: str) -> bool:
    return node[1] == '' and node[0] == text
