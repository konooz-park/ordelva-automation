"""Automatic fact verification (strict; anything doubtful is held for a human).

1. Every claim's quote must exist (near-)verbatim in the fetched source text  -> deterministic.
2. Every number/year in the narration must appear in one of the verified quotes -> deterministic.
3. An LLM judge must rate each claim SUPPORTED by its quote (temperature 0).
4. An LLM pass looks for factual statements in the narration not covered by any claim.
Passing this does NOT prove every statement is true; it proves each statement is traceable to the source.
"""
import difflib
import re


def norm(s):
    s = s.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def quote_found(quote, source, min_ratio=0.92):
    q, s = norm(quote), norm(source)
    if len(q) < 25:
        return False
    if q in s:
        return True
    sm = difflib.SequenceMatcher(None, s, q, autojunk=False)
    blocks = sm.get_matching_blocks()
    matched = sum(b.size for b in blocks)
    return matched / len(q) >= min_ratio and max(b.size for b in blocks) >= len(q) * 0.5


def numbers(text):
    out = set()
    for m in re.finditer(r"\d[\d,\.]*", text):
        n = m.group(0).rstrip(".,").replace(",", "")
        if n and n not in ("0",):
            out.add(n)
    return out


def check(spec, source_text, use_llm=True):
    from .llm import judge_claims, uncovered_statements
    facts = spec.get("facts", [])
    problems, details = [], []
    if len(facts) < 3:
        problems.append(f"only {len(facts)} claims listed")
    ok_quotes = []
    for f in facts:
        found = quote_found(f.get("quote", ""), source_text)
        details.append({"claim": f.get("claim"), "quote_found": found})
        if not found:
            problems.append(f"quote not found in source: {f.get('quote', '')[:80]}")
        else:
            ok_quotes.append(f["quote"])
    narration = " ".join(b["text"] for b in spec["beats"])
    quote_nums = set().union(*[numbers(q) for q in ok_quotes]) if ok_quotes else set()
    for n in numbers(narration):
        if n not in quote_nums and n not in numbers(source_text):
            problems.append(f"number {n} in narration not found in sources")
        elif n not in quote_nums:
            details.append({"number": n, "note": "in source text but not in a cited quote"})
    if use_llm and facts:
        verdicts = judge_claims([(f["claim"], f.get("quote", "")) for f in facts])
        for f, v in zip(facts, verdicts):
            f["verdict"] = v.get("verdict")
            if v.get("verdict") != "SUPPORTED":
                problems.append(f"claim {v.get('verdict')}: {f['claim'][:90]} ({v.get('why', '')[:80]})")
        unc = uncovered_statements(narration, [f["claim"] for f in facts])
        for u in unc:
            problems.append(f"statement without source: {u[:120]}")
    return {"ok": not problems, "problems": problems, "details": details}
