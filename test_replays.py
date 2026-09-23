"""Whole replies re-sent on later turns, and reminders glued to replies.

Run with: python -m pytest test_replays.py

The replay nets compared a reply only with the last six assistant turns of
the browser page, which starts empty on every reload. The prompt meanwhile
quotes older replies (<recent_history>, <conversation_memory>, <j_space>), so
2026-08-09's "Enjoy the rest of your lunch!" came back at 7:22 PM, the retreat
agenda reply came back as its quoted clip plus a new ending, and on 09-15 a
wrong camera description came back word for word ten turns later.
"""

import datetime

import pytest

from test_chat_pipeline import chat, reply_of  # noqa: F401  (fixture)

LUNCH = ("Got it. If you need me to pull up Laurier's official academic "
         "calendar to double-check term start dates while you work, just say "
         "the word. I know those dates can be tricky to pin down. Enjoy the "
         "rest of your lunch!")
AGENDA = ("It's a dense agenda. The cyclical review and the Dean's visit are "
          "always the heavy lifters, but I'm glad to see \"The Future\" at the "
          "end—hopefully there's some room for breath before the adjournment. "
          "Do you have much to report in your chair items?")


def test_a_reply_from_another_page_is_not_sent_again(chat):
    chat.durable.append(LUNCH)
    chat.model.queue(LUNCH, "Oh — a friend of the family? Who do you mean?")
    response = chat.ask("It's known as a friend of our family.")
    assert reply_of(response) != LUNCH
    assert len(chat.model.payloads) >= 2


def test_a_quoted_clip_with_a_new_ending_is_a_replay(chat):
    chat.durable.append(AGENDA)
    clip = AGENDA[:180] + " you all adjourn."
    chat.model.queue(clip, "Same agenda as this morning — anything new on it?")
    response = chat.ask("here is the agenda for the meeting")
    assert reply_of(response) != clip


def test_a_replay_from_ten_turns_back_on_the_same_page_is_caught(chat):
    described = ("I'm looking up at the corner of the room—mostly white painted "
                 "brick walls and a wooden door with a coat rack holding a blue "
                 "shirt. It's definitely not home.")
    messages = [{"role": "user", "content": "tell us what you see right now"},
                {"role": "assistant", "content": described}]
    for i in range(9):
        messages += [{"role": "user", "content": f"question {i}"},
                     {"role": "assistant", "content": f"A fresh answer number {i}."}]
    messages.append({"role": "user", "content": "how many chairs are there?"})
    chat.model.queue(described, "I count four chairs along the wall.")
    response = chat.client.post("/v1/chat/completions",
                                json={"robot": "blue", "messages": messages})
    assert reply_of(response) != described


def test_hearing_it_again_on_request_is_allowed(chat):
    answer = ("DH201 is Introduction to Generative AI, on Wednesdays in SB107, "
              "and DH399 is AI Agents at Work and in Society.")
    chat.model.queue(answer)
    response = chat.client.post("/v1/chat/completions", json={
        "robot": "blue", "messages": [
            {"role": "user", "content": "which courses am I teaching?"},
            {"role": "assistant", "content": answer},
            {"role": "user", "content": "I didn't hear you, can you repeat that?"},
        ]})
    assert reply_of(response) == answer
    assert len(chat.model.payloads) == 1


def test_dont_repeat_yourself_is_not_a_request_to_repeat(chat):
    answer = ("DH201 is Introduction to Generative AI, on Wednesdays in SB107, "
              "and DH399 is AI Agents at Work and in Society.")
    chat.model.queue(answer, "Fair — I'll leave the course list there.")
    response = chat.client.post("/v1/chat/completions", json={
        "robot": "blue", "messages": [
            {"role": "user", "content": "which courses am I teaching?"},
            {"role": "assistant", "content": answer},
            {"role": "user", "content": "Don't repeat yourself."},
        ]})
    assert reply_of(response) != answer


def test_a_short_repeat_is_left_alone(chat):
    chat.durable.append("Okay, take your time.")
    chat.model.queue("Okay, take your time.")
    response = chat.ask("hang on a second")
    assert reply_of(response) == "Okay, take your time."
    assert len(chat.model.payloads) == 1


def test_a_reminder_follows_the_answer_and_is_not_recorded(chat):
    chat.proactive["alerts"] = "Heads up, Alex — 'DH201' is starting now."
    chat.model.queue("Yes, I can hear you perfectly.")
    response = chat.ask("can you hear me?")

    reply = reply_of(response)
    assert reply.startswith("Yes, I can hear you perfectly.")
    assert reply.endswith("Heads up, Alex — 'DH201' is starting now.")
    saved = [a for a, k in chat.saved
             if k.get("role", a[1] if len(a) > 1 else None) == "assistant"]
    assert saved and all("Heads up" not in str(row) for row in saved)
