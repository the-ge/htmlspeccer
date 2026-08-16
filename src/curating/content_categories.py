import logging
from collections.abc import Iterator

from bs4 import BeautifulSoup, element

from config import SPEC_BASE_URL
from curating.nodes import concat_text_nodes, get_nodes, is_link, is_text
from schema import ContentCategoryData
from util.transforming import normalize_url

logger = logging.getLogger(__name__)

# Bare (non-<code>-wrapped, non-MathML/SVG) anchor text found in a content-category elements/exceptions
# cell -> pseudo-tag name. The leading '_' guarantees no collision with any real HTML/SVG/MathML tag
# name (which must start with a letter) or with a hyphenated custom element tag name. Any other bare
# anchor text is unrecognized (warned and skipped).
_CONTENT_CATEGORY_SPECIAL_TAGS = {
    'autonomous custom elements': '_custom-autonomous',
    'form-associated custom elements': '_custom-form-associated',
    'Text': '_text',
}
# Expected cell count
_HTML_CELL_COUNT = 3


def _parse_content_category_tag(a: element.Tag) -> tuple[str, str] | None:
    """Resolve one <a> node from a content-category cell into (tag, url).

    A <code>-wrapped anchor is a real tag: its own text is the tag name, its own href is the url. A
    bare anchor with a <code> child (e.g. "MathML <code>math</code>") uses the <code> text as the tag
    name and the anchor's own href as the url. Any other bare anchor is looked up in
    _CONTENT_CATEGORY_SPECIAL_TAGS; not found is warned and skipped.

    Returns:
        (tag, url), or None if the anchor is an unrecognized bare anchor
    """
    url = normalize_url(a['href'].strip(), SPEC_BASE_URL)
    if a.find_parent('code') is not None:
        return a.get_text().strip(), url
    code = a.find('code')
    if code is not None:
        return code.get_text().strip(), url
    text = a.get_text().strip()
    tag = _CONTENT_CATEGORY_SPECIAL_TAGS.get(text)
    if tag is None:
        logger.warning('⚠️ Content category: unrecognized special element phrase %r', text)
        return None
    return tag, url


def _parse_content_category_elements(cell: element.Tag) -> list[tuple[str, str]]:
    """Parse a content-category "Elements" cell into (tag, url) pairs, in document order.

    Returns:
        List of (tag, url) pairs; unrecognized bare anchors are skipped (warned)
    """
    result = []
    for a in cell.find_all('a'):
        parsed = _parse_content_category_tag(a)
        if parsed is not None:
            result.append(parsed)
    return result


def _gen_content_category_groups(cell: element.Tag) -> Iterator[list]:
    """Split a content-category "Elements with exceptions" cell into per-item node groups.

    Items are delimited by a ';' inside a top-level text node; the ';' itself and surrounding
    whitespace are dropped. Nested tags (e.g. an <a> spanning "hierarchically correct main element")
    are never split, since only the cell's direct children stream is scanned for the boundary.

    Yields:
        Lists of nodes (Tag objects and stripped str fragments) making up one item
    """
    group: list = []
    for child in cell.children:
        if isinstance(child, element.Tag):
            group.append(child)
            continue
        text = str(child)
        while ';' in text:
            before, text = text.split(';', 1)
            before = before.strip()
            if before:
                group.append(before)
            if group:
                yield group
            group = []
        text = text.strip()
        if text:
            group.append(text)
    if group:
        yield group


def _parse_content_category_subject(node: object) -> tuple[str, str] | None:
    """Resolve a content-category exception item's subject node into (tag, url).

    Returns:
        (tag, url), or None if `node` isn't a recognized <code> or <a> subject
    """
    if not isinstance(node, element.Tag):
        return None
    if node.name == 'code':
        a = node.find('a')
        return None if a is None else (a.get_text().strip(), normalize_url(a['href'].strip(), SPEC_BASE_URL))
    if node.name == 'a':
        return _parse_content_category_tag(node)
    return None


def _strip_condition_wrapper(nodes: list) -> list:
    """Strip an optional leading '(' + 'if ' and an optional trailing ')' from an exception's condition.

    Some conditions are wrapped, e.g. "(if it is a descendant of a map element)"; others are bare
    prose with no parens or 'if' at all, e.g. "that is not inter-element whitespace". Only present
    wrapper characters are stripped; `nodes` is otherwise returned unchanged.

    Returns:
        `nodes` with any wrapping '(' + 'if ' / ')' stripped
    """
    nodes = list(nodes)
    if nodes and isinstance(nodes[0], str) and nodes[0].startswith('('):
        nodes[0] = nodes[0].removeprefix('(').strip().removeprefix('if ').strip()
        if not nodes[0]:
            nodes = nodes[1:]
    if nodes and isinstance(nodes[-1], str) and nodes[-1].endswith(')'):
        nodes[-1] = nodes[-1].removesuffix(')').strip()
        if not nodes[-1]:
            nodes = nodes[:-1]
    return nodes


def _match_condition_pattern(nodes: list[tuple[str, str]], pattern: str) -> list[tuple[str, str]] | None:
    """Match a (post-concat_text_nodes()) condition against a fixed lead/link/text `pattern`.

    `pattern` is plain text with '_LINK_' placeholders marking where a link ((text, url) with
    url != '') must appear; the text between/around placeholders (once split on '_LINK_' and each
    segment stripped) must match a plain-text ((text, '')) node exactly. The node count implied by
    `pattern` is checked against `len(nodes)` first. Only fits a fixed node count; a variable-arity
    shape (e.g. a repeated link group) needs its own rule.

    Returns:
        The captured link tuples, in pattern order, or None if `nodes` doesn't match
    """
    segments = [s.strip() for s in pattern.split('_LINK_')]
    expected: list[str | None] = []  # None marks a link slot; str marks a required literal-text slot
    for i, text in enumerate(segments):
        if text:
            expected.append(text)
        if i < len(segments) - 1:
            expected.append(None)
    if len(expected) != len(nodes):
        return None

    links = []
    for node, want in zip(nodes, expected, strict=True):
        if want is None:
            if not is_link(node):
                return None
            links.append(node)
        elif not is_text(node, want):
            return None
    return links


def _simplify_condition_descendant(nodes: list[tuple[str, str]]) -> list[tuple[str, str]] | None:
    # "it is a descendant of a _LINK_ element" -> ["descendant of", link]
    links = _match_condition_pattern(nodes, 'it is a descendant of a _LINK_ element')
    return None if links is None else [('descendant of', ''), *links]


def _simplify_condition_bare_link(nodes: list[tuple[str, str]]) -> list[tuple[str, str]] | None:
    # "it is _LINK_" | "it is a _LINK_" -> [link]
    for pattern in ('it is _LINK_', 'it is a _LINK_'):
        links = _match_condition_pattern(nodes, pattern)
        if links is not None:
            return links
    return None


def _simplify_condition_attribute_present(nodes: list[tuple[str, str]]) -> list[tuple[str, str]] | None:
    # ["the", link (, "or", link)*, "attribute is present"] -> ["attribute is present", link, link, ...]
    # Variable link count (img's "usemap or controls"), so this doesn't fit _match_condition_pattern's
    # fixed min_node_count; kept as its own loop-based rule.
    min_node_count = 3
    if (
        len(nodes) < min_node_count
        or not is_text(nodes[0], 'the')
        or not is_text(nodes[-1], 'attribute is present')
    ):
        return None
    links = []
    middle = nodes[1:-1]
    i = 0
    while i < len(middle):
        if not is_link(middle[i]):
            return None
        links.append(middle[i])
        i += 1
        if i < len(middle):
            if not is_text(middle[i], 'or'):
                return None
            i += 1
    return [('attribute is present', ''), *links] if links else None


def _simplify_condition_input_state(nodes: list[tuple[str, str]]) -> list[tuple[str, str]] | None:
    # "the _LINK_ attribute is not in the _LINK_ state" -> ["attribute is not in state", link, link]
    links = _match_condition_pattern(nodes, 'the _LINK_ attribute is not in the _LINK_ state')
    return None if links is None else [('attribute is not in state', ''), *links]


def _simplify_condition_child_element(nodes: list[tuple[str, str]]) -> list[tuple[str, str]] | None:
    # "the element's children include at least one _LINK_ element" -> ["at least one child", link]
    links = _match_condition_pattern(nodes, "the element's children include at least one _LINK_ element")
    return None if links is None else [('at least one child', ''), *links]


# Literal structural condition-simplification rules, tried in order; first match wins. Each rule
# matches an exact lead/tail text shape observed in the source's exception prose; an unmatched shape
# passes through untouched. Rules are mutually exclusive by construction (distinct lead/tail literals
# and/or tuple counts), so match order doesn't affect the result.
_CONDITION_SIMPLIFY_RULES = (
    _simplify_condition_descendant,
    _simplify_condition_bare_link,
    _simplify_condition_attribute_present,
    _simplify_condition_input_state,
    _simplify_condition_child_element,
)


def _simplify_condition(nodes: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Apply the first matching rule in _CONDITION_SIMPLIFY_RULES to a condition node list.

    Returns:
        The simplified node list, or `nodes` unchanged if no rule matches
    """
    for rule in _CONDITION_SIMPLIFY_RULES:
        result = rule(nodes)
        if result is not None:
            return result
    return nodes


def _parse_content_category_elements_if(cell: element.Tag) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """Parse a content-category "Elements with exceptions" cell into (tag, url, condition) triples.

    Each item's subject (real tag or special node, resolved the same way as the "Elements" column) is
    followed by an optional condition, decomposed into (text, url) node pairs the same way as
    AttributeData.description (see get_nodes()), then run through concat_text_nodes() and
    _simplify_condition(), in that order. A cell containing only '—' (no exceptions) yields nothing.

    Returns:
        List of (tag, url, condition) triples; items with an unrecognized subject are skipped (warned)
    """
    if cell.get_text().strip() == '—':
        return []

    result = []
    for group in _gen_content_category_groups(cell):
        if not group:
            continue
        subject = _parse_content_category_subject(group[0])
        if subject is None:
            logger.warning('⚠️ Content category exception: unrecognized subject node; item skipped: %s', group[0])
            continue
        condition = _simplify_condition(concat_text_nodes(get_nodes(_strip_condition_wrapper(group[1:]))))
        result.append((*subject, condition))
    return result


def parse_content_categories(soup: BeautifulSoup) -> Iterator[ContentCategoryData]:
    # https://html.spec.whatwg.org/multipage/indices.html#element-content-categories
    rows = soup.find('h3', {'id': 'element-content-categories'}).find_next('tbody').find_all('tr')
    count = _HTML_CELL_COUNT
    for row in rows:
        cells = row.find_all(['th', 'td'])
        if len(cells) != count:
            logger.error('❌ Expected %s cells, got %s. Skipping row: %s', count, len(cells), row)
            continue
        name_cell, elements_cell, exceptions_cell = cells
        category = ' '.join(name_cell.get_text().strip().split())
        url = f'https://html.spec.whatwg.org/multipage/{name_cell.a['href']}'

        elements = _parse_content_category_elements(elements_cell)
        elements_if = _parse_content_category_elements_if(exceptions_cell) or None

        yield ContentCategoryData(
            name=category,
            url=url,
            elements=elements,
            elements_if=elements_if,
        )
