import re

from datamate.core import Candidate, LinkResult
from datamate.ingest.profiler import quote


class MockBackend:
    """Small explicit grammar using literal schema names; no business semantics."""
    def generate(self, prompt: str, linked: LinkResult) -> Candidate:
        text = linked.resolved.question.question.strip()
        match = re.fullmatch(r"(?:count|đếm) (\w+)", text, re.I)
        if match:
            return Candidate(f"SELECT count(*) FROM {quote(match[1])}", "number", "count")
        match = re.fullmatch(r"(sum|tổng|avg|min|max|list|danh sách) (\w+) (?:from|trong) (\w+)", text, re.I)
        if match:
            op, column, table = match.groups()
            op = {"tổng": "sum", "danh sách": "list"}.get(op.lower(), op.lower())
            if op == "list":
                return Candidate(f"SELECT {quote(column)} FROM {quote(table)} ORDER BY 1", "list")
            return Candidate(f"SELECT {op}({quote(column)}) FROM {quote(table)}")
        match = re.fullmatch(r"(?:table|bảng) (\w+)", text, re.I)
        if match:
            return Candidate(f"SELECT * FROM {quote(match[1])} ORDER BY ALL", "table")
        raise ValueError("Unsupported mock question; expected count/sum/avg/min/max/list/table grammar")
