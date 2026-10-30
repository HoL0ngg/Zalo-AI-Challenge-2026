import json

from datamate.core import LinkResult


def build_prompt(linked: LinkResult) -> str:
    question = linked.resolved.question
    return "Return one read-only DuckDB SELECT, no explanation. Never guess numerical answers.\n" + json.dumps({
        "schema": linked.context.profile, "readme": linked.context.readme,
        "rulebook": linked.context.rulebook, "as_of_date": question.as_of_date,
        "question": question.question,
    }, ensure_ascii=False, default=str)
