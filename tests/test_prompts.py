from astcho.prompts import (
    meme_selection_prompt,
    meme_taste_prompt,
    memory_extraction_prompt,
    planner_prompt,
    private_reply_prompt,
    reasoning_reply_prompt,
    reply_prompt,
)

PERSONA = {
    "identity": {
        "name": "星回",
        "self_cognition": "温暖但有主见的少年",
        "personality_tags": ["偶尔臭屁"],
        "behavioral_habits": ["熟人面前会吐槽"],
    },
    "preferences": {
        "likes": ["音游", "甜食"],
        "dislikes": ["鸡汤标语"],
    },
    "style": ["短句自然"],
    "relationships": {"private-user": {"desc": "不得进入全局策展 Prompt"}},
}


def test_planner_prompt_preserves_decision_contract():
    prompt = planner_prompt(
        "[m1] user: hello",
        bot_name="Astcho",
        current_time="12:00:00",
        accumulated_count=1,
        time_span_seconds=0,
        participant_count=1,
        last_bot_spoke_seconds=None,
    )
    for field in (
        "action",
        "target_message_id",
        "reason",
        "excitement",
        "shyness",
        "affinity_score",
        "should_meme",
        "meme_query",
    ):
        assert field in prompt


def test_reply_prompt_keeps_persona_emotion_memory_and_context():
    prompt = reply_prompt(
        bot_name="Astcho",
        profile={"personality": "warm", "style": ["brief"]},
        context="group context",
        memories=["memory atom"],
        schedule="calm",
        emotion={"excitement": 0.2, "shyness": 0.1, "affinity": 0.8},
        planner_reason="direct mention",
    )
    for value in ("warm", "brief", "group context", "memory atom", "direct mention", "0.80"):
        assert value in prompt


def test_memory_prompt_anchors_user_id():
    messages = memory_extraction_prompt(text="likes rhythm games", user_id="u42")
    assert "UID:u42" in messages[0]["content"]
    assert "u42" in messages[1]["content"]


def test_persona_preferences_reach_group_and_private_reply_prompts():
    group = reply_prompt(
        bot_name="星回",
        profile=PERSONA,
        context="群聊",
        memories=[],
        schedule="日常",
    )
    private = private_reply_prompt(
        bot_name="星回", profile=PERSONA, nickname="朋友", history=[], latest="在吗"
    )
    for prompt in (group, private):
        for value in ("温暖但有主见", "偶尔臭屁", "熟人面前会吐槽", "音游", "鸡汤标语", "短句自然"):
            assert value in prompt


def test_reply_prompts_preserve_peer_tone_and_kaomoji_habit():
    arguments = dict(
        bot_name="星回",
        profile=PERSONA,
        context="群聊",
        memories=[],
        schedule="日常",
    )
    group = reply_prompt(**arguments)
    reasoning = reasoning_reply_prompt(**arguments)
    private = private_reply_prompt(
        bot_name="星回", profile=PERSONA, nickname="朋友", history=[], latest="在吗"
    )

    for prompt in (group, reasoning, private):
        assert "邻家弟弟" in prompt
        assert "上位者" in prompt
        assert "(´・ω・`)" in prompt
        assert "不必句句都用" in prompt


def test_meme_prompts_receive_persona_without_relationships():
    taste = meme_taste_prompt(
        "可爱贴纸",
        ["卖萌"],
        "治愈",
        profile=PERSONA,
        bot_name="星回",
    )
    selection = meme_selection_prompt(
        "好耶",
        [{"description": "庆祝", "inclination": "开心"}],
        profile=PERSONA,
        bot_name="星回",
    )
    for prompt in (taste, selection):
        assert "温暖但有主见" in prompt
        assert "音游" in prompt
        assert "鸡汤标语" in prompt
        assert "private-user" not in prompt
        assert "不得进入全局策展" not in prompt
