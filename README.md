# Search Chat Agent

The best chat agent you can build with **one tool: web search**.

It answers fast, gets things right, and remembers what you
asked — and when. No LLM, no API key, no account. Python
standard library only.

- **Fast:** a factual question answers in ~1.2 s — parallel
  search queries, an 8 s timeout, and a 1-hour result cache.
- **Right:** every factual claim is cited, corroborated by a
  second source when one exists, and flagged as single-source
  when it doesn't. No results means "I don't know", never a guess.
- **Memory:** every turn is saved in a local SQLite database
  with a timestamp, so "when did I ask about France?" gets a
  real answer with a real time.

Read the full reasoning in **[design.md](design.md)**.

## Run it

```bash
python3 agent.py                        # interactive chat
python3 agent.py --ask "What is the capital of France?"
python3 agent.py --ask "When did I ask about France?"
python3 agent.py --history              # past turns, with timestamps
python3 agent.py --recall "France"      # what you asked about a topic, and when
```

## Live demo (real run, 2026-11-10)

```
$ python3 agent.py --ask "What is the capital of France?"
Paris is the capital and largest city of France, with an estimated
city population of 2.04 million in an area of 105.4 km2, as of
January 2026, and a metropolitan population of 13.3 million (2023).

Corroborated by a second source: "Paris is the capital city of
France. The city has an approximate area of 41 square miles..."

Sources:
[1] Paris - Wikipedia — https://en.wikipedia.org/wiki/Paris
[2] What is the Capital of France? - Mappr — https://www.mappr.co/capital-cities/france/
[3] What is the Capital of France? - WorldAtlas — https://www.worldatlas.com/articles/what-is-the-capital-of-france.html
[4] What is the capital of France? Overview of Paris - iroamly.com — https://www.iroamly.com/france-travel/what-is-the-capital-of-france.html
[5] Paris | Definition, Map, Population, Facts, & History | Britannica — https://www.britannica.com/place/Paris

_Answered in 1.2s · 2026-11-10 16:41 UTC_

$ python3 agent.py --ask "When did I ask about France?"
You asked about "France":
- 2026-11-10T16:41:38+00:00 — "What is the capital of France?"

_Answered in 0.0s · 2026-11-10 16:41 UTC_
```

## Tests

```bash
python3 -m unittest test_agent.py -v
# 10 tests, all passing: search parsing, memory recall with
# timestamps, citations, single-source flagging, no-guess on
# empty results, greetings need no search.
```

## How it works

```
question → route: greeting? memory? else search
         → web_search (one tool, two queries in parallel)
         → answer from snippets only, with citations
         → corroborate with a second source, or flag single-source
         → save user + agent turns to memory.db with timestamps
```

## Files

| File | What it is |
|---|---|
| `agent.py` | The agent: routing, synthesis, CLI |
| `search_tool.py` | The one tool: `web_search` (DuckDuckGo lite → HTML → Instant Answer) |
| `memory.py` | SQLite memory with timestamps |
| `test_agent.py` | Unit tests (no network) |
| `design.md` | Design decisions, trade-offs, evaluation |
