import hashlib
import os
from dotenv import load_dotenv
load_dotenv()
import json
import time
import requests
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List, Optional
import uuid

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, Response
import io

from pydantic import BaseModel
from pymongo import MongoClient
from pymongo.errors import PyMongoError


from analyze_docx import (
    analyze,
    aggregate,
    load_paragraphs,
    plagiarism_analyze,
    plagiarism_aggregate,
)

from report_generator import generate_report_pdf

app = FastAPI(
    title="AI Plag Analyzer Backend",
    description="Accepts Word document uploads and returns AI + plagiarism analysis results.",
)

ALLOWED_PAYMENT_METHODS = {"google_pay", "phonepe"}

ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')
ADMIN_SESSION_TOKENS: Dict[str, Dict[str, Any]] = {}
PAYMENT_EVENTS: List[Dict[str, Any]] = []
USERS: Dict[str, Dict[str, Any]] = {}

DEFAULT_MONGODB_URI = 'mongodb+srv://prajayfaldesai987_db_user:hGsIgjrHhhZV0A2X@cluster0.6agqfbt.mongodb.net/?appName=Cluster0'
MONGODB_URI = os.getenv('MONGODB_URI', DEFAULT_MONGODB_URI)
MONGODB_DB_NAME = os.getenv('MONGODB_DB', 'ai_plag_analyzer')
mongo_client = None
mongo_db = None

try:
    mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    mongo_client.server_info()
    mongo_db = mongo_client[MONGODB_DB_NAME]
    mongo_db['users'].create_index('username', unique=True)
except PyMongoError:
    mongo_client = None
    mongo_db = None


def get_user_collection():
    return mongo_db['users'] if mongo_db is not None else None


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def find_user(username: str) -> Optional[Dict[str, Any]]:
    users = get_user_collection()
    if users is not None:
        return users.find_one({'username': username})
    return USERS.get(username)


def find_user_by_token(token: str) -> Optional[Dict[str, Any]]:
    users = get_user_collection()
    if users is not None:
        return users.find_one({'token': token})
    for user in USERS.values():
        if user.get('token') == token:
            return user
    return None


def serialize_user(user: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not user:
        return None
    subscription = user.get('subscription') or {'status': 'inactive', 'plan': None}
    return {
        'username': user.get('username'),
        'email': user.get('email'),
        'token': user.get('token'),
        'created_at': user.get('created_at'),
        'subscription': subscription,
    }


def set_user_subscription(username: str, subscription: Dict[str, Any]) -> None:
    users = get_user_collection()
    if users is not None:
        users.update_one({'username': username}, {'$set': {'subscription': subscription}})
    elif username in USERS:
        USERS[username]['subscription'] = subscription


class SubscribeRequest(BaseModel):
    plan: str = "pro"
    payment_method: str
    phone_number: Optional[str] = None


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class PaymentConfirmRequest(BaseModel):
    payment_event_id: str
    payment_id: str
    status: str = "completed"


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class PaymentConfirmRequest(BaseModel):
    payment_event_id: str
    payment_id: str
    status: str = "completed"


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def write_temp_docx(file_bytes: bytes) -> str:
    temp_file = NamedTemporaryFile(delete=False, suffix=".docx")
    temp_file.write(file_bytes)
    temp_file.flush()
    temp_file.close()
    return temp_file.name


def cleanup_temp_file(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def create_payment_event(plan: str, payment_method: str, provider: str, order_id: str, phone_number: Optional[str] = None, username: Optional[str] = None) -> Dict[str, Any]:
    event = {
        "id": str(uuid.uuid4()),
        "plan": plan,
        "payment_method": payment_method,
        "provider": provider,
        "order_id": order_id,
        "phone_number": phone_number,
        "status": "pending",
        "message": "Payment requested by user.",
        "created_at": int(time.time()),
        "username": username,
    }
    PAYMENT_EVENTS.append(event)
    return event


def admin_authorized(authorization: Optional[str]) -> bool:
    if not authorization:
        return False
    token = authorization.replace("Bearer ", "", 1)
    return token in ADMIN_SESSION_TOKENS


def create_razorpay_order(amount: int, receipt: str) -> Optional[Dict[str, Any]]:
    key_id = os.getenv("RAZORPAY_KEY_ID")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")

    print("Razorpay Key ID loaded:", bool(key_id))
    print("Razorpay Secret loaded:", bool(key_secret))

    if not key_id or not key_secret:
        print("Razorpay credentials are missing.")
        return None

    payload = {
        "amount": int(amount * 100),
        "currency": "INR",
        "receipt": receipt,
    }

    response = requests.post(
        "https://api.razorpay.com/v1/orders",
        auth=(key_id, key_secret),
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def send_text_to_external_api(text: str) -> Optional[Dict[str, Any]]:
    """Send the extracted document text to your paid API provider.

    Replace the body of this function with the exact request your API requires.
    The code below is a generic starting point using JSON POST and bearer auth.
    """
    api_url = os.getenv("ANALYSIS_API_URL")
    api_key = os.getenv("ANALYSIS_API_KEY")
    if not api_url:
        return None

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = {
        "text": text,
        "features": ["plagiarism", "ai_detection"],
    }

    extra_fields = os.getenv("ANALYSIS_API_EXTRA")
    if extra_fields:
        try:
            body.update(json.loads(extra_fields))
        except json.JSONDecodeError:
            pass

    response = requests.post(api_url, json=body, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


@app.post("/admin/login")
def admin_login(payload: AdminLoginRequest):
    if payload.username != ADMIN_USERNAME or payload.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

    token = str(uuid.uuid4())
    ADMIN_SESSION_TOKENS[token] = {
        "username": payload.username,
        "created_at": int(time.time()),
    }
    return {
        "status": "success",
        "token": token,
        "message": "Admin login successful.",
    }


class SignupRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


class SigninRequest(BaseModel):
    username: str
    password: str


@app.post("/signup")
def signup(payload: SignupRequest):
    if not payload.username or not payload.password:
        raise HTTPException(status_code=400, detail="username and password are required")

    users = get_user_collection()
    if users is not None:
        if users.find_one({'username': payload.username}):
            raise HTTPException(status_code=400, detail="User already exists")
        token = str(uuid.uuid4())
        users.insert_one({
            'username': payload.username,
            'email': payload.email,
            'password_hash': hash_password(payload.password),
            'token': token,
            'created_at': int(time.time()),
        })
    else:
        if payload.username in USERS:
            raise HTTPException(status_code=400, detail="User already exists")
        token = str(uuid.uuid4())
        USERS[payload.username] = {
            'username': payload.username,
            'email': payload.email,
            'password': payload.password,
            'token': token,
            'created_at': int(time.time()),
        }

    return {
        "status": "success",
        "message": "User created successfully",
        "token": token,
        "user": serialize_user({
            'username': payload.username,
            'email': payload.email,
            'token': token,
            'created_at': int(time.time()),
        }),
    }


@app.post("/signin")
def signin(payload: SigninRequest):
    if not payload.username or not payload.password:
        raise HTTPException(status_code=400, detail="username and password are required")

    user = find_user(payload.username)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    password_hash = hash_password(payload.password)
    expected_hash = user.get('password_hash')
    if expected_hash:
        if expected_hash != password_hash:
            raise HTTPException(status_code=401, detail="Invalid credentials")
    elif user.get('password') != payload.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = str(uuid.uuid4())
    user['token'] = token
    users = get_user_collection()
    if users is not None:
        users.update_one({'username': payload.username}, {'$set': {'token': token}})
    else:
        user['token'] = token

    return {
        "status": "success",
        "message": "Login successful",
        "token": token,
        "username": user.get("username"),
        "user": serialize_user(user),
    }


@app.get("/profile")
def profile(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header is required")

    token = authorization.replace("Bearer ", "", 1)
    user = find_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return {"status": "success", "message": "Profile loaded", "user": serialize_user(user)}


@app.get("/admin/payments")
def admin_payments(authorization: Optional[str] = Header(None)):
    if not admin_authorized(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"status": "success", "payments": PAYMENT_EVENTS}


@app.post("/payment-confirm")
def payment_confirm(payload: PaymentConfirmRequest):
    target = next((item for item in PAYMENT_EVENTS if item["id"] == payload.payment_event_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Payment event not found")

    target["status"] = payload.status
    target["payment_id"] = payload.payment_id
    target["message"] = "Payment received and confirmed by the system."
    target["confirmed_at"] = int(time.time())

    if target.get("username") and payload.status == "completed":
        set_user_subscription(target["username"], {
            "status": "active",
            "plan": target.get("plan"),
            "payment_event_id": target["id"],
            "activated_at": target["confirmed_at"],
        })

    return {
        "status": "success",
        "message": "Payment confirmed and admin notified.",
        "payment_event": target,
    }


def extract_value(response: Dict[str, Any], paths: List[str]) -> Optional[Any]:
    for path in paths:
        parts = path.split(".")
        current = response
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                break
        else:
            return current
    return None


def normalize_external_response(response: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(response, dict):
        return {}

    ai_score = extract_value(response, ["ai_score", "ai.score", "score", "ai_percentage", "ai.percent"])
    plag_score = extract_value(response, ["plagiarism_score", "plagiarism.score", "plag.score", "plagiarism_percentage"])
    ai_label = extract_value(response, ["ai_label", "ai.label", "label"])
    plag_label = extract_value(response, ["plagiarism_label", "plagiarism.label", "plag.label"])

    results = []
    raw_items = extract_value(response, ["paragraphs", "results", "items"]) or []
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            results.append({
                "ai_score": extract_value(item, ["ai_score", "ai.score", "score"]),
                "plagiarism_score": extract_value(item, ["plagiarism_score", "plagiarism.score", "plag.score"]),
                "ai_label": extract_value(item, ["ai_label", "ai.label", "label"]),
                "plagiarism_label": extract_value(item, ["plagiarism_label", "plagiarism.label"]),
                "reason": extract_value(item, ["reason", "explanation", "details"]),
            })

    return {
        "ai_score": float(ai_score) if ai_score is not None else None,
        "plagiarism_score": float(plag_score) if plag_score is not None else None,
        "ai_label": ai_label,
        "plagiarism_label": plag_label,
        "items": results,
    }


@app.get("/analyze")
def analyze_info():
    return {
        "status": "ok",
        "message": "Use POST /analyze with a multipart/form-data file upload to analyze a .docx document.",
    }


@app.post("/analyze")
async def analyze_document(
    file: UploadFile = File(...),
    mode: str = Form('ai'),
):
    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only .docx files are supported")

    if mode not in {"ai", "plagiarism"}:
        raise HTTPException(status_code=400, detail="Invalid analysis mode. Use ai or plagiarism.")

    file_bytes = await file.read()
    temp_path = write_temp_docx(file_bytes)

    try:
        paragraphs = load_paragraphs(temp_path)
        if not paragraphs:
            raise HTTPException(status_code=400, detail="The uploaded document contains no readable paragraphs.")

        document_text = "\n\n".join(p["text"] for p in paragraphs)
        external_data = None
        external_error = None

        try:
            raw_response = send_text_to_external_api(document_text)
            if raw_response:
                external_data = normalize_external_response(raw_response)
        except Exception as exc:
            external_error = str(exc)

        if mode == "plagiarism":
            heuristic_results = plagiarism_analyze(paragraphs)
        else:
            heuristic_results = analyze(paragraphs, use_openai=False)

        constructed_results = []
        external_items = external_data.get("items", []) if external_data else []

        for idx, paragraph in enumerate(heuristic_results):
            item_data = external_items[idx] if idx < len(external_items) else {}
            score = item_data.get("plagiarism_score") if mode == "plagiarism" else item_data.get("ai_score")
            if score is None:
                score = paragraph["score"]

            constructed_results.append({
                "index": paragraph["index"],
                "text": paragraph["text"],
                "length": paragraph["length"],
                "score": float(score),
                "label": item_data.get("plagiarism_label") or item_data.get("ai_label") or paragraph["label"],
                "reason": item_data.get("reason") or paragraph["reason"],
                "plagiarism_score": item_data.get("plagiarism_score") if mode == "plagiarism" else item_data.get("plagiarism_score"),
                "plagiarism_label": item_data.get("plagiarism_label"),
            })

        if mode == "plagiarism":
            summary = {
                "overall_score": external_data.get("plagiarism_score") if external_data and external_data.get("plagiarism_score") is not None else plagiarism_aggregate(heuristic_results)["overall_score"],
                "plagiarism_score": external_data.get("plagiarism_score") if external_data else plagiarism_aggregate(heuristic_results)["plagiarism_score"],
                "plagiarism_label": external_data.get("plagiarism_label") if external_data else plagiarism_aggregate(heuristic_results)["plagiarism_label"],
                "ai_label": external_data.get("ai_label") if external_data else None,
            }
        else:
            summary = {
                "overall_score": external_data.get("ai_score") if external_data and external_data.get("ai_score") is not None else aggregate(heuristic_results)["overall_score"],
                "plagiarism_score": external_data.get("plagiarism_score") if external_data else None,
                "ai_label": external_data.get("ai_label") if external_data else None,
                "plagiarism_label": external_data.get("plagiarism_label") if external_data else None,
            }

        return JSONResponse(
            content={
                "results": constructed_results,
                "aggregate": summary,
                "external_source": bool(external_data),
                "external_error": external_error,
            }
        )
    finally:
        cleanup_temp_file(temp_path)


@app.post("/subscribe")
def subscribe(payload: SubscribeRequest, authorization: Optional[str] = Header(None)):
    payment_method = payload.payment_method.lower()
    if payment_method not in ALLOWED_PAYMENT_METHODS:
        raise HTTPException(status_code=400, detail="Unsupported payment method. Use google_pay or phonepe.")

    if payment_method == "phonepe" and not payload.phone_number:
        raise HTTPException(status_code=400, detail="PhonePe checkout requires a phone number.")

    if not authorization:
        raise HTTPException(status_code=401, detail="Sign in before subscribing to a plan.")

    token = authorization.replace("Bearer ", "", 1)
    user = find_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please sign in again.")

    username = user.get("username")

    amount = float(os.getenv("SUBSCRIPTION_AMOUNT", "499"))
    receipt = f"sub-{int(time.time())}"
    checkout = create_razorpay_order(amount=amount, receipt=receipt)
    provider = "razorpay" if checkout else "demo"

    event = create_payment_event(
        plan=payload.plan,
        payment_method=payment_method,
        provider=provider,
        order_id=checkout.get("id") if checkout else receipt,
        phone_number=payload.phone_number,
        username=username,
    )

    # Mark the user's subscription as pending until payment is confirmed
    # (via Razorpay success callback, or admin confirmation for manual UPI payments).
    set_user_subscription(username, {
        "status": "pending",
        "plan": payload.plan,
        "payment_event_id": event["id"],
    })

    if checkout:
        return {
            "status": "success",
            "provider": "razorpay",
            "message": f"Subscription request received for {payload.plan} plan using {payment_method}. Complete checkout to activate your plan.",
            "plan": payload.plan,
            "payment_method": payment_method,
            "phone_number": payload.phone_number,
            "payment_event_id": event["id"],
            "checkout": {
                "key": os.getenv("RAZORPAY_KEY_ID"),
                "order_id": checkout.get("id"),
                "amount": checkout.get("amount"),
                "currency": checkout.get("currency"),
                "receipt": checkout.get("receipt"),
            },
        }

    return {
        "status": "success",
        "provider": "demo",
        "message": f"Subscription request received for {payload.plan} plan using {payment_method}. Pay via the UPI ID shown, then wait for confirmation.",
        "plan": payload.plan,
        "payment_method": payment_method,
        "phone_number": payload.phone_number,
        "payment_event_id": event["id"],
    }


@app.get("/")
def health_check():
    return {"status": "ok", "message": "AI Plag Analyzer backend is running."}


@app.post("/download-report", response_class=StreamingResponse)
def download_report(payload: Dict[str, Any]):

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail="Invalid request body"
        )

    try:
        print("Generating PDF...")

        # Generate PDF
        pdf_bytes = generate_report_pdf(payload)

        # Make absolutely sure we received bytes
        if not isinstance(pdf_bytes, bytes):
            raise Exception(
                f"PDF generator returned {type(pdf_bytes).__name__}, not bytes"
            )

        if len(pdf_bytes) == 0:
            raise Exception("PDF generator returned empty bytes")

        # Check PDF signature
        if not pdf_bytes.startswith(b"%PDF"):
            print("FIRST 100 BYTES:", repr(pdf_bytes[:100]))
            raise Exception(
                "Generated output is NOT a valid PDF. Missing %PDF header."
            )

        print(f"PDF SUCCESS - {len(pdf_bytes)} bytes")

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": 'attachment; filename="ai_plag_report.pdf"',
                "Content-Length": str(len(pdf_bytes)),
            }
        )

    except Exception as exc:

        print("====================================")
        print("PDF GENERATION ERROR")
        print(repr(exc))
        print("====================================")

        raise HTTPException(
            status_code=500,
            detail=f"PDF generation failed: {str(exc)}"
        )

if __name__ == '__main__':
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
