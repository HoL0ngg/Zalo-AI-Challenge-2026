"""Extract the SQL statement from a raw model reply (strict tags first, tolerant fallbacks after)."""
import re

THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
TAGGED = re.compile(r"<sql>(.*?)(?:</sql>|$)", re.S | re.I)
FENCED = re.compile(r"```[ \t]*(?:sql|duckdb)?[ \t]*\n(.*?)(?:```|$)", re.S | re.I)
START = re.compile(r"\b(?:with|select)\b", re.I)


def extract_sql(text: str) -> str:
    """Return the SQL in `text`, or "" when there is none (e.g. the reply was cut inside a <think> block).

    Order: `<sql>` tags, then a ``` fence, then the first WITH/SELECT keyword of an untagged reply.
    A tag or fence that was never closed (truncated generation) still yields its content.
    """
    if re.search(r"<think>", text, re.I) and not re.search(r"</think>", text, re.I):
        return ""
    text = THINK.sub("", text)
    for pattern in (TAGGED, FENCED):
        match = pattern.search(text)
        if match and match.group(1).strip():
            return match.group(1).strip().rstrip(";").strip()
    match = START.search(text)
    return text[match.start():].strip().rstrip(";").strip() if match else ""
