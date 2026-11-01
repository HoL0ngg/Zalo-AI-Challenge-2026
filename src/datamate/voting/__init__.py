from datamate.core import ExecResult


def vote_stub(results: list[ExecResult]) -> ExecResult:
    for result in results:
        if result.error is None:
            return result
    raise ValueError("no candidate executed: " + "; ".join(str(r.error)[:80] for r in results))
