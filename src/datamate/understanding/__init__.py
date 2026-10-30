from datamate.core import BusinessContext, Question, ResolvedQuestion


def understand_stub(question: Question, context: BusinessContext) -> ResolvedQuestion:
    """Pass through unchanged; normalization and temporal resolution are deferred."""
    return ResolvedQuestion(question)
