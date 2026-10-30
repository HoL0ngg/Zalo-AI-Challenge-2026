"""Answerability gate (rule part). Blocks only on provable evidence; ambiguity passes through.

`unanswerable` means the data cannot support the question: a requested concept the business
does not provide, an entity that does not exist, or a period entirely outside the data.
Wrongly blocking an answerable question costs more than letting an unanswerable one through
to execution, so mapping failures and ambiguous links never block.
"""
from datamate.core import GateResult, LinkResult

ENTITY_REASON = {"product": "Không có mã hoặc tên sản phẩm được hỏi trong dữ liệu của cơ sở.",
                 "customer": "Không có mã hoặc tên khách hàng được hỏi trong dữ liệu của cơ sở.",
                 "category": "Không có nhóm hàng được hỏi trong dữ liệu của cơ sở."}
PERIOD_REASON = "Khoảng thời gian được hỏi nằm ngoài dữ liệu của cơ sở."


def gate(linked: LinkResult) -> GateResult:
    flags = linked.flags or {}
    if flags.get("missing_entity"):
        kind = (flags.get("missing_mentions") or [{}])[0].get("kind", "product")
        return GateResult(linked, False, ENTITY_REASON.get(kind, ENTITY_REASON["product"]))
    missing = flags.get("missing_capability") or []
    if missing:
        reasons = flags.get("missing_capability_reasons") or {}
        return GateResult(linked, False, reasons.get(missing[0]) or f"Không có dữ liệu về {missing[0]} trong dữ liệu của cơ sở.")
    if flags.get("period_outside_data"):
        return GateResult(linked, False, PERIOD_REASON)
    return GateResult(linked)


gate_stub = gate  # backward-compatible name
