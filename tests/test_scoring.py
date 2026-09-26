from refresolver.models import Reference
from refresolver.scoring import rank, score, title_similarity, year_similarity

from .conftest import cand


def test_series_editions_are_separated_by_year():
    ref = Reference(
        "R1",
        "OECD (2023), OECD Employment Outlook 2023: Artificial Intelligence and the Labour Market, "
        "OECD Publishing, Paris.",
        year=2023,
    )
    ranked = rank(
        ref,
        [
            cand("10.1787/empl_outlook-2005-en", "OECD Employment Outlook 2005", ["OECD"], 2005),
            cand(
                "10.1787/08785bba-en",
                "OECD Employment Outlook 2023: Artificial Intelligence and the Labour Market",
                ["OECD"],
                2023,
            ),
        ],
    )
    assert ranked[0].identifier == "10.1787/08785bba-en"
    assert ranked[0].score >= 0.85
    assert ranked[0].score - ranked[1].score > 0.2


def test_subtitle_in_registry_but_not_in_citation_still_matches():
    assert (
        title_similarity(
            "On the Dangers of Stochastic Parrots",
            "On the Dangers of Stochastic Parrots: Can Language Models Be Too Big?",
        )
        == 1.0
    )


def test_containment_needs_three_words():
    # "Science" alone is contained in the citation, but must not count as a title match.
    assert title_similarity("Experimental evidence on productivity, Science", "Science") < 0.5


def test_year_similarity():
    assert year_similarity(2015, 2015) == 1.0
    assert year_similarity(2016, 2015) == 0.6  # online-first versus print
    assert year_similarity(2019, 2015) == 0.0
    assert year_similarity(None, 2015) == 0.5


def test_authors_found_in_raw_citation_when_not_parsed():
    ref = Reference("R1", "Acemoglu, D. and P. Restrepo (2020), Robots and jobs, JPE.", year=2020)
    scored = score(ref, cand("10.1086/705716", "Robots and Jobs", ["Acemoglu", "Restrepo"], 2020))
    assert scored.score_detail["authors"] == 1.0


def test_score_detail_is_explainable():
    ref = Reference("R1", "Autor, D. (2016), Why are there still so many jobs?", year=2016)
    scored = score(
        ref,
        cand(
            "10.1257/jep.29.3.3",
            "Why Are There Still So Many Jobs? The History and Future of Workplace Automation",
            ["Autor"],
            2015,
        ),
    )
    assert set(scored.score_detail) == {"title", "year", "authors"}
    assert scored.score_detail["year"] == 0.6
    assert scored.score >= 0.85  # a one-year slip should not block an otherwise clear match
