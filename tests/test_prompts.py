from astcho.prompts import memory_extraction_prompt, planner_prompt, reply_prompt


def test_planner_prompt_preserves_decision_contract():
    prompt = planner_prompt("[m1] user: hello", bot_name="Astcho", current_time="12:00:00",
                            accumulated_count=1, time_span_seconds=0, participant_count=1,
                            last_bot_spoke_seconds=None)
    for field in ("action", "target_message_id", "reason", "excitement", "shyness",
                  "affinity_score", "should_meme", "meme_query"):
        assert field in prompt


def test_reply_prompt_keeps_persona_emotion_memory_and_context():
    prompt = reply_prompt(bot_name="Astcho", profile={"personality": "warm", "style": ["brief"]},
                          context="group context", memories=["memory atom"], schedule="calm",
                          emotion={"excitement": 0.2, "shyness": 0.1, "affinity": 0.8},
                          planner_reason="direct mention")
    for value in ("warm", "brief", "group context", "memory atom", "direct mention", "0.80"):
        assert value in prompt


def test_memory_prompt_anchors_user_id():
    messages = memory_extraction_prompt(text="likes rhythm games", user_id="u42")
    assert "UID:u42" in messages[0]["content"]
    assert "u42" in messages[1]["content"]
