#!/usr/bin/env python3
"""Fetch publications from OpenAlex, Semantic Scholar and DBLP, merge them with
hand-curated entries, and write _data/publications.yml.

The generated file is machine-owned: do not edit it by hand. Curated additions,
corrections and PDF links live in _data/publications_manual.yml, which this
script reads but never writes.

Usage:
    python3 scripts/fetch_publications.py [--dry-run]
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "_data"
MANUAL_FILE = DATA / "publications_manual.yml"
OUTPUT_FILE = DATA / "publications.yml"

# --- identity -----------------------------------------------------------------
ORCID = "0000-0002-8289-388X"
SEMANTIC_SCHOLAR_IDS = ["3084761", "2295375069"]
DBLP_PID = "136/8659"
CONTACT_EMAIL = "afriannotate@gmail.com"

USER_AGENT = f"seyyaw.github.io publication sync (mailto:{CONTACT_EMAIL})"

# Order matters: the first pattern that matches wins.
WORKSHOP_HINTS = ("workshop", "semeval", "winlp", "africanlp", "shared task")
PREPRINT_HINTS = ("arxiv", "corr", "preprint", "openreview")


def get_json(url, tries=3, pause=2.0):
    """GET a URL and parse JSON, tolerating transient failures."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == tries - 1:
                print(f"  ! giving up on {url}: {exc}", file=sys.stderr)
                return None
            time.sleep(pause * (attempt + 1))
    return None


def get_text(url, tries=3, pause=2.0):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == tries - 1:
                print(f"  ! giving up on {url}: {exc}", file=sys.stderr)
                return None
            time.sleep(pause * (attempt + 1))
    return None


def norm_title(title):
    """Normalised title used as the deduplication key."""
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def clean_doi(doi):
    if not doi:
        return None
    doi = doi.strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    return doi or None


def classify(venue, work_type, doi):
    """Map a heterogeneous source type onto our own small vocabulary."""
    v = (venue or "").lower()
    t = (work_type or "").lower()

    if "thesis" in t or "dissertation" in t:
        return "thesis"
    if "book-chapter" in t or "chapter" in t:
        return "book-chapter"
    if any(h in v for h in PREPRINT_HINTS) and not doi:
        return "preprint"
    if t in ("preprint", "posted-content"):
        return "preprint"
    if any(h in v for h in WORKSHOP_HINTS):
        return "workshop"
    if t in ("article", "journal-article", "review"):
        return "journal"
    if t in ("conference-paper", "proceedings-article", "inproceedings"):
        return "conference"
    # Fall back to the venue string when the source type is vague ("other").
    if any(h in v for h in ("proceedings", "conference", "meeting", "symposium")):
        return "conference"
    if any(h in v for h in ("journal", "transactions")):
        return "journal"
    return "other"


AUTHOR_SURNAME = "yimam"


def has_author(authors):
    """True when AUTHOR_SURNAME appears in the author list.

    Filters metadata artefacts (indexes, tables of contents, other authors'
    publication lists) that appear on the Semantic Scholar profile.
    """
    return any(AUTHOR_SURNAME in (a or "").lower() for a in (authors or []))


def looks_garbled(title):
    """Detect broken PDF text extraction, e.g. 'A FRI S ENTI : A B ENCHMARK'."""
    tokens = (title or "").split()
    if len(tokens) < 4:
        return False
    stubs = sum(1 for tok in tokens if len(tok) <= 2 and tok.isupper())
    return stubs >= max(3, len(tokens) // 4)


PREPRINT_VENUES = ("corr", "arxiv", "arxiv.org", "openreview", "ssrn",
                   "social science research network", "zenodo", "biorxiv", "medrxiv")

# Institutional repositories host a copy; they are never the publication venue.
REPOSITORY_HINTS = ("repository", "tubilio", "hildok", "eprint", "institutional",
                    "publikationsserver", "edoc", "hal (", "communication scientifique",
                    "researchgate", "semantic scholar")

# ACL Anthology venue codes that are full conferences; anything else in the
# Anthology is a workshop or co-located event.
ANTHOLOGY_MAIN = {
    "acl", "emnlp", "naacl", "eacl", "coling", "lrec", "lrec-coling", "tacl",
    "cl", "aacl", "ijcnlp", "conll", "findings", "anthology",
}
# Old-style Anthology ids (P16-1234): first letter encodes the venue.
ANTHOLOGY_LETTER = {
    "p": "conference", "d": "conference", "n": "conference", "e": "conference",
    "c": "conference", "l": "conference", "q": "journal", "j": "journal",
    "w": "workshop", "s": "workshop", "k": "conference",
}


def is_preprint_venue(venue):
    v = (venue or "").strip().lower()
    if not v:
        return False
    return any(v == h or h in v for h in PREPRINT_VENUES)


def anthology_kind(doi):
    """Classify an ACL Anthology DOI as conference / workshop / journal."""
    m = re.match(r"10\.18653/v1/(.+)$", doi or "")
    if not m:
        return None
    ident = m.group(1).lower()
    modern = re.match(r"(\d{4})\.([a-z0-9\-]+?)-", ident)
    if modern:
        code = modern.group(2)
        if code.startswith("findings"):
            return "conference"
        return "conference" if code in ANTHOLOGY_MAIN else "workshop"
    old = re.match(r"([a-z])\d{2}-", ident)
    if old:
        return ANTHOLOGY_LETTER.get(old.group(1), "conference")
    return None


def derive_type(rec):
    """Re-derive the publication type once every source has been merged.

    Source-reported types are unreliable (OpenAlex calls an arXiv posting an
    "article", which classify() then reads as a journal paper), so the final
    word goes to the DOI and the venue.
    """
    current = rec.get("type")
    # A type set by hand in publications_manual.yml is authoritative.
    if rec.get("_type_locked") or current in ("thesis", "poster", "book-chapter"):
        return current

    doi = (rec.get("doi") or "").lower()
    venue = rec.get("venue")

    kind = anthology_kind(doi)
    if kind:
        return kind

    # An arXiv DOI only means the paper is ON arXiv. HateXplain is on arXiv and
    # published at AAAI; "How Hateful are Movies?" is on arXiv and published at
    # KONVENS. So a real venue always wins over the arXiv DOI, and a paper is
    # only a preprint when nothing better than a preprint server is known.
    has_real_venue = bool(venue) and not is_preprint_venue(venue) \
        and not any(h in (venue or "").lower() for h in REPOSITORY_HINTS)
    if not has_real_venue and (doi.startswith("10.48550/arxiv")
                               or is_preprint_venue(venue)
                               or rec.get("arxiv")):
        return "preprint"

    v = (venue or "").lower()
    if not v or any(h in v for h in REPOSITORY_HINTS):
        # Nothing usable to go on: an unplaced record is not a journal article.
        return "preprint" if rec.get("arxiv") else "other"
    if "thesis" in v or "dissertation" in v:
        return "thesis"
    if any(h in v for h in WORKSHOP_HINTS):
        return "workshop"
    # Unambiguous journal words first -- "Transactions of the ACL" is a journal
    # even though it contains "acl".
    if any(h in v for h in ("journal", "transactions", "trans.")):
        return "journal"
    # Then anything that names an event. This has to come before the weaker
    # journal hints below, or "IEEE Conference on Healthcare Informatics" and
    # "Conference on ICT for Development" would be read as journals.
    if any(h in v for h in ("proceedings", "conference", "meeting", "symposium",
                            "workshop", "acl", "coling", "lrec", "gscl", "konvens",
                            "ranlp", "ijcnlp", "aaai", "ieee", "naacl", "eacl",
                            "society for computational linguistics", "clarin",
                            "eurovis", "sepln", "sigul")):
        return "workshop" if "workshop" in v else "conference"
    # Weak journal hints: only reached when nothing above matched.
    if any(h in v for h in ("informatics", "development", "future internet", "i-com")):
        return "journal"
    return current if current not in (None, "other") else "other"


def anthology_url(doi):
    """ACL Anthology DOIs (10.18653/v1/<id>) map directly onto anthology pages.

    DOIs are lower-cased on ingest, but pre-2020 Anthology ids are upper-case
    (D18-2014, not d18-2014) and the lower-case form 404s, so restore it.
    """
    if not doi:
        return None
    m = re.match(r"10\.18653/v1/(.+)$", doi)
    if not m:
        return None
    ident = m.group(1)
    old = re.match(r"^([a-z])(\d{2}-\d+)$", ident)
    if old:
        ident = old.group(1).upper() + old.group(2)
    return f"https://aclanthology.org/{ident}/"


# --- sources ------------------------------------------------------------------

def from_openalex():
    """OpenAlex, filtered by ORCID so we never pick up a namesake."""
    out, cursor = [], "*"
    while cursor:
        url = (
            "https://api.openalex.org/works?"
            + urllib.parse.urlencode(
                {
                    "filter": f"author.orcid:{ORCID}",
                    "per-page": 200,
                    "cursor": cursor,
                    "mailto": CONTACT_EMAIL,
                }
            )
        )
        data = get_json(url)
        if not data:
            break
        for w in data.get("results", []):
            src = (w.get("primary_location") or {}).get("source") or {}
            venue = src.get("display_name")
            doi = clean_doi(w.get("doi"))
            authors = [
                (a.get("author") or {}).get("display_name")
                for a in w.get("authorships", [])
            ]
            loc = w.get("best_oa_location") or w.get("primary_location") or {}
            out.append(
                {
                    "title": (w.get("title") or "").strip(),
                    "authors": [a for a in authors if a],
                    "year": w.get("publication_year"),
                    "venue": venue,
                    "type": classify(venue, w.get("type"), doi),
                    "doi": doi,
                    "url": w.get("id"),
                    "pdf": loc.get("pdf_url"),
                    "source": "openalex",
                }
            )
        cursor = (data.get("meta") or {}).get("next_cursor")
        time.sleep(0.3)
    print(f"  OpenAlex: {len(out)} works")
    return out


def from_semantic_scholar():
    out = []
    fields = "title,year,venue,externalIds,publicationTypes,authors,openAccessPdf,url"
    for author_id in SEMANTIC_SCHOLAR_IDS:
        offset = 0
        while True:
            url = (
                f"https://api.semanticscholar.org/graph/v1/author/{author_id}/papers?"
                + urllib.parse.urlencode(
                    {"fields": fields, "limit": 100, "offset": offset}
                )
            )
            data = get_json(url)
            if not data or not data.get("data"):
                break
            for p in data["data"]:
                ext = p.get("externalIds") or {}
                doi = clean_doi(ext.get("DOI"))
                types = p.get("publicationTypes") or []
                venue = p.get("venue")
                out.append(
                    {
                        "title": (p.get("title") or "").strip(),
                        "authors": [a.get("name") for a in (p.get("authors") or [])],
                        "year": p.get("year"),
                        "venue": venue,
                        "type": classify(venue, types[0] if types else None, doi),
                        "doi": doi,
                        "url": p.get("url"),
                        "pdf": (p.get("openAccessPdf") or {}).get("url"),
                        "arxiv": ext.get("ArXiv"),
                        "source": "semanticscholar",
                    }
                )
            if data.get("next") is None:
                break
            offset = data["next"]
            time.sleep(0.5)
        time.sleep(0.5)
    print(f"  Semantic Scholar: {len(out)} works")
    return out


DBLP_TYPE = {
    "article": "journal",
    "inproceedings": "conference",
    "incollection": "book-chapter",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
}


def from_dblp():
    """DBLP is the most reliable source for ACL/CS venue names."""
    raw = get_text(f"https://dblp.org/pid/{DBLP_PID}.xml")
    if not raw:
        print("  DBLP: unavailable")
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        print(f"  ! DBLP parse error: {exc}", file=sys.stderr)
        return []

    out = []
    for rec in root.findall("./r/*"):
        tag = rec.tag
        title = "".join(rec.find("title").itertext()).strip() if rec.find("title") is not None else ""
        title = title.rstrip(".")
        venue = None
        for key in ("journal", "booktitle", "school"):
            node = rec.find(key)
            if node is not None and node.text:
                venue = node.text
                break
        year_node = rec.find("year")
        doi = None
        url = None
        for ee in rec.findall("ee"):
            if ee.text and "doi.org" in ee.text:
                doi = clean_doi(ee.text)
            elif ee.text and not url:
                url = ee.text
        if tag in ("phdthesis", "mastersthesis") and venue:
            kind = "Ph.D. Thesis" if tag == "phdthesis" else "M.Sc. Thesis"
            venue = f"{kind}, {venue}"
        is_informal = rec.get("publtype") == "informal"
        wtype = "preprint" if is_informal else DBLP_TYPE.get(tag, "other")
        if wtype not in ("preprint", "thesis"):
            wtype = classify(venue, tag, doi)
        out.append(
            {
                "title": title,
                "authors": [a.text for a in rec.findall("author") if a.text],
                "year": int(year_node.text) if year_node is not None and year_node.text else None,
                "venue": venue,
                "type": wtype,
                "doi": doi,
                "url": url,
                "source": "dblp",
            }
        )
    print(f"  DBLP: {len(out)} works")
    return out


# --- merge --------------------------------------------------------------------

# Sources listed later win when filling a field that is still empty.
SOURCE_RANK = {"dblp": 3, "openalex": 2, "semanticscholar": 1}


def title_prefix(title, n=58):
    """Prefix key that survives a source appending the venue to the title."""
    t = norm_title(title)
    return t[:n]


def merge(records):
    """Collapse records describing the same paper, preferring richer sources."""
    by_key = {}
    doi_to_key = {}
    prefix_to_key = {}

    for rec in records:
        if not rec.get("title"):
            continue
        tkey = norm_title(rec["title"])
        pkey = title_prefix(rec["title"])
        doi = rec.get("doi")
        key = doi_to_key.get(doi) if doi else None
        if key is None:
            # Exact title, else a shared long prefix -- one source likes to glue
            # the venue onto the end of the title.
            key = tkey if tkey in by_key else prefix_to_key.get(pkey, tkey)
        if doi:
            doi_to_key[doi] = key
        prefix_to_key.setdefault(pkey, key)

        existing = by_key.get(key)
        if existing is None:
            rec = dict(rec)
            rec["sources"] = [rec.pop("source")]
            by_key[key] = rec
            continue

        src = rec.pop("source")
        if src not in existing["sources"]:
            existing["sources"].append(src)
        better = SOURCE_RANK.get(src, 0) >= max(
            SOURCE_RANK.get(s, 0) for s in existing["sources"]
        )
        for field in ("title", "venue", "year", "doi", "url", "pdf", "arxiv", "authors"):
            new = rec.get(field)
            if not new:
                continue
            if not existing.get(field):
                existing[field] = new
            elif field == "venue":
                # DBLP has the cleanest venue strings, but it also indexes the
                # arXiv copy of most papers -- never let "CoRR" bury the real
                # publication venue.
                if is_preprint_venue(existing.get("venue")) and not is_preprint_venue(new):
                    existing["venue"] = new
                elif better and not is_preprint_venue(new):
                    existing["venue"] = new
            elif field in ("authors", "title") and better:
                existing[field] = new
        if rec.get("type") and existing.get("type") in (None, "other"):
            existing["type"] = rec["type"]

    return list(by_key.values())


def consolidate(records):
    """Second dedupe pass over already-merged records.

    Sources sometimes disagree on a title ("SemEval Task 1" vs "SemEval-2024
    Task 1"), so two groups form; the richer source then rewrites both titles to
    the same string. Only after merging can those be seen as one paper.
    """
    out, by_key = [], {}
    for rec in records:
        keys = [norm_title(rec.get("title")), title_prefix(rec.get("title"))]
        hit = None
        for k in keys:
            if k and k in by_key:
                hit = by_key[k]
                break
        if hit is None:
            out.append(rec)
            for k in keys:
                if k:
                    by_key[k] = rec
            continue

        # Keep the version of record: a real DOI beats an arXiv one.
        hit_doi, new_doi = hit.get("doi") or "", rec.get("doi") or ""
        if new_doi and (not hit_doi or
                        (hit_doi.startswith("10.48550") and not new_doi.startswith("10.48550"))):
            hit["doi"] = new_doi
            if rec.get("type"):
                hit["type"] = rec["type"]
        for field in ("venue", "year", "pdf", "arxiv", "authors", "award", "url"):
            if not hit.get(field) and rec.get(field):
                hit[field] = rec[field]
        hit["sources"] = sorted(set((hit.get("sources") or []) + (rec.get("sources") or [])))
    return out


def apply_manual(records, manual):
    """Layer curated extras, per-paper overrides and exclusions on top."""
    overrides = manual.get("overrides") or []
    extras = manual.get("extra") or []
    # Excludes match on a normalised substring, so a distinctive prefix is
    # enough -- these titles are long and sources truncate them differently.
    exclude = [norm_title(t) for t in (manual.get("exclude") or []) if norm_title(t)]

    def excluded(rec):
        t = norm_title(rec.get("title"))
        for pattern in exclude:
            # One-directional only: the pattern must be contained in the title.
            # Matching the other way round would drop a real paper whose title
            # is a substring of a longer artefact title.
            if pattern and pattern in t:
                print(f"  - excluded (manual): {rec.get('title', '')[:70]}")
                return True
        return False

    records = [r for r in records if not excluded(r)]

    by_doi = {r["doi"]: r for r in records if r.get("doi")}
    by_title = {norm_title(r.get("title")): r for r in records}
    # Sources differ on punctuation and line breaks inside titles, so also key
    # on a long prefix.
    by_prefix_ov = {}
    for r in records:
        by_prefix_ov.setdefault(title_prefix(r.get("title")), r)

    for ov in overrides:
        target = None
        if ov.get("doi"):
            target = by_doi.get(clean_doi(ov["doi"]))
        if target is None and ov.get("title"):
            target = (by_title.get(norm_title(ov["title"]))
                      or by_prefix_ov.get(title_prefix(ov["title"])))
        if target is None:
            print(f"  ! override matched nothing: {ov.get('title') or ov.get('doi')}")
            continue
        for k, v in ov.items():
            if k not in ("doi", "title") or not target.get(k):
                target[k] = v
        if "type" in ov:
            target["_type_locked"] = True

    # Extras must not duplicate something the indexes already returned: match on
    # title (exact, then long prefix) and enrich that record instead.
    by_prefix = {}
    for r in records:
        by_prefix.setdefault(title_prefix(r.get("title")), r)

    for extra in extras:
        rec = dict(extra)
        target = (by_title.get(norm_title(rec.get("title")))
                  or by_prefix.get(title_prefix(rec.get("title"))))
        if target is not None:
            for k, v in rec.items():
                if k != "sources":
                    target[k] = v
            if "type" in rec:
                target["_type_locked"] = True
            target.setdefault("sources", []).append("manual")
            print(f"  merged curated entry into fetched record: {rec.get('title','')[:60]}")
            continue
        rec.setdefault("sources", ["manual"])
        if "type" in rec:
            rec["_type_locked"] = True
        records.append(rec)
        by_title[norm_title(rec.get("title"))] = rec
        by_prefix.setdefault(title_prefix(rec.get("title")), rec)

    return records


def sort_key(rec):
    return (-(rec.get("year") or 0), (rec.get("title") or "").lower())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="print, do not write")
    args = parser.parse_args()

    print("Fetching publications...")
    records = []
    records += from_openalex()
    records += from_semantic_scholar()
    records += from_dblp()

    merged = consolidate(merge(records))
    print(f"  merged into {len(merged)} unique publications")

    # Quality gate. Anything dropped here is reported, never silently removed,
    # so a wrongly-filtered paper can be re-added via publications_manual.yml.
    kept, dropped = [], []
    for rec in merged:
        if not has_author(rec.get("authors")):
            dropped.append(("no matching author", rec))
        elif looks_garbled(rec.get("title")):
            dropped.append(("garbled title", rec))
        else:
            kept.append(rec)
    for reason, rec in dropped:
        print(f"  - dropped ({reason}): {rec.get('title', '')[:70]}")
    print(f"  {len(kept)} publications after filtering")
    merged = kept

    manual = {}
    if MANUAL_FILE.exists():
        manual = yaml.safe_load(MANUAL_FILE.read_text(encoding="utf-8")) or {}
    merged = apply_manual(merged, manual)

    for rec in merged:
        rec["type"] = derive_type(rec)
        if not rec.get("anthology"):
            link = anthology_url(rec.get("doi"))
            if link:
                rec["anthology"] = link
        if rec.get("doi") and not rec.get("doi_url"):
            rec["doi_url"] = f"https://doi.org/{rec['doi']}"
        rec.pop("_type_locked", None)
        rec["sources"] = sorted(set(rec.get("sources") or []))
        # Drop empties so the YAML stays readable.
        for k in [k for k, v in rec.items() if v in (None, "", [])]:
            del rec[k]

    merged.sort(key=sort_key)

    payload = (
        "# AUTO-GENERATED by scripts/fetch_publications.py -- do not edit by hand.\n"
        "# Curated additions and corrections belong in _data/publications_manual.yml\n"
        + yaml.safe_dump(merged, allow_unicode=True, sort_keys=False, width=100)
    )

    if args.dry_run:
        print(payload[:2000])
        print(f"\n[dry-run] {len(merged)} publications, not written")
        return

    OUTPUT_FILE.write_text(payload, encoding="utf-8")
    print(f"Wrote {len(merged)} publications to {OUTPUT_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
