"""PubMed / NCBI E-utilities adapter.

PubMed is the most reliable source of the trial->publication link: when an
article names a registry identifier, NLM records it as a DataBank accession
number. That gives us the "easy case" of section 8 with no guessing at all.
"""

import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from ..models.core import Author, Paper, Provenance
from .clinical_trials import extract_nct_ids
from .http import SourceError, get_text

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _text(node: Optional[ET.Element]) -> Optional[str]:
    """Flatten an element's text, including any inline markup children."""
    if node is None:
        return None
    return "".join(node.itertext()).strip() or None


def _publication_date(article: ET.Element) -> Optional[str]:
    """Prefer the electronic/print article date; fall back to the journal issue."""
    for path in (".//ArticleDate", ".//Journal/JournalIssue/PubDate"):
        node = article.find(path)
        if node is None:
            continue
        year = node.findtext("Year")
        if not year:
            # PubDate is sometimes only a MedlineDate string such as "2023 Feb-Mar".
            medline = node.findtext("MedlineDate")
            if medline:
                return medline.split()[0]
            continue
        month = node.findtext("Month") or "01"
        day = node.findtext("Day") or "01"
        months = {
            "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
            "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
            "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
        }
        month = months.get(month[:3], month)
        return "{}-{:0>2}-{:0>2}".format(year, month, day)
    return None


def _authors(article: ET.Element) -> List[Author]:
    authors: List[Author] = []
    nodes = article.findall(".//AuthorList/Author")
    for index, node in enumerate(nodes):
        last = node.findtext("LastName")
        fore = node.findtext("ForeName")
        name = " ".join(part for part in (fore, last) if part) or node.findtext(
            "CollectiveName"
        )
        if not name:
            continue
        orcid = None
        for ident in node.findall("Identifier"):
            if ident.get("Source") == "ORCID":
                orcid = (ident.text or "").strip()
        position = "middle"
        if index == 0:
            position = "first"
        elif index == len(nodes) - 1:
            position = "last"
        authors.append(
            Author(
                name=name,
                orcid=orcid,
                institutions=[
                    text
                    for text in (
                        _text(aff) for aff in node.findall(".//AffiliationInfo/Affiliation")
                    )
                    if text
                ],
                position=position,
            )
        )
    return authors


def _abstract_sections(article: ET.Element) -> Dict[str, str]:
    """Return labeled abstract sections, e.g. {"RESULTS": "...", ...}.

    Keeping sections separate lets downstream extraction send only the relevant
    part of an abstract to an LLM instead of the whole document.
    """
    sections: Dict[str, str] = {}
    for index, node in enumerate(article.findall(".//Abstract/AbstractText")):
        label = node.get("Label") or node.get("NlmCategory") or "ABSTRACT"
        if label in sections:
            label = "{} ({})".format(label, index)
        body = _text(node)
        if body:
            sections[label] = body
    return sections


def _article_ids(citation: ET.Element) -> Dict[str, str]:
    """Read ids from PubmedData only.

    The reference list also contains ArticleId elements, so a document-wide
    search would happily return a cited paper's DOI as this paper's DOI.
    """
    ids: Dict[str, str] = {}
    for node in citation.findall("./PubmedData/ArticleIdList/ArticleId"):
        id_type = node.get("IdType")
        if id_type and node.text:
            ids[id_type] = node.text.strip()
    return ids


def parse_pubmed_article(citation: ET.Element) -> Paper:
    """Normalize a single <PubmedArticle> element into a `Paper`."""
    article = citation.find(".//Article")
    if article is None:
        raise SourceError("PubMed record is missing an Article element")

    ids = _article_ids(citation)
    pmid = ids.get("pubmed") or citation.findtext(".//MedlineCitation/PMID")
    sections = _abstract_sections(article)

    # A registry id can appear as a DataBank accession (authoritative) or only
    # in the abstract text (still declared by the article itself).
    declared_ncts: List[str] = []
    for bank in citation.findall(".//DataBankList/DataBank"):
        if (bank.findtext("DataBankName") or "").lower() == "clinicaltrials.gov":
            for accession in bank.findall(".//AccessionNumber"):
                for nct in extract_nct_ids(accession.text):
                    if nct not in declared_ncts:
                        declared_ncts.append(nct)
    for nct in extract_nct_ids(" ".join(sections.values())):
        if nct not in declared_ncts:
            declared_ncts.append(nct)

    return Paper(
        title=_text(article.find("ArticleTitle")) or "",
        doi=ids.get("doi"),
        pmid=pmid,
        abstract="\n\n".join(
            "{}: {}".format(label, body) if label != "ABSTRACT" else body
            for label, body in sections.items()
        )
        or None,
        abstract_sections=sections,
        journal=article.findtext(".//Journal/Title"),
        publication_date=_publication_date(article),
        publication_year=int(_publication_date(article)[:4])
        if _publication_date(article)
        else None,
        authors=_authors(article),
        publication_types=[
            text for text in (p.text for p in article.findall(".//PublicationType")) if text
        ],
        registered_trial_ids=declared_ncts,
        provenance=[
            Provenance(
                source="pubmed",
                source_id=pmid or "",
                url="https://pubmed.ncbi.nlm.nih.gov/{}/".format(pmid or ""),
            )
        ],
    )


def get_papers_by_pmid(pmids: List[str]) -> List[Paper]:
    """Fetch several PubMed records in one call (E-utilities allows batching)."""
    pmids = [str(p).strip() for p in pmids if str(p).strip()]
    if not pmids:
        return []
    xml = get_text(
        "{}/efetch.fcgi".format(EUTILS),
        {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"},
    )
    root = ET.fromstring(xml)
    papers = []
    for citation in root.findall(".//PubmedArticle"):
        try:
            papers.append(parse_pubmed_article(citation))
        except SourceError:
            continue
    return papers


def get_paper_by_pmid(pmid: str) -> Optional[Paper]:
    papers = get_papers_by_pmid([pmid])
    return papers[0] if papers else None


def search_papers(query: str, limit: int = 10) -> List[Paper]:
    """Search PubMed and return normalized records for the top hits."""
    payload = get_text(
        "{}/esearch.fcgi".format(EUTILS),
        {"db": "pubmed", "term": query, "retmax": limit, "retmode": "json"},
    )
    import json

    ids = json.loads(payload).get("esearchresult", {}).get("idlist", [])
    return get_papers_by_pmid(ids)
