from pipeline.catalog import TOOLS


def choose_tool(requirement: str) -> dict:
    text = requirement.lower()
    scores = {}
    hits = {}
    for name, spec in TOOLS.items():
        matched = [cue for cue in spec["cues"] if cue.lower() in text]
        hits[name] = matched
        scores[name] = len(matched)

    ranked = sorted(scores, key=lambda name: scores[name], reverse=True)
    best = ranked[0]
    second = ranked[1]
    ambiguous = scores[best] == 0 or scores[best] == scores[second]
    return {
        "tool": None if ambiguous else best,
        "scores": scores,
        "hits": hits,
        "ambiguous": ambiguous,
        "ranked": ranked,
    }
