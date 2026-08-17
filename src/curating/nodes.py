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
    for text, url in nodes:
        stripped = re.sub(_WHITESPACE_REGEX, ' ', text)
        if not url and result and not result[-1][1]:
            result[-1] = (f'{result[-1][0]} {stripped}', '')
        else:
            result.append((stripped, url))

    return result


def get_cell_nodes(cell: element.Tag) -> list[tuple[str, str]]:
    """Recursively decompose `cell` into (text, url) leaf nodes; see get_nodes() for the rules.

    Returns:
        (text, url) tuples in document order, normalized
    """
    return get_nodes(cell.children)


def get_nodes(nodes: Iterator) -> list[tuple[str, str]]:
    """Recursively decompose a node stream into (text, url) leaf nodes; see _gen_nodes() for the rules.

    The result is run through _normalize_spec_info() once, after the full recursive decomposition.

    Returns:
        (text, url) tuples in document order, normalized
    """
    return _normalize_spec_info(list(_gen_nodes(nodes)))


def _gen_nodes(nodes: Iterator) -> Iterator[tuple[str, str]]:
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
                yield from _gen_nodes(child.children)
        else:
            text = str(child).strip()
            if text:
                yield text, ''


def _normalize_spec_info(nodes: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Remove redundant nodes from the parsed info.

    Returns:
        `nodes` with the redundant nodes stripped
    """
    if nodes and nodes[0][0] in {'A', 'An'}:
        nodes = nodes[1:]
    if nodes and nodes[-1][0] == '.':
        nodes = nodes[:-1]
    return nodes


def is_link(node: tuple[str, str]) -> bool:
    return bool(node[1])


def is_text(node: tuple[str, str], text: str) -> bool:
    return node[1] == '' and node[0] == text
