"""Pure plan invariants and content states; no filesystem dependencies."""

import base64
import hashlib
import json
from dataclasses import dataclass


class ForvynxError(Exception):
    def __init__(self, message, code=3):
        super().__init__(message)
        self.code = code


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def content_state(data):
    return {"kind": "absent"} if data is None else {"kind": "file", "sha256": sha(data)}


def encode(data):
    return None if data is None else base64.b64encode(data).decode("ascii")


def decode(value):
    try:
        return None if value is None else base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ForvynxError("Invalid content payload") from exc


@dataclass(frozen=True)
class Plan:
    """A content-addressed proposal, never an authorization credential."""

    value: dict

    @staticmethod
    def seal(value):
        body = {k: v for k, v in value.items() if k != "digest"}
        return Plan({**body, "digest": sha(canonical(body))})

    def validate(self):
        value = self.value
        if value.get("schema_version") != 1 or value.get("kind") != "onboard":
            raise ForvynxError("Unsupported plan format", 5)
        if Plan.seal(value).value["digest"] != value.get("digest"):
            raise ForvynxError("Plan digest mismatch")
        if not value.get("repositories") or not value.get("actions"):
            raise ForvynxError("Empty onboarding plan")
        paths = set()
        for action in value["actions"]:
            key = (action["root"], action["path"])
            if key in paths:
                raise ForvynxError("Duplicate action")
            paths.add(key)
            if content_state(decode(action.get("content_b64"))) != action["after"]:
                raise ForvynxError("Payload does not match planned after state")
            if content_state(decode(action.get("before_b64"))) != action["before"]:
                raise ForvynxError("Backup does not match planned before state")
        return self

    def require_confirmation(self, receipt):
        if receipt != self.value["digest"]:
            raise ForvynxError("Explicit confirmation of this plan digest is required", 2)

    def classify(self, states):
        if all(s == a["after"] for s, a in zip(states, self.value["actions"])):
            return "no_change"
        if all(s == a["before"] for s, a in zip(states, self.value["actions"])):
            return "before"
        raise ForvynxError("Files drifted or transaction is partial; inspect recovery journal")
