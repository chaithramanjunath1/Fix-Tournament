"""Exercises the Token Factory client and a whole race through it, against a mocked
OpenAI-compatible endpoint (no network, no key)."""
import json

import httpx
import pytest

from fixtournament.agent import build_roster
from fixtournament.cases import load_case
from fixtournament.llm import LLMError, NebiusClient
from fixtournament.runners import LocalRunner
from fixtournament.tournament import EventLog, Spec, Tournament

FIX = """Fix.

FILE: slugger/core.py
<<<<<<< SEARCH
    text = re.sub(r"[\\s_]+", sep, text)
=======
    text = re.sub(r"[\\s_-]+", sep, text).strip(sep)
>>>>>>> REPLACE

FILE: slugger/core.py
<<<<<<< SEARCH
        text = text[:max_length]
=======
        text = text[:max_length].strip(sep)
>>>>>>> REPLACE
"""


def make_client(handler):
    return NebiusClient("https://example.test/v1", "k", transport=httpx.MockTransport(handler))


def reply(text, usage=True):
    body = {"choices": [{"message": {"content": text}}]}
    if usage:
        body["usage"] = {"prompt_tokens": 11, "completion_tokens": 7}
    return httpx.Response(200, json=body)


def test_request_shape_and_think_stripping():
    seen = {}

    def handler(req):
        seen["auth"] = req.headers["authorization"]
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return reply("<think>hidden</think>answer")

    r = make_client(handler).complete(model="m", messages=[{"role": "user", "content": "hi"}])
    assert seen["auth"] == "Bearer k" and seen["url"].endswith("/v1/chat/completions")
    assert seen["body"]["model"] == "m"
    assert r.text == "answer" and (r.tokens_in, r.tokens_out) == (11, 7)


def test_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429, text="slow down") if len(calls) < 3 else reply("ok", usage=False)

    r = make_client(handler).complete(model="m", messages=[{"role": "user", "content": "hi"}])
    assert r.text == "ok" and len(calls) == 3 and r.tokens_in >= 1


def test_client_error_is_raised_not_retried():
    with pytest.raises(LLMError, match="401"):
        make_client(lambda req: httpx.Response(401, text="bad key")).complete(
            model="m", messages=[{"role": "user", "content": "hi"}])


def test_whole_race_over_the_live_client():
    def handler(req):
        sys_prompt = json.loads(req.content)["messages"][0]["content"]
        if "principal engineer" in sys_prompt:
            return reply("<think>hmm</think>The separator regex ignores hyphens.")
        if "staff engineer" in sys_prompt:
            return reply('{"summary": "ok", "root_cause": "regex", "risk": "low", "risk_notes": [], "follow_ups": []}')
        return reply(FIX)

    case = load_case("slugger")
    log = EventLog()
    spec = Spec(case.repo, case.issue_text, case.issue_title, case.test_cmd, case.timeout, case.title)
    t = Tournament(spec, make_client(handler), LocalRunner(), build_roster(4), "qualify", log)
    result = t.run()
    assert result["winner"] and result["review"]["risk"] == "low"
    start = log.events[0]
    assert start["type"] == "run.start" and start["source"] == "live"
