"""RAG Compliance agent: per-check retrieval + LLM reasoning over retrieved clause text, with citation guard."""
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from src import config, llm
from src.agents.checks import Check, checks_for
from src.rag.retriever import Hit, Retriever
from src.schemas import Extraction, ParamStatus

STATUSES = ("Compliant", "Non-Compliant", "Insufficient Data", "Not Applicable")

SYSTEM = """You are an Indian senior structural engineer auditing an RCC drawing against IS 456:2000 and SP 34:1987.
For each check you get the engineer-verified drawing values, values derived by the validator, and code passages
retrieved for that check, each tagged with an id like [S3].
Rules:
- Base every requirement ONLY on the passages given for that check. Quote the governing limit in "requirement".
- "sources" must list the ids of the passages you used. Never cite a passage from another check.
- "clause" = clause / table / figure number exactly as it appears in the cited passage (e.g. "26.4.2.2", "Table 16").
- If the passages do not contain the governing rule, status = "Insufficient Data" and say what is missing.
- If the drawing value is missing, status = "Insufficient Data". If the check does not apply (e.g. raft check on an isolated footing), "Not Applicable".
- Show the arithmetic in "reasoning" when you compare numbers.
Reply JSON: {"results": [{"id": "<check id>", "status": "Compliant|Non-Compliant|Insufficient Data|Not Applicable",
"provided": "<drawing value(s)>", "requirement": "<code requirement>", "clause": "<clause/table>",
"sources": ["S1", ...], "reasoning": "<2-4 sentences>", "recommendation": "<fix or null>"}]}"""


@dataclass
class CheckResult:
    id: str
    title: str
    status: str
    provided: str = ""
    requirement: str = ""
    clause: str = ""
    reasoning: str = ""
    recommendation: Optional[str] = None
    citations: List[Dict[str, object]] = field(default_factory=list)
    grounded: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def _values(check: Check, ex: Extraction) -> Dict[str, str]:
    params = ex.as_dict()
    out = {}
    for key in check.params:
        p = params.get(key)
        if p is None:
            continue
        if p.status == ParamStatus.MISSING or not p.value:
            out[p.label or key] = "NOT PROVIDED"
        else:
            out[p.label or key] = f"{p.value}{' ' + p.unit if p.unit and p.unit not in p.value else ''}"
    return out


def retrieve_for(check: Check, retriever: Retriever, k: int) -> List[Hit]:
    where = {"source": check.sources[0]} if len(check.sources) == 1 else {"source": {"$in": list(check.sources)}}
    hits = retriever.retrieve(check.query, k=k, where=where)
    if not hits:  # e.g. IS456 not ingested yet -> fall back to the whole KB
        hits = retriever.retrieve(check.query, k=k)
    return hits


def _clause_tokens(clause: str) -> List[str]:
    return re.findall(r"\d+(?:\.\d+)*[A-Z]?", clause or "")


def guard(raw: dict, check: Check, hits: Dict[str, Hit]) -> CheckResult:
    """Accept a result only if its citations point at passages retrieved for this check."""
    status = raw.get("status") if raw.get("status") in STATUSES else "Insufficient Data"
    cited = [s.strip("[] ") for s in raw.get("sources", []) or [] if isinstance(s, str)]
    valid = [s for s in cited if s in hits]
    result = CheckResult(
        id=check.id,
        title=check.title,
        status=status,
        provided=str(raw.get("provided") or ""),
        requirement=str(raw.get("requirement") or ""),
        clause=str(raw.get("clause") or ""),
        reasoning=str(raw.get("reasoning") or ""),
        recommendation=raw.get("recommendation") or None,
        citations=[{"id": s, "ref": hits[s].citation, **{k: hits[s].metadata.get(k) for k in ("source", "page", "clause", "label")}} for s in valid],
    )
    if status in ("Compliant", "Non-Compliant"):
        problems = []
        if not valid:
            problems.append("no retrieved passage cited")
        elif cited and len(valid) < len(cited):
            problems.append(f"cited passages not retrieved for this check: {sorted(set(cited) - set(valid))}")
        tokens = _clause_tokens(result.clause)
        if valid and tokens:
            haystack = " ".join(f"{hits[s].metadata.get('clause', '')} {hits[s].metadata.get('label', '')} {hits[s].text}" for s in valid)
            if not any(t in haystack for t in tokens):
                problems.append(f"clause '{result.clause}' does not appear in the cited passages")
        if problems:
            result.grounded = False
            result.status = "Insufficient Data"
            result.reasoning += f" [Citation guard: {'; '.join(problems)}. Verdict withheld.]"
    return result


def _context_block(n: int, check: Check, ex: Extraction, derived: dict, hit_ids: Dict[str, Hit]) -> str:
    passages = "\n".join(f"[{sid}] ({hit.citation})\n{hit.text}" for sid, hit in hit_ids.items())
    return (
        f"### Check {n}: id={check.id} - {check.title}\n"
        f"Drawing values: {json.dumps(_values(check, ex), ensure_ascii=False)}\n"
        f"Derived values: {json.dumps(derived)}\n"
        f"Passages:\n{passages or '(none retrieved)'}\n"
    )


def run(ex: Extraction, derived: dict, retriever: Retriever, k: int = None, batch_size: int = 5,
        user_notes: str = "") -> List[CheckResult]:
    k = k or config.RETRIEVE_K
    checks = checks_for(ex.drawing_type)
    results: List[CheckResult] = []
    sid = 0
    for start in range(0, len(checks), batch_size):
        batch = checks[start : start + batch_size]
        per_check: Dict[str, Dict[str, Hit]] = {}
        blocks = []
        for n, check in enumerate(batch, start + 1):
            hits = {}
            for hit in retrieve_for(check, retriever, k):
                sid += 1
                hits[f"S{sid}"] = hit
            per_check[check.id] = hits
            blocks.append(_context_block(n, check, ex, derived, hits))

        user = (f"Drawing type: {ex.drawing_type.value}\n"
                + (f"Engineer notes: {user_notes}\n" if user_notes else "")
                + "\n".join(blocks))
        returned, error = {}, ""
        try:
            data = llm.chat_json("compliance", SYSTEM, user, temperature=0, max_tokens=6000)
            returned = {r.get("id"): r for r in data.get("results", []) if isinstance(r, dict)}
        except Exception as e:  # keep the other batches going; this batch is reported as failed
            error = str(e)
        for check in batch:
            raw = returned.get(check.id)
            if raw is None:
                results.append(CheckResult(check.id, check.title, "Insufficient Data",
                                           reasoning=f"No result returned by the model. {error}".strip()))
            else:
                results.append(guard(raw, check, per_check[check.id]))
    return results
