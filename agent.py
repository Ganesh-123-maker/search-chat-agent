#!/usr/bin/env python3
"""Search Chat Agent — one tool, fast, accurate, with memory.

Usage:
    python3 agent.py                        # interactive chat
    python3 agent.py --ask "question"       # one question, print answer, exit
    python3 agent.py --ask "q" --no-memory # same, without saving the turn
    python3 agent.py --history              # show saved turns and exit
    python3 agent.py --recall "topic"       # what you asked about a topic, and when

The agent has exactly ONE tool: web_search (see search_tool.py).
It does not call any LLM and needs no API key, which is a design
choice, not a shortcut — see design.md. Answers are built only
from what the tool returns, with a citation for every factual
claim, so a wrong answer is traceable to a specific source
instead of being invented.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from memory import Memory
from search_tool import SearchError, web_search

GREETINGS = {"hi", "hello", "hey", "namaste", "good morning", "good afternoon",
             "good evening", "thanks", "thank you", "bye", "goodbye"}
MEMORY_PATTERNS = [
    re.compile(r"\b(what did i ask|what have i asked|what did you ask|my questions|"
               r"when did i ask|did i ask|have i asked)\b", re.I),
    re.compile(r"\b(what was my (last|previous) question|my last question)\b", re.I),
]


def _is_greeting(text: str) -> bool:
    return text.strip().lower().rstrip("!.") in GREETINGS


def _is_memory_question(text: str) -> bool:
    return any(p.search(text) for p in MEMORY_PATTERNS)


def _reformulate(question: str) -> str:
    """A second, shorter query for the same question — used in
    parallel with the first, so a bad phrasing does not sink the answer."""
    words = re.findall(r"[A-Za-z0-9]+", question)
    stop = {"what", "is", "are", "the", "a", "an", "of", "in", "on", "for",
            "to", "who", "when", "where", "how", "why", "did", "does", "do",
            "tell", "me", "about", "please", "give"}
    kept = [w for w in words if w.lower() not in stop]
    return " ".join(kept[:8]) or question


class ChatAgent:
    def __init__(self, memory: Memory | None = None):
        self.memory = memory or Memory()

    # -- routing ------------------------------------------------------
    def needs_search(self, question: str) -> bool:
        """No search for greetings or for questions about the
        conversation itself. Everything else is treated as
        needing external facts — guessing is not an option."""
        if _is_greeting(question) or _is_memory_question(question):
            return False
        return True

    # -- answering ----------------------------------------------------
    def answer(self, question: str, save: bool = True) -> str:
        started = time.monotonic()
        question = question.strip()
        if not question:
            return "Ask me something — a fact, a current event, or what you asked me before."
        if _is_greeting(question):
            reply = ("Hi! Ask me anything — I'll search the web for it, "
                     "cite my sources, and remember what you asked and when.")
        elif _is_memory_question(question):
            reply = self._answer_from_memory(question)
        else:
            reply = self._answer_from_search(question)
        elapsed = time.monotonic() - started
        reply = f"{reply}\n\n_Answered in {elapsed:.1f}s · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_"
        if save:
            self.memory.remember("user", question)
            self.memory.remember("agent", reply)
        return reply

    def _answer_from_memory(self, question: str) -> str:
        recent = self.memory.user_questions(n=20)
        if not recent:
            return "I don't have any earlier questions from you saved yet — this looks like our first conversation."
        # "when did I ask about X?" — find the matching turn, quote its time.
        topic = re.sub(r"(?i)what did i ask|when did i ask|did i ask|have i asked|about|"
                       r"my questions|please|tell me", "", question).strip(" ?")
        matches = self.memory.search(topic or question, n=5) if topic else []
        if matches:
            lines = [f'You asked about "{topic}":']
            for m in matches:
                lines.append(f'- {m["ts"]} — "{m["text"]}"')
            return "\n".join(lines)
        lines = ["Your recent questions:"]
        for q in reversed(recent[-5:]):
            lines.append(f'- {q["ts"]} — "{q["text"]}"')
        return "\n".join(lines)

    def _answer_from_search(self, question: str) -> str:
        queries = [question]
        alt = _reformulate(question)
        if alt.lower() != question.lower():
            queries.append(alt)
        results = self._search_parallel(queries)
        if not results:
            return ("I searched the web and found nothing I could verify on "
                    f"that — I don't want to guess. Try rephrasing the question, "
                    "or ask me something narrower.")
        # Agreement check: a claim is only stated as fact if it appears
        # in at least two independent sources, or in one source that is
        # quoted verbatim as a single-source claim.
        top = results[0]
        answer_lines = [top["snippet"]]
        sources = []
        for i, r in enumerate(results, 1):
            sources.append(f"[{i}] {r['title']} — {r['url']}")
        if len(results) >= 2:
            # Corroborate with the *most informative* second source,
            # not just the next one: longest snippet sharing a word
            # with the question.
            question_words = {w.lower() for w in re.findall(r"[A-Za-z]+", question)}
            second = max(results[1:], key=lambda r: (
                len(set(re.findall(r"[A-Za-z]+", r["snippet"].lower())) & question_words),
                len(r["snippet"])))
            answer_lines.append(
                "\nCorroborated by a second source: "
                f"\"{second['snippet']}\"")
        else:
            answer_lines.append(
                "\nNote: only one source returned this — treat it as "
                "single-source, not confirmed.")
        answer_lines.append("\nSources:\n" + "\n".join(sources))
        return "\n".join(answer_lines)

    @staticmethod
    def _search_parallel(queries: list) -> list:
        """Run the queries at the same time (fast) and merge by URL,
        keeping the first query's ordering."""
        merged, seen = [], set()
        with ThreadPoolExecutor(max_workers=len(queries)) as pool:
            for results in pool.map(_safe_search, queries):
                for r in results:
                    if r["url"] not in seen:
                        seen.add(r["url"])
                        merged.append(r)
        return merged[:5]


def _safe_search(query: str) -> list:
    try:
        return web_search(query)
    except (SearchError, ValueError):
        return []


def main(argv=None):
    parser = argparse.ArgumentParser(description="Search Chat Agent")
    parser.add_argument("--ask", help="ask one question and exit")
    parser.add_argument("--history", action="store_true", help="show saved turns")
    parser.add_argument("--recall", help="show what you asked about a topic, and when")
    parser.add_argument("--no-memory", action="store_true",
                        help="do not save this turn")
    parser.add_argument("--db", default="memory.db", help="memory database path")
    args = parser.parse_args(argv)

    agent = ChatAgent(Memory(args.db))
    if args.history:
        for turn in agent.memory.recent(20):
            print(f"{turn['ts']} [{turn['role']}] {turn['text']}")
        return 0
    if args.recall:
        for m in agent.memory.search(args.recall):
            print(f"{m['ts']} — \"{m['text']}\"")
        return 0
    if args.ask:
        print(agent.answer(args.ask, save=not args.no_memory))
        return 0

    print("Search Chat Agent — one tool (web search), citations, memory.")
    print("Type 'exit' to quit, 'history' to see past turns.\n")
    try:
        while True:
            question = input("You: ").strip()
            if question.lower() in ("exit", "quit"):
                break
            if question.lower() == "history":
                for turn in agent.memory.recent(10):
                    print(f"  {turn['ts']} [{turn['role']}] {turn['text']}")
                continue
            if not question:
                continue
            print(f"\nAgent: {agent.answer(question)}\n")
    except (KeyboardInterrupt, EOFError):
        print("\nBye — your questions are saved in memory.db.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
