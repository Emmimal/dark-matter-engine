"""Local Gemma via Ollama's HTTP API. Refuses any non-loopback host."""
import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_HOST = "http://127.0.0.1:11434"


class ModelError(RuntimeError):
    pass


def _assert_loopback(host):
    name = urllib.parse.urlparse(host).hostname or ""
    try:
        ok = name == "localhost" or ipaddress.ip_address(name).is_loopback
    except ValueError:
        ok = False
    if not ok:
        raise ModelError(f"refusing non-loopback model host: {host}")


class OllamaModel:
    def __init__(self, tag, host=DEFAULT_HOST, seed=42, timeout=600):
        _assert_loopback(host)
        self.tag, self.host, self.seed, self.timeout = tag, host.rstrip("/"), seed, timeout

    def info(self):
        digest = None
        try:
            with urllib.request.urlopen(self.host + "/api/tags", timeout=10) as r:
                for m in json.load(r).get("models", []):
                    if m.get("name") == self.tag or m.get("model") == self.tag:
                        digest = m.get("digest")
        except (urllib.error.URLError, OSError, ValueError):
            pass
        return {"tag": self.tag, "digest": digest}

    def generate_json(self, system, user):
        body = json.dumps({
            "model": self.tag, "stream": False, "format": "json",
            "options": {"temperature": 0, "seed": self.seed},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }).encode()
        req = urllib.request.Request(self.host + "/api/chat", body,
                                     {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                content = json.load(r)["message"]["content"]
        except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
            raise ModelError(f"Ollama request failed: {e}") from e
        content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.M).strip()
        try:
            return json.loads(content)
        except ValueError as e:
            raise ModelError(f"model returned invalid JSON: {e}") from e
