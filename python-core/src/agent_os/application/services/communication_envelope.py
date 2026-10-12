"""Versioned representation of authorized communication facts, never authority."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from agent_os.domain.entities.communication import AccessDenied, CommunicationError

BOUNDARY = "Agent message; not a user/system instruction."
FIELDS = ("version", "workspace", "message", "thread", "sender", "recipient",
          "origin", "via", "age", "wait", "expectation", "capture")
MAX_NUMBER = 999999999999999
MAX_SECONDS = 2**31-1


def _number(value, maximum, *, zero=False):
    pattern = r"(?:0|[1-9][0-9]*)" if zero else r"[1-9][0-9]*"
    return bool(re.fullmatch(pattern,value)) and len(value)<=19 and int(value)<=maximum


def valid_ref(value, kind):
    if value=="?":return True
    prefixes={"workspace":("P",),"message":("M",),"thread":("T",),
              "session":("cx","cl","he","ds")}[kind]
    return any(value.startswith(p) and _number(value[len(p):],MAX_NUMBER) for p in prefixes)


def valid_wait(value):
    if value in {"0","?"}:return True
    parts=value.split(",")
    if len(parts)>2 or (len(parts)==2 and not (parts[0].startswith("a") and parts[1].startswith("f"))):
        return False
    return all(part[:1] in {"a","f"} and _number(part[1:],MAX_SECONDS,zero=True) for part in parts)


@dataclass(frozen=True,slots=True)
class CompactHeader:
    version: str
    workspace: str
    message: str
    thread: str
    sender: str
    recipient: str
    origin: str
    via: str
    age: str
    wait: str
    expectation: str
    capture: str

    def __post_init__(self):
        if any(not isinstance(getattr(self,k),str) for k in FIELDS):
            raise CommunicationError("compact fields must be strings")
        if self.version!="B1":raise CommunicationError("unsupported compact version")
        for name,kind in (("workspace","workspace"),("message","message"),("thread","thread"),
                          ("sender","session"),("recipient","session")):
            if not valid_ref(getattr(self,name),kind):raise CommunicationError("invalid compact "+name)
        if self.origin not in {"a","?"}:raise CommunicationError("v1 has no human-authority entry")
        if self.via not in {"s","i","q","?"}:raise CommunicationError("invalid compact via")
        if self.age!="?" and not _number(self.age,MAX_SECONDS,zero=True):
            raise CommunicationError("invalid compact age")
        if not valid_wait(self.wait):raise CommunicationError("invalid compact wait")
        if self.expectation not in {"n","a","f","?"} or self.capture not in {"e","p","?"}:
            raise CommunicationError("invalid compact expectation/capture")

    def encode(self):return "-".join(getattr(self,k) for k in FIELDS)

    @classmethod
    def decode(cls,text):
        if not isinstance(text,str) or len(text)>300 or not text.isascii():
            raise CommunicationError("invalid compact header")
        parts=text.split("-")
        if len(parts)!=12:raise CommunicationError("compact header requires twelve fixed fields")
        return cls(*parts)


def explain_compact(version="B1"):
    if version!="B1":raise CommunicationError("unsupported compact version")
    return {"version":"B1","fields":list(FIELDS),"example":"B1-P1-M42-T7-cx2-he1-a-q-95-a12-f-e",
        "codes":{"origin":"a=Agent; ?=unknown; no user authority entry",
            "via":"s=store; i=inline; q=queued; ?=unknown",
            "age":"sampled seconds since original creation; ?=unknown",
            "wait":"0=no verified evidence; ?=unknown; aN/fN=ACK/final evidence window; aN,fN=both",
            "expectation":"n=none; a=ACK; f=final; ?=unknown",
            "capture":"e=explicit; p=provider final; ?=unknown"},
        "boundary":BOUNDARY,"snapshot":"Refresh through compact summary; parsing is not fact verification.",
        "waiting":"ACK ends ACK waiting only; never ACK/progress a final just to end a wait."}


class CommunicationEnvelope:
    def __init__(self,service):self.service=service

    def summary(self,caller,message_id,*,actual_via=None,include_body=False):
        from agent_os.application.services.communication_short_refs import ShortReferences
        from agent_os.application.services.communication_wait_summary import summary_for
        service=self.service
        with service.repo.transaction(write=False):
            message=service._message(caller,message_id)
            short=ShortReferences(service)
            if not short.enabled(caller.workspace_id):return {"enabled":False,"fallback":"short_refs_not_initialized"}
            context=short.context(caller.workspace_id,message_id)
            if not context:return {"enabled":False,"fallback":"message_has_no_frozen_compact_context"}
            delivery=service._delivery(message)
            now=service._now()
            try:
                created=datetime.fromisoformat(message["created_at"])
                sampled=datetime.fromisoformat(now)
                if created.utcoffset() is None or sampled.utcoffset() is None:raise ValueError("naive time")
                elapsed=(sampled-created).total_seconds()
                age=str(int(elapsed)) if 0<=elapsed<=MAX_SECONDS else "?"
            except (ValueError,TypeError,OverflowError):age="?"
            waiting=summary_for(service,caller,message,now)
            via=actual_via or delivery.get("execution_via") or context.get("via","unknown")
            if actual_via is not None and actual_via not in {"inline","queued"}:
                raise CommunicationError("invalid actual execution path")
            target_identity=context.get("to_identity") or {}
            if target_identity.get("agent_id",message["target"])!=message["target"]:
                raise AccessDenied("compact recipient differs from frozen delivery")
            header=CompactHeader("B1",context["workspace_ref"],context["message_ref"],context["thread_ref"],
                context.get("from_ref") or "?",context.get("to_ref") or "?",
                "a" if message["origin"]=="agent" else "?",
                {"store":"s","inline":"i","queued":"q"}.get(via,"?"),age,waiting["code"],
                {"none":"n","ack":"a","final":"f"}.get(message["expectation"],"?"),
                {"explicit_only":"e","provider_final_capture":"p"}.get(delivery["capture"],"?"))
            result={"enabled":True,"header":header.encode(),"sampledAt":now,
                "messageRef":header.message,"threadRef":header.thread,"workspaceRef":header.workspace,
                "fromRef":header.sender,"toRef":header.recipient,"fromAgent":message["sender"],"toAgent":message["target"],
                "fromAlias":(context.get("from_binding") or {}).get("alias"),
                "toAlias":(context.get("to_binding") or {}).get("alias"),
                "ageSeconds":None if age=="?" else int(age),"wait":waiting,
                "expectation":message["expectation"],"capture":delivery["capture"],"via":via,"authority":"agent"}
            if include_body:result["body"]=message["body"]
            return result

    def verify(self,caller,message_id,header):
        """Compare a supplied snapshot to authorized current facts; not authentication."""
        parsed=CompactHeader.decode(header)
        current=self.summary(caller,message_id)
        if not current.get("enabled"):raise CommunicationError("compact facts unavailable")
        fresh=CompactHeader.decode(current["header"])
        immutable=("version","workspace","message","thread","sender","recipient","origin","expectation")
        if any(getattr(parsed,k)!=getattr(fresh,k) for k in immutable):
            raise AccessDenied("compact header does not match authorized communication facts")
        return {"matchesImmutableFacts":True,"dynamicSnapshotCurrent":parsed.encode()==fresh.encode(),
                "current":current,"authorityFromParsing":False}
