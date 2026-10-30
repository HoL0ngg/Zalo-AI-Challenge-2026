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
EMPTY_PERIOD_REASON = "Không có giao dịch hợp lệ trong kỳ được hỏi để xác định kết quả."
ZERO_BASE_REASON = "Kỳ so sánh có mẫu số bằng 0, không xác định tỷ lệ tăng trưởng."
UNCOSTED_REASON = "Thiếu lô có giá nhập cho một số sản phẩm đã bán trong kỳ."
# Operations with no defined result on an empty period. topN gives [], sums and counts give 0: never blocked.
UNDEFINED_ON_EMPTY = {"top1", "bottom1", "date_of_max", "avg"}


def _data_reason(linked: LinkResult) -> str | None:
    """Reason from facts read out of the data (`period_stats`); None when unknown or answerable."""
    stats = (linked.flags or {}).get("period_stats")
    if not stats:
        return None
    hints = linked.resolved.intent_hints or {}
    operation = hints.get("operation")
    if operation in UNDEFINED_ON_EMPTY:
        primary = next((s for s in stats if s["role"] == "primary"), None)
        if primary is not None and primary["rows"] == 0:
            return EMPTY_PERIOD_REASON
    if operation == "compare_percent":
        comparison = next((s for s in stats if s["role"] == "comparison"), None)
        measure = "qty" if hints.get("metric") == "quantity" else "revenue"
        if comparison is not None and comparison[measure] == 0:
            return ZERO_BASE_REASON
    return None


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
    reason = _data_reason(linked) or (UNCOSTED_REASON if flags.get("uncosted_skus") else None)
    if reason:
        return GateResult(linked, False, reason)
    return GateResult(linked)


gate_stub = gate  # backward-compatible name
