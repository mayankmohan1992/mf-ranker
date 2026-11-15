"""SEBI / AMFI scheme classification.

AMFI tags every scheme with a section like:

    Open Ended Schemes(Equity Schemes - Large Cap Fund)
    Open Ended Schemes(Debt Scheme - Liquid Fund)
    Open Ended Schemes(Income/Debt Oriented Schemes - Corporate Bond Fund)

The same SEBI category shows up under several spellings ("Equity Scheme" vs
"Equity Schemes", "Liquid Fund" vs "Long Term Fund", ...) because AMFI keeps
legacy headers alive alongside the post-2026 categorisation. This module folds
those into one canonical category per SEBI bucket, and splits the very broad
"Index Fund" / "ETF" buckets by the benchmark in the scheme name, so a Nifty 50
index fund is ranked against other Nifty 50 index funds instead of against a
silver ETF.
"""
from __future__ import annotations

import re

# --- canonical taxonomy -----------------------------------------------------
# (canonical name, asset class, display order)
CANON = {
    # Equity
    "Large Cap Fund": ("Equity", 10),
    "Large & Mid Cap Fund": ("Equity", 11),
    "Mid Cap Fund": ("Equity", 12),
    "Small Cap Fund": ("Equity", 13),
    "Multi Cap Fund": ("Equity", 14),
    "Flexi Cap Fund": ("Equity", 15),
    "Focused Fund": ("Equity", 16),
    "ELSS": ("Equity", 17),
    "Value Fund": ("Equity", 18),
    "Contra Fund": ("Equity", 19),
    "Dividend Yield Fund": ("Equity", 20),
    "Sectoral / Thematic Fund": ("Equity", 21),
    # Debt
    "Overnight Fund": ("Debt", 30),
    "Liquid Fund": ("Debt", 31),
    "Ultra Short Duration Fund": ("Debt", 32),
    "Low Duration Fund": ("Debt", 33),
    "Money Market Fund": ("Debt", 34),
    "Short Duration Fund": ("Debt", 35),
    "Medium Duration Fund": ("Debt", 36),
    "Medium to Long Duration Fund": ("Debt", 37),
    "Long Duration Fund": ("Debt", 38),
    "Dynamic Bond Fund": ("Debt", 39),
    "Corporate Bond Fund": ("Debt", 40),
    "Credit Risk Fund": ("Debt", 41),
    "Banking & PSU Fund": ("Debt", 42),
    "Gilt Fund": ("Debt", 43),
    "Floater Fund": ("Debt", 44),
    "Constant Maturity Gilt Fund": ("Debt", 45),
    "Debt Sectoral Fund": ("Debt", 46),
    "Fixed Term Plan": ("Debt", 47),
    # Hybrid
    "Conservative Hybrid Fund": ("Hybrid", 50),
    "Balanced Hybrid Fund": ("Hybrid", 51),
    "Aggressive Hybrid Fund": ("Hybrid", 52),
    "Dynamic Asset Allocation / Balanced Advantage": ("Hybrid", 53),
    "Multi Asset Allocation Fund": ("Hybrid", 54),
    "Arbitrage Fund": ("Hybrid", 55),
    "Equity Savings Fund": ("Hybrid", 56),
    # Other
    "Index Fund": ("Other", 60),
    "ETF": ("Other", 61),
    "Fund of Funds": ("Other", 62),
    "Children's Fund": ("Other", 63),
    "Retirement Fund": ("Other", 64),
    "Life Cycle Fund": ("Other", 65),
    "Other / Unclassified": ("Other", 99),
}

# specific AMFI label (lowercased, punctuation-normalised) -> canonical name
ALIASES = {
    # equity
    "large cap fund": "Large Cap Fund",
    "large and mid cap fund": "Large & Mid Cap Fund",
    "mid cap fund": "Mid Cap Fund",
    "small cap fund": "Small Cap Fund",
    "multi cap fund": "Multi Cap Fund",
    "flexi cap fund": "Flexi Cap Fund",
    "focused fund": "Focused Fund",
    "elss": "ELSS",
    "elss tax saver": "ELSS",
    "elss tax saver fund": "ELSS",
    "elss- tax saver fund": "ELSS",
    "value fund": "Value Fund",
    "contra fund": "Contra Fund",
    "dividend yield fund": "Dividend Yield Fund",
    "sectoral/ thematic": "Sectoral / Thematic Fund",
    "sectoral / thematic": "Sectoral / Thematic Fund",
    "sectoral fund": "Sectoral / Thematic Fund",
    "thematic fund": "Sectoral / Thematic Fund",
    # debt
    "overnight fund": "Overnight Fund",
    "liquid fund": "Liquid Fund",
    "ultra short duration fund": "Ultra Short Duration Fund",
    "ultra short term fund": "Ultra Short Duration Fund",
    "ultra short to short term fund": "Ultra Short Duration Fund",
    "low duration fund": "Low Duration Fund",
    "money market fund": "Money Market Fund",
    "short duration fund": "Short Duration Fund",
    "short term fund": "Short Duration Fund",
    "medium duration fund": "Medium Duration Fund",
    "medium term fund": "Medium Duration Fund",
    "medium to long duration fund": "Medium to Long Duration Fund",
    "medium to long term fund": "Medium to Long Duration Fund",
    "long duration fund": "Long Duration Fund",
    "long term fund": "Long Duration Fund",
    "dynamic bond": "Dynamic Bond Fund",
    "dynamic bond fund": "Dynamic Bond Fund",
    "dynamic term fund": "Dynamic Bond Fund",
    "corporate bond fund": "Corporate Bond Fund",
    "credit risk fund": "Credit Risk Fund",
    "banking and psu fund": "Banking & PSU Fund",
    "banking and psu debt fund": "Banking & PSU Fund",
    "gilt fund": "Gilt Fund",
    "gilt": "Gilt Fund",
    "floating interest rates fund": "Floater Fund",
    "floater fund": "Floater Fund",
    "10-year constant maturity gilt fund": "Constant Maturity Gilt Fund",
    "fixed term plan": "Fixed Term Plan",
    "other debt scheme": "Debt Sectoral Fund",
    # hybrid
    "conservative hybrid fund": "Conservative Hybrid Fund",
    "balanced hybrid fund": "Balanced Hybrid Fund",
    "aggressive hybrid fund": "Aggressive Hybrid Fund",
    "dynamic asset allocation or balanced advantage": "Dynamic Asset Allocation / Balanced Advantage",
    "balanced advantage fund/ dynamic asset allocation": "Dynamic Asset Allocation / Balanced Advantage",
    "dynamic asset allocation": "Dynamic Asset Allocation / Balanced Advantage",
    "balanced advantage fund": "Dynamic Asset Allocation / Balanced Advantage",
    "multi asset allocation": "Multi Asset Allocation Fund",
    "multi asset allocation fund": "Multi Asset Allocation Fund",
    "arbitrage fund": "Arbitrage Fund",
    "equity savings": "Equity Savings Fund",
    "equity savings fund": "Equity Savings Fund",
    # other
    "index funds": "Index Fund",
    "index funds debt funds": "Index Fund",
    "index funds equity funds": "Index Fund",
    "index funds hybrid fund": "Index Fund",
    "debt funds": "Index Fund",
    "equity funds": "Index Fund",
    "hybrid fund": "Index Fund",
    "index fund": "Index Fund",
    "debt etf": "ETF",
    "equity etf": "ETF",
    "gold etf": "ETF",
    "silver etf": "ETF",
    "hybrid etf": "ETF",
    "other etf": "ETF",
    "other etfs": "ETF",
    "etfs investing overseas": "ETF",
    "fof domestic": "Fund of Funds",
    "fof overseas": "Fund of Funds",
    "fund of funds scheme domestic": "Fund of Funds",
    "fund of funds investing overseas": "Fund of Funds",
    "children's fund": "Children's Fund",
    "childrens' fund": "Children's Fund",
    "children’s fund": "Children's Fund",
    "retirement fund": "Retirement Fund",
    "life cycle fund": "Life Cycle Fund",
    # legacy bare headers - the whole section, no sub-label
    "income": "",
    "growth": "",
    "elss ": "",
}


def _norm(text: str) -> str:
    t = text.strip().lower()
    t = t.replace("**", " ")
    t = t.replace("&", "and")
    t = t.replace("’", "'")
    t = re.sub(r"\([^)]*\)", lambda m: " " + m.group(0)[1:-1] + " ", t)
    t = t.replace("(", " ").replace(")", " ")
    t = re.sub(r"\s+", " ", t)
    return t.strip(" .-")


def _specific(label: str) -> str:
    """'Equity Schemes - Large Cap Fund' -> 'Large Cap Fund'; 'Income' -> 'Income'."""
    n = _norm(label)
    if " - " in n:
        n = n.split(" - ")[-1]
    return n.strip()


def canonical_category(section_inner: str) -> str:
    """Map an AMFI section label to a canonical SEBI category."""
    specific = _specific(section_inner or "")
    if not specific:
        return "Other / Unclassified"
    if specific in ALIASES:
        return ALIASES[specific] or "Other / Unclassified"
    for alias, canon in ALIASES.items():
        if alias.strip() and specific.startswith(alias):
            return canon
    # life cycle funds carry their maturity year in the name
    if specific.startswith("life cycle"):
        return "Life Cycle Fund"
    # last resort: title-case the specific label if it is already a known bucket
    for canon in CANON:
        if _norm(canon) == specific:
            return canon
    return "Other / Unclassified"


def asset_class(canon: str) -> str:
    return CANON.get(canon, ("Other", 99))[0]


def order_of(canon: str) -> int:
    return CANON.get(canon, ("Other", 99))[1]


# --- benchmark grouping for Index / ETF ------------------------------------
BENCHMARKS = [
    ("nifty next 50", "Nifty Next 50"),
    ("nifty 500", "Nifty 500"),
    ("nifty midcap 150", "Nifty Midcap 150"),
    ("nifty smallcap 250", "Nifty Smallcap 250"),
    ("nifty midcap 100", "Nifty Midcap 100"),
    ("nifty smallcap 100", "Nifty Smallcap 100"),
    ("nifty total market", "Nifty Total Market"),
    ("nifty 100", "Nifty 100"),
    ("nifty 50", "Nifty 50"),
    ("nifty bank", "Nifty Bank"),
    ("nifty psu bank", "Nifty PSU Bank"),
    ("nifty private bank", "Nifty Private Bank"),
    ("nifty it", "Nifty IT"),
    ("nifty pharma", "Nifty Pharma"),
    ("nifty healthcare", "Nifty Healthcare"),
    ("nifty auto", "Nifty Auto"),
    ("nifty fmcg", "Nifty FMCG"),
    ("nifty metal", "Nifty Metal"),
    ("nifty energy", "Nifty Energy"),
    ("nifty infrastructure", "Nifty Infrastructure"),
    ("nifty cpse", "Nifty CPSE"),
    ("nifty pse", "Nifty PSE"),
    ("nifty defence", "Nifty India Defence"),
    ("nifty ev", "Nifty EV"),
    ("nifty india consumption", "Nifty India Consumption"),
    ("sensex", "Sensex"),
    ("bse 500", "BSE 500"),
    ("nasdaq 100", "Nasdaq 100"),
    ("s&p 500", "S&P 500"),
    ("hang seng", "Hang Seng"),
    ("gold", "Gold"),
    ("silver", "Silver"),
    ("sdl", "SDL"),
    ("g-sec", "G-Sec"),
    ("gsec", "G-Sec"),
    ("10 year", "G-Sec 10Y"),
    ("target maturity", "Target Maturity"),
    ("liquid", "Liquid"),
    ("overnight", "Overnight"),
    ("crisil", "CRISIL Composite"),
]


IDX_RE = re.compile(
    r"\b(nifty|bse|crisil|s&p|nasdaq|msci|hang seng|sensex)\b"
    r"([a-z0-9 &.\-]{0,45}?)"
    r"(?=\s*(?:index|etf|fund|scheme|growth|direct|plan|$))"
)


_ACRONYMS = {
    "Bse": "BSE", "Psu": "PSU", "Sdl": "SDL", "Etf": "ETF", "It": "IT",
    "Esg": "ESG", "Mnc": "MNC", "Cpse": "CPSE", "Nse": "NSE", "Bfsi": "BFSI",
    "Gsec": "G-Sec", "Ipo": "IPO", "Sme": "SME", "Reit": "REIT", "Invits": "InvITs",
    "Nfo": "NFO", "Q50": "Q50", "Alpha": "Alpha", "Mcap": "MCap", "Aaa": "AAA",
}


def _fix_case(label: str) -> str:
    """Title-casing wrecks acronyms ('Bse', 'Psu'); put them back."""
    return " ".join(_ACRONYMS.get(w, w) for w in label.split(" "))


def benchmark_group(name: str) -> str:
    """Bucket an index fund / ETF by its underlying index so ranks are meaningful.

    Known indices get a clean label; anything else is grouped by the index name
    parsed out of the scheme name (so two "Nifty India X Index Fund" schemes still
    find each other), and a genuinely unique index ends up in a group of one -
    which correctly yields no rank rather than a meaningless one.
    """
    n = _norm(name)
    for needle, label in BENCHMARKS:
        if needle in n:
            return label
    m = IDX_RE.search(n)
    if m:
        words = (m.group(1) + m.group(2)).strip()
        words = re.sub(r"\s+", " ", words).strip(" .-&")
        if len(words) > 3:
            return _fix_case(words.title())
    return "Other Index / ETF"


THEMES = [
    ("pharma", "Pharma / Healthcare"), ("healthcare", "Pharma / Healthcare"),
    ("health", "Pharma / Healthcare"), ("medicare", "Pharma / Healthcare"),
    ("technology", "Technology"), ("digital", "Technology"), ("it fund", "Technology"),
    ("infotech", "Technology"), ("software", "Technology"), ("innovation", "Technology"),
    ("banking", "Banking / Financial Services"), ("bank", "Banking / Financial Services"),
    ("financial services", "Banking / Financial Services"), ("fintech", "Banking / Financial Services"),
    ("psu", "PSU / CPSE"), ("cpse", "PSU / CPSE"),
    ("defence", "Defence"), ("defense", "Defence"),
    ("infrastructure", "Infrastructure"), ("infra", "Infrastructure"),
    ("manufacturing", "Manufacturing"), ("capital market", "Capital Markets"),
    ("consumption", "Consumption"), ("consumer", "Consumption"),
    ("fmcg", "FMCG / Consumption"), ("auto", "Auto"),
    ("energy", "Energy / Power"), ("power", "Energy / Power"), ("oil", "Energy / Power"),
    ("metal", "Metals / Mining"), ("mining", "Metals / Mining"),
    ("realty", "Real Estate"), ("real estate", "Real Estate"),
    ("transport", "Transport / Logistics"), ("logistics", "Transport / Logistics"),
    ("telecom", "Telecom / Media"), ("media", "Telecom / Media"),
    ("esg", "ESG"), ("sustainable", "ESG"),
    ("mnc", "MNC"), ("business cycle", "Business Cycle"),
    ("quant", "Quant / Rule-based"), ("value", "Value"),
    ("small cap", "Small Cap Theme"), ("mid cap", "Mid Cap Theme"),
    ("large cap", "Large Cap Theme"), ("dividend", "Dividend Yield"),
    ("gold", "Gold"), ("silver", "Silver"), ("commodit", "Commodities"),
    ("special opportunities", "Special Situations"), ("opportunit", "Special Situations"),
    ("index", "Index / Passive Theme"), ("rural", "Rural / Agri"), ("agri", "Rural / Agri"),
    ("tourism", "Hospitality / Tourism"), ("hospitality", "Hospitality / Tourism"),
    ("chemical", "Chemicals"), ("textile", "Textiles"),
    ("ev ", "EV / Mobility"), ("electric", "EV / Mobility"), ("mobility", "EV / Mobility"),
    ("housing", "Housing"), ("water", "Water / Environment"), ("environment", "Water / Environment"),
    ("services", "Services"), ("export", "Export / Global"),
]


def theme_group(name: str) -> str:
    n = _norm(name)
    padded = " " + n + " "
    for needle, label in THEMES:
        if (" " + needle) in padded or needle.endswith(" ") and needle in padded:
            return label
    return "Other Thematic"


def rank_group(canon: str, name: str) -> str:
    """Ranking bucket inside a category.

    Index funds / ETFs rank within their benchmark, Sectoral/Thematic funds rank
    within their theme - otherwise a pharma fund would be ranked against a
    defence fund and the number would mean nothing.
    """
    if canon in ("Index Fund", "ETF"):
        return benchmark_group(name)
    if canon == "Sectoral / Thematic Fund":
        return theme_group(name)
    return ""


def slug(text: str) -> str:
    s = _norm(text)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")
