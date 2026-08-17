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

    The result is run through _prune_nodes() once, after the full recursive decomposition.

    Returns:
        (text, url) tuples in document order, normalized
    """
    return prune_nodes(list(_gen_nodes(nodes)), {0: {'A', 'An'}, -1: {'.'}})


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


def prune_nodes(
    nodes: list[tuple[str, str]],
    prunings: dict[int | str, set[str]],
    match_mode: str = 'all',
) -> list[tuple[str, str]]:
    """Remove nodes from the parsed info nodes.

    `prunings` keys are either an int (positional: prune the node at that index if its text is in the
    paired set) or the literal string 'match' (prune by text value, anywhere in `nodes`, regardless of
    position). Positional entries are applied first, in dict order; 'match' (if present) is applied
    last, against whatever remains after positional pruning.

    `match_mode` controls 'match' pruning: 'all' drops every node whose text is in the paired set;
    'first' drops only the first (document-order) matching node.

    Returns:
        `nodes` with the redundant nodes stripped

    Raises:
        ValueError: if `prunings` has a key other than an int or 'match'
    """
    for index, values in prunings.items():
        if not isinstance(index, int) and index != 'match':
            msg = f'prunings keys must be an int or "match", got {index!r}'
            raise ValueError(msg)
        if index == 'match':
            continue
        if not nodes:
            continue
        i = index if index >= 0 else len(nodes) + index  # negative index: upper-bounded by len(nodes) above
        if 0 <= i < len(nodes) and nodes[i][0] in values:
            nodes = nodes[:i] + nodes[i + 1:]

    if 'match' in prunings:
        nodes = prune_matched_nodes(nodes, prunings['match'], match_mode)

    return nodes


def prune_matched_nodes(
    nodes: list[tuple[str, str]],
    cases: set[str],
    match_mode: str = 'all',
) -> list[tuple[str, str]]:
    """Remove nodes by text value, anywhere in `nodes`, regardless of position.

    `match_mode` controls 'match' pruning: 'all' drops every node whose text is in the paired set;
    'first' drops only the first (document-order) matching node.

    Returns:
        `nodes` with the matched nodes stripped

    Raises:
        ValueError: if `match_mode` is not 'all' or 'first'
    """
    if match_mode not in {'all', 'first'}:
        msg = f'match_mode must be "all" or "first", got {match_mode!r}'
        raise ValueError(msg)

    if match_mode == 'all':
        nodes = [n for n in nodes if n[0] not in cases]
    else:
        for i, n in enumerate(nodes):
            if n[0] in cases:
                nodes = nodes[:i] + nodes[i + 1:]
                break

    return nodes


def is_link(node: tuple[str, str]) -> bool:
    return bool(node[1])


def is_text(node: tuple[str, str], text: str) -> bool:
    return node[1] == '' and node[0] == text
