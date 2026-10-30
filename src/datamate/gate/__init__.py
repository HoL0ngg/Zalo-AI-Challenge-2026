from datamate.core import GateResult, LinkResult


def gate_stub(linked: LinkResult) -> GateResult:
    return GateResult(linked)
