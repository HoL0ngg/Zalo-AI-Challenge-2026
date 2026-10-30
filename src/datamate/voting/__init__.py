from datamate.core import ExecResult


def vote_stub(results: list[ExecResult]) -> ExecResult:
    return next(result for result in results if result.error is None)
