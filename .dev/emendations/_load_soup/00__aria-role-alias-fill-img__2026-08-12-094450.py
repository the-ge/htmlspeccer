import copy

from bs4 import BeautifulSoup

description = "copy 'image' role's structural data table onto 'img' (alias)"


def emend(section: str, soup: BeautifulSoup) -> bool:
    """`section` here is the PAGE name (_load_soup's argument), not an output section name.

    Returns:
        True if it applied, False if not
    """
    if section != 'aria':
        return False

    tgt_section = soup.find('section', {'id': 'img'})
    src_section = soup.find('section', {'id': 'image'})
    if tgt_section is None or src_section is None:
        return False
    if tgt_section.find('table', {'class': 'def'}) is not None:
        return False

    src_table = src_section.find('table', {'class': 'def'})
    if src_table is None:
        return False

    tgt_section.append(copy.deepcopy(src_table))
    return True
