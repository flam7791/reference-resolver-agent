from refresolver.text import (
    bibliography_section,
    content_words,
    find_dois,
    find_quoted_title,
    find_year,
    normalise,
    split_entries,
)


def test_bibliography_section_starts_at_heading_and_stops_at_next_heading():
    doc = "# Paper\n\nBody text 2020.\n\n## References\n\nA (2020), One.\n\n## Annex\n\nNot a ref."
    section = bibliography_section(doc)
    assert "A (2020), One." in section
    assert "Not a ref" not in section and "Body text" not in section


def test_french_heading_is_recognised():
    assert "X (2021)" in bibliography_section("Texte\n\nRéférences\n\nX (2021), Titre long ici.")


def test_split_numbered_list_joins_wrapped_lines():
    section = (
        "[1] Autor, D. (2015), Why are there still\n    so many jobs?\n"
        "[2] Frey, C. (2017), The future of employment."
    )
    assert split_entries(section) == [
        "Autor, D. (2015), Why are there still so many jobs?",
        "Frey, C. (2017), The future of employment.",
    ]


def test_split_blank_line_separated_entries():
    section = "Autor, D. (2015), Why are there\nstill so many jobs?\n\nFrey, C. (2017), The future."
    assert len(split_entries(section)) == 2


def test_split_one_entry_per_line():
    section = (
        "Autor, D. (2015), Why are there still so many jobs?\nFrey, C. (2017), The future of work."
    )
    assert len(split_entries(section)) == 2


def test_find_dois_strips_trailing_punctuation_and_lowercases():
    text = "See https://doi.org/10.1016/J.TECHFORE.2016.08.019. Also (doi:10.1086/705716)."
    assert find_dois(text) == ["10.1016/j.techfore.2016.08.019", "10.1086/705716"]


def test_find_year_ignores_page_numbers():
    assert find_year("Journal 29(3): 3-30, 2015a.") == 2015
    assert find_year("No year here, pages 1234-1250") is None


def test_find_year_ignores_access_dates():
    # Found in the live evaluation: a web page was linked using the date it was read.
    assert (
        find_year("OECD.AI (n.d.), Live data, https://oecd.ai (accessed 1 September 2026).") is None
    )
    assert find_year("Report (2021), https://x.org, retrieved 3 May 2024") == 2021


def test_normalise_and_content_words():
    assert normalise("Perspectives de l'Emploi : Été") == "perspectives de l emploi ete"
    assert content_words("The future of employment") == {"future", "employment"}


def test_quoted_title_is_found_in_common_styles():
    assert find_quoted_title('Gebru, T. (2021), "Datasheets for datasets", CACM.') == (
        "Datasheets for datasets"
    )
    assert find_quoted_title("OCDE (2023), « Perspectives de l'emploi », Paris.") == (
        "Perspectives de l'emploi"
    )
    assert find_quoted_title("Autor, D. (2015), Why are there still so many jobs?") is None
