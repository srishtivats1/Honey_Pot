from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import re
import requests
import time

# ================= CONFIG =================
API_KEY = "YOUR_SECRET_API_KEY"
GUVI_CALLBACK_URL = "https://hackathon.guvi.in/api/updateHoneyPotFinalResult"
MAX_MESSAGES = 8   # conversation end threshold

# In-memory session store (hackathon OK)
SESSIONS = {}

# ================= MODELS =================
class Message(BaseModel):
    sender: str   # "scammer" | "agent"
    text: str
    timestamp: int

class RequestBody(BaseModel):
    sessionId: str
    message: Message
    conversationHistory: Optional[List[Message]] = []
    metadata: Optional[dict] = {}

# ================= UTILS =================
SCAM_KEYWORDS = [
    "blocked", "verify", "urgent", "suspend",
    "upi", "otp", "kyc", "account", "immediately"
]

def detect_scam(text: str) -> bool:
    text = text.lower()
    return any(word in text for word in SCAM_KEYWORDS)

def extract_intelligence(text: str, intel: dict):
    intel["upiIds"] += re.findall(r"[a-zA-Z0-9.\-_]{2,}@[a-zA-Z]{2,}", text)
    intel["phoneNumbers"] += re.findall(r"\+91\d{10}", text)
    intel["phishingLinks"] += re.findall(r"https?://\S+", text)

    if detect_scam(text):
        intel["suspiciousKeywords"].append(text)

def agent_reply(history_len: int) -> str:
    replies = [
        "What do you mean my account will be blocked?",
        "Which bank are you calling from?",
        "I didn’t get any message earlier.",
        "Is this really required right now?",
        "Can you explain properly, I’m confused.",
        "Why are you asking for this information?",
        "I’m not comfortable sharing this.",
        "I will visit the bank branch instead."
    ]
    return replies[min(history_len, len(replies) - 1)]

def send_final_callback(session_id: str, session: dict):
    payload = {
        "sessionId": session_id,
        "scamDetected": session["scamDetected"],
        "totalMessagesExchanged": session["messageCount"],
        "extractedIntelligence": session["intelligence"],
        "agentNotes": "Scammer used urgency, fear tactics and payment redirection"
    }

    try:
        requests.post(GUVI_CALLBACK_URL, json=payload, timeout=5)
    except Exception as e:
        print("Callback failed:", e)

# ================= FASTAPI =================
app = FastAPI(title="Agentic Honeypot API")

@app.post("/honeypot/message")
def honeypot(
    body: RequestBody,
    x_api_key: str = Header(...)
):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    session_id = body.sessionId

    # Create session if not exists
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {
            "scamDetected": False,
            "agentActive": False,
            "messageCount": 0,
            "intelligence": {
                "bankAccounts": [],
                "upiIds": [],
                "phishingLinks": [],
                "phoneNumbers": [],
                "suspiciousKeywords": []
            }
        }

    session = SESSIONS[session_id]
    session["messageCount"] += 1

    msg = body.message

    # Extract intelligence only from scammer
    if msg.sender == "scammer":
        extract_intelligence(msg.text, session["intelligence"])

    # Detect scam
    if not session["scamDetected"] and detect_scam(msg.text):
        session["scamDetected"] = True
        session["agentActive"] = True

    # If agent not activated, ignore message
    if not session["agentActive"]:
        return {
            "status": "ignored",
            "reason": "No scam intent detected yet"
        }

    # End condition
    if session["messageCount"] >= MAX_MESSAGES:
        send_final_callback(session_id, session)
        del SESSIONS[session_id]

        return {
            "status": "ended",
            "message": "Honeypot session completed"
        }

    # Generate agent reply
    reply_text = agent_reply(len(body.conversationHistory))

    return {
        "status": "reply",
        "reply": {
            "sender": "agent",
            "text": reply_text,
            "timestamp": int(time.time())
        }
    }
