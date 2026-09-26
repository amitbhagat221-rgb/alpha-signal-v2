"""
Alpha Signal v2 — the one Claude call + ```-fence JSON parse the output
generators share (stock dossiers, sector dossiers, tools/compare_reg_models).

Each call is logged to llm_usage via db.log_llm_usage(step, model, usage),
exactly as the inline copies did. sources/regulatory_classifier.py keeps its
own client code (batch API, owned by another session).
"""

import json

from db import log_llm_usage


def llm_text(prompt, model, step, max_tokens=1024, client=None):
    """Single-turn Claude call → response text; usage logged under `step`.
    `client` lets a caller reuse one anthropic.Anthropic() across many calls;
    otherwise one is built from ANTHROPIC_API_KEY."""
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model, max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    log_llm_usage(step, model, resp.usage)
    return resp.content[0].text


def llm_json(prompt, model, step, max_tokens=1024, client=None):
    """llm_text() parsed as JSON. Tolerates a ```json fenced block anywhere in
    the reply; a reply with no JSON at all comes back as {"raw_response": text}
    (a fenced block that isn't valid JSON raises json.JSONDecodeError)."""
    text = llm_text(prompt, model, step, max_tokens=max_tokens, client=client)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if "```" not in text:
            return {"raw_response": text}
        block = text.split("```")[1]
        if block.startswith("json"):
            block = block[4:]
        return json.loads(block)
