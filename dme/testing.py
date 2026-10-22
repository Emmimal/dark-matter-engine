"""Stub model for plumbing checks and tests. NOT a measure of Gemma's quality."""
import re

DEFAULT_RULES = {
    "C1": ["never charges the order a second time"],
    "C2": ["retries the charge up to 3 times"],
    "C3": ["returns 402 with the decline reason"],
    "J1": ["the job reappears in the queue"],
    "J2": ["retries the job after a delay of 30 seconds"],
    "J3": ["is ignored, so a producer can safely resend"],
    "A1": ["revokes all existing refresh tokens"], "A2": ["the old one stops working"],
    "A3": ["deletes the stored refresh token"], "U1": ["no activity for 24 hours"],
    "U2": ["rejected at the start of the upload with a 413"], "U3": ["returns its checksum"],
    "N1": ["kept for up to 6 hours"], "N2": ["dropped and counted in the metrics dashboard"],
    "N3": ["held and delivered at 07:00"],
    "K1": ["is released and the unit becomes available again"],
    "K2": ["shows the new price and notifies the customer at checkout"],
    "K3": ["returns 409 with the message"],
    "W1": ["moved to a dead-letter list kept for 14 days"],
    "W2": ["carries an HMAC signature header"],
    "W3": ["delivered in the order they were created"],
    "P1": ["deletes its cached copy before returning"],
    "P2": ["the least recently used profile is evicted"],
    "P3": ["the cache starts empty"],
    "E1": ["the status becomes failed with an error message"],
    "E2": ["rejected with a 422 response"],
    "E3": ["returns pending, ready or failed"],
}


class FakeModel:
    tag = "fake-model"

    def __init__(self, rules=None, scenarios=None, relevance=True):
        self.relevance = relevance
        self.rules = DEFAULT_RULES if rules is None else rules
        self.scenarios = scenarios or []

    def info(self):
        return {"tag": self.tag, "digest": None}

    def generate_json(self, system, user):
        if "DESCRIBE_QUOTE" in system:
            return {"situation": "stub description"}
        if "SITUATION_COMPARE" in system:
            return {"same_situation": self.relevance}
        if "RELEVANCE_CHECK" in system:
            return {"addresses_event": self.relevance}
        if "SCENARIO_GENERATION" in system:
            return {"scenarios": self.scenarios}
        sid = re.search(r"SCENARIO_ID: (\S+)", user).group(1)
        passages = user.split("PASSAGES:", 1)[1]
        for phrase in self.rules.get(sid, []):
            m = re.search(re.escape(phrase), passages, re.I)
            if m:
                return {"status": "Answered", "citations": [{"file": "", "text": m.group(0)}],
                        "open_question": ""}
        return {"status": "Not established", "citations": [],
                "open_question": f"What must happen in scenario {sid}?"}
