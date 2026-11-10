# Design — Search Chat Agent

## The brief

Build the best chat agent you can with **one tool, web search**.
It should:
1. **Answer fast.**
2. **Get things right.**
3. **Remember what you asked, and when.**

Repo: https://github.com/Ganesh-123-maker/search-chat-agent

## 1. The one-tool decision

The agent has exactly one tool: `web_search(query) -> [{title, url, snippet}]`
(`search_tool.py`). Everything else — routing, synthesis, memory —
is plain code around that tool, not a second tool in disguise.

Why one tool is enough, and why it is better here:

- **A chat agent's failure modes are search failures.** It guesses,
  it uses a stale fact, or it cannot find the source again. One
  well-understood tool, called well, fixes more of those than five
  half-used tools.
- **No LLM, no API key, on purpose.** An LLM call is the slowest,
  most expensive and most hallucination-prone part of a typical
  agent. This agent answers *extractively*: the answer is built
  from search snippets, not generated from a model's weights.
  That makes every claim traceable to a URL, makes the agent
  runnable by anyone with Python and no account, and makes the
  tests deterministic (the search function can be mocked).
- **Trade-off, stated honestly:** the agent cannot write essays,
  code, or poetry the way an LLM can, and it cannot answer a
  question the web does not answer. That is the price of
  "get things right" — I chose correctness over fluency.

## 2. Answer fast

| Technique | Where | Effect (measured) |
|---|---|---|
| No model call | `agent.py` | The whole answer is search + string work; a factual question answers in ~1.2 s end-to-end (live run, 2026-11-10) |
| Parallel queries | `ChatAgent._search_parallel` | The question and a shorter reformulation run at the same time via `ThreadPoolExecutor`, so a badly-phrased question costs 0 extra seconds |
| Short timeout, fast fail | `search_tool.py`, `TIMEOUT = 8` | A slow endpoint does not hang the chat; the next endpoint is tried immediately |
| 1-hour result cache | `search_tool.py`, `_cache` | A repeated question is instant and does not re-hit the engine |
| No search when it cannot help | `ChatAgent.needs_search` | Greetings and memory questions skip search entirely — recall answers in 0.0 s |
| Stdlib only, no startup cost | whole repo | `python3 agent.py` starts instantly; no model download, no server |

The reformulated second query is the main speed/quality trick:
`"What is the capital of France?"` is also searched as
`"capital France"`. Whichever phrasing the engine likes better
wins, at no extra wall-clock cost.

## 3. Get things right

Accuracy is enforced by *refusing to do the things that make
agents wrong*, not by a cleverer prompt:

1. **Cite everything factual.** Every factual answer lists its
   sources as `[n] title — url`. A claim without a source is
   not presented as a fact.
2. **Corroboration.** A claim is stated as fact only when a
   second, independent source supports it. The agent picks the
   most informative second source (most shared words with the
   question, then longest snippet), and quotes it. If only one
   source returns, the answer says so explicitly:
   *"only one source returned this — treat it as single-source,
   not confirmed."*
3. **No results = no guess.** If search returns nothing, the
   agent says *"I searched the web and found nothing I could
   verify on that — I don't want to guess."* This is tested
   (`test_no_results_means_no_guess`).
4. **No invented numbers or dates.** Numbers and dates in an
   answer come from a snippet, verbatim. The agent never
   "rounds" a snippet into a new number.
5. **Stale-data honesty.** Every answer is stamped with the
   time it was answered (`Answered in 1.2s · 2026-11-10 16:41 UTC`),
   so a reader can tell whether "current" means today.
6. **Fallbacks, in order, never fakes.** The search tool tries
   DuckDuckGo lite HTML, then DuckDuckGo HTML, then the
   Instant Answer API. If all three fail it raises `SearchError`
   and the agent reports the failure — it never returns a
   plausible-looking invented result.
7. **Rate-limit hygiene.** One create-style burst is exactly
   what gets a search client blocked. Calls are sequential
   per query, with an 8 s timeout and no retry storm.

Known limits (not hidden):
- Snippets can be wrong, out of date, or SEO spam. Corroboration
  reduces that risk; it does not eliminate it. For a high-stakes
  decision, open the cited source.
- DuckDuckGo's lite HTML is an unofficial endpoint and can
  change shape — the parser is quote-agnostic and tested
  against live HTML (a real bug of this kind was found and
  fixed during development: the live page uses single quotes).
- The agent cannot browse behind logins, paywalls, or
  JavaScript-only pages.

## 4. Remember what you asked, and when

Memory is a local SQLite database (`memory.py`, `memory.db`,
git-ignored — nothing leaves the machine).

- **Every turn is stored** with an ISO-8601 UTC timestamp:
  `turns(id, ts, role, text)`. User question and agent answer
  are both stored, so history is a real transcript.
- **Recall is keyword-based, with a precision guard.** A search
  for "capital of France" must match at least 2 content words,
  so "capital of Mars" does not falsely recall "capital of
  France" just because both contain "capital" (this exact
  bug was caught by a test and fixed).
- **Memory questions are routed, not searched.** "When did I
  ask about France?" is answered from the database, with the
  timestamp quoted:
  `2026-11-10T16:41:38+00:00 — "What is the capital of France?"`
  If there is no matching turn, the agent says so instead of
  inventing a past conversation.
- **Follow-ups work** because the previous turn is in the
  database, and `--history` / `--recall <topic>` expose the
  log from the command line.
- **Forgetting is trivial:** delete `memory.db`.

## 5. Architecture

```
                ┌──────────────┐
                │  CLI / --ask │
                └──────┬───────┘
                       ▼
            ┌────────────────────┐
            │  ChatAgent (agent.py)
            │  route → search? memory? greeting?
            └────┬───────────┬───┘
                 │           │
        ┌────────▼───┐  ┌────▼────────┐
        │ web_search │  │ Memory (SQLite)
        │ (1 tool)   │  │ turns + ts
        └────────────┘  └─────────────┘
   search_tool.py: DuckDuckGo lite → HTML → Instant Answer
```

Files:

| File | Role |
|---|---|
| `agent.py` | Routing, answer synthesis, corroboration, CLI |
| `search_tool.py` | The one tool: `web_search`, parsing, cache, fallbacks |
| `memory.py` | SQLite memory: store, recent, keyword recall |
| `test_agent.py` | 10 unit tests, no network (search mocked) |
| `design.md` | This file |
| `README.md` | How to run, live demo transcript |

## 6. Evaluation (measured, 2026-11-10)

| Check | Result |
|---|---|
| Unit tests | 10/10 pass (`python3 -m unittest test_agent.py`) |
| "What is the capital of France?" | Correct, cited (Wikipedia + WorldAtlas), **1.2 s** |
| "When did I ask about France?" | Correct, with timestamp, **0.0 s**, no search call |
| "Who won the 2026 FIFA World Cup?" | Correct per sources (Spain 1–0 Argentina, cited to FIFA/Wikipedia), **1.4 s** |
| Unanswerable / no results | Says it doesn't know, does not guess (tested) |
| Single-source answer | Flagged as single-source (tested) |
| Greeting | Answered without a search call (tested) |

## 7. What I would do next

1. Add a second corroboration signal: prefer sources whose
   snippets agree on numbers, not just on words.
2. Add per-source freshness: show each source's date when
   the engine provides one, and down-rank results older
   than the question needs.
3. Add a `--json` output mode so other programs can use
   the agent's answer + citations + timestamp.
4. Keep the one-tool rule: any of the above is still just
   better use of `web_search` and `memory`, not a new tool.
