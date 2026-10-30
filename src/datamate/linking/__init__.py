from datamate.core import BusinessContext, LinkResult, ResolvedQuestion


def link_stub(resolved: ResolvedQuestion, context: BusinessContext) -> LinkResult:
    return LinkResult(resolved, context)
