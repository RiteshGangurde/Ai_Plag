import os
import json
import time
import uuid
import hmac
import hashlib
import secrets
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from analyze_docx import (
    analyze,
    aggregate,
    load_paragraphs,
    plagiarism_analyze,
    plagiarism_aggregate,
)

from report_generator import generate_report_pdf


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

app = FastAPI(
    title="AI Plag Analyzer",
    description="AI plagiarism detector with login and Razorpay subscription.",
)

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "").strip()
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "").strip()

FRONTEND_URL = os.getenv("FRONTEND_URL", "*")

try:
    SUBSCRIPTION_AMOUNT = int(
        float(os.getenv("SUBSCRIPTION_AMOUNT", "499"))
    )
except ValueError:
    SUBSCRIPTION_AMOUNT = 499

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

ANALYSIS_API_URL = os.getenv("ANALYSIS_API_URL", "").strip()
ANALYSIS_API_KEY = os.getenv("ANALYSIS_API_KEY", "").strip()
ANALYSIS_API_EXTRA = os.getenv("ANALYSIS_API_EXTRA", "").strip()


# ============================================================
# SIMPLE IN-MEMORY STORAGE
# ============================================================
#
# NO MONGODB
#
# IMPORTANT:
# Railway restart/redeploy will clear this data.
# For your current MVP this keeps the backend extremely simple.
#
# If you later need permanent users/subscriptions, we can add
# a database after the payment flow is completely stable.
# ============================================================

USERS: Dict[str, Dict[str, Any]] = {}

TOKENS: Dict[str, str] = {}

PAYMENTS: Dict[str, Dict[str, Any]] = {}

ADMIN_TOKENS: Dict[str, int] = {}


# ============================================================
# CORS
# ============================================================

if FRONTEND_URL == "*":

    allowed_origins = ["*"]
    allow_credentials = False

else:

    allowed_origins = [
        item.strip()
        for item in FRONTEND_URL.split(",")
        if item.strip()
    ]

    allow_credentials = True


app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_error_logger(request: Request, exc: RequestValidationError):
    # Logs the exact raw body + which fields FastAPI considered missing/invalid,
    # so a 422 can be diagnosed from the Railway logs instead of guessing.
    try:
        raw_body = await request.body()
    except Exception:
        raw_body = b""
    print("====================================")
    print(f"422 VALIDATION ERROR on {request.method} {request.url.path}")
    print("Raw body received:", raw_body.decode("utf-8", errors="replace"))
    print("Field errors:", json.dumps(exc.errors(), default=str))
    print("====================================")
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


# ============================================================
# REQUEST MODELS
# ============================================================

class SignupRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


class SigninRequest(BaseModel):
    username: str
    password: str


class SubscribeRequest(BaseModel):
    plan: str = "pro"
    payment_method: str = "razorpay"
    phone_number: Optional[str] = None


class PaymentConfirmRequest(BaseModel):
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str


class AdminLoginRequest(BaseModel):
    username: str
    password: str


# ============================================================
# PASSWORD HASHING
# ============================================================

def hash_password(password: str) -> str:

    salt = secrets.token_bytes(16)

    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        200_000,
    )

    return (
        "pbkdf2_sha256$200000$"
        + salt.hex()
        + "$"
        + derived.hex()
    )


def verify_password(
    password: str,
    stored_hash: str,
) -> bool:

    try:

        parts = stored_hash.split("$")

        if len(parts) != 4:
            return False

        algorithm = parts[0]
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected = bytes.fromhex(parts[3])

        if algorithm != "pbkdf2_sha256":
            return False

        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        )

        return hmac.compare_digest(
            actual,
            expected,
        )

    except Exception:

        return False


# ============================================================
# TOKEN FUNCTIONS
# ============================================================

def create_token() -> str:

    return secrets.token_urlsafe(32)


def extract_bearer_token(
    authorization: Optional[str],
) -> Optional[str]:

    if not authorization:
        return None

    token = authorization.strip()

    if token.lower().startswith("bearer "):

        token = token[7:].strip()

    return token or None


def get_user_from_token(
    token: Optional[str],
) -> Optional[Dict[str, Any]]:

    if not token:
        return None

    username = TOKENS.get(token)

    if not username:
        return None

    return USERS.get(username)


def get_current_user(
    authorization: Optional[str],
) -> Dict[str, Any]:

    token = extract_bearer_token(
        authorization
    )

    user = get_user_from_token(token)

    if not user:

        raise HTTPException(
            status_code=401,
            detail="Please sign in again.",
        )

    return user


def get_active_user(
    authorization: Optional[str],
) -> Dict[str, Any]:

    user = get_current_user(
        authorization
    )

    subscription = (
        user.get("subscription")
        or {}
    )

    if subscription.get("status") != "active":

        raise HTTPException(
            status_code=402,
            detail=(
                "Active subscription required. "
                "Please complete payment first."
            ),
        )

    return user


# ============================================================
# USER SERIALIZATION
# ============================================================

def serialize_user(
    user: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:

    if not user:
        return None

    subscription = (
        user.get("subscription")
        or {
            "status": "inactive",
            "plan": None,
        }
    )

    return {

        "username": user.get("username"),

        "email": user.get("email"),

        "created_at": user.get("created_at"),

        "subscription": subscription,

    }


# ============================================================
# RAZORPAY ORDER CREATION
# ============================================================

def create_razorpay_order(
    amount_rupees: int,
    receipt: str,
) -> Dict[str, Any]:

    if not RAZORPAY_KEY_ID:

        raise HTTPException(
            status_code=500,
            detail=(
                "RAZORPAY_KEY_ID is missing "
                "from Railway environment variables."
            ),
        )

    if not RAZORPAY_KEY_SECRET:

        raise HTTPException(
            status_code=500,
            detail=(
                "RAZORPAY_KEY_SECRET is missing "
                "from Railway environment variables."
            ),
        )

    payload = {
        "amount": int(amount_rupees * 100),
        "currency": "INR",
        "receipt": receipt,
    }

    try:

        response = requests.post(
            "https://api.razorpay.com/v1/orders",
            auth=(
                RAZORPAY_KEY_ID,
                RAZORPAY_KEY_SECRET,
            ),
            json=payload,
            timeout=20,
        )

        response.raise_for_status()

        data = response.json()

        if not data.get("id"):

            raise HTTPException(
                status_code=502,
                detail="Razorpay did not return an order ID.",
            )

        return data

    except requests.HTTPError as exc:

        try:
            detail = response.json()
        except Exception:
            detail = response.text

        print(
            "===================================="
        )
        print("RAZORPAY ORDER ERROR")
        print(detail)
        print(
            "===================================="
        )

        raise HTTPException(
            status_code=502,
            detail=f"Razorpay order creation failed: {detail}",
        ) from exc

    except requests.RequestException as exc:

        print(
            "RAZORPAY CONNECTION ERROR:",
            repr(exc),
        )

        raise HTTPException(
            status_code=502,
            detail="Could not connect to Razorpay.",
        ) from exc


# ============================================================
# RAZORPAY SIGNATURE VERIFICATION
# ============================================================

def verify_razorpay_signature(
    order_id: str,
    payment_id: str,
    signature: str,
) -> bool:

    if not RAZORPAY_KEY_SECRET:
        return False

    message = f"{order_id}|{payment_id}"

    expected_signature = hmac.new(
        RAZORPAY_KEY_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(
        expected_signature,
        signature,
    )


# ============================================================
# SIGNUP
# ============================================================

@app.post("/signup")
def signup(
    payload: SignupRequest,
):

    username = payload.username.strip()

    password = payload.password

    if len(username) < 3:

        raise HTTPException(
            status_code=400,
            detail="Username must contain at least 3 characters.",
        )

    if len(password) < 6:

        raise HTTPException(
            status_code=400,
            detail="Password must contain at least 6 characters.",
        )

    if username in USERS:

        raise HTTPException(
            status_code=400,
            detail="User already exists.",
        )

    token = create_token()

    USERS[username] = {

        "username": username,

        "email": payload.email,

        "password_hash": hash_password(password),

        "token": token,

        "created_at": int(time.time()),

        "subscription": {
            "status": "inactive",
            "plan": None,
        },

    }

    TOKENS[token] = username

    return {

        "status": "success",

        "message": "Account created successfully.",

        "token": token,

        "next": "payment",

        "user": serialize_user(
            USERS[username]
        ),

    }


# ============================================================
# SIGNIN
# ============================================================

@app.post("/signin")
def signin(
    payload: SigninRequest,
):

    username = payload.username.strip()

    user = USERS.get(username)

    if not user:

        raise HTTPException(
            status_code=401,
            detail="Invalid username or password.",
        )

    if not verify_password(
        payload.password,
        user["password_hash"],
    ):

        raise HTTPException(
            status_code=401,
            detail="Invalid username or password.",
        )

    old_token = user.get("token")

    if old_token:

        TOKENS.pop(
            old_token,
            None,
        )

    token = create_token()

    user["token"] = token

    TOKENS[token] = username

    subscription = (
        user.get("subscription")
        or {}
    )

    if subscription.get("status") == "active":

        next_page = "dashboard"

    else:

        next_page = "payment"

    return {

        "status": "success",

        "message": "Login successful.",

        "token": token,

        "username": username,

        "next": next_page,

        "user": serialize_user(user),

    }


# ============================================================
# LOGOUT
# ============================================================

@app.post("/logout")
def logout(
    authorization: Optional[str] = Header(None),
):

    token = extract_bearer_token(
        authorization
    )

    if token:

        TOKENS.pop(
            token,
            None,
        )

    return {

        "status": "success",

        "message": "Logged out successfully.",

    }


# ============================================================
# PROFILE
# ============================================================

@app.get("/profile")
def profile(
    authorization: Optional[str] = Header(None),
):

    user = get_current_user(
        authorization
    )

    return {

        "status": "success",

        "user": serialize_user(user),

    }


# ============================================================
# SUBSCRIBE
# ============================================================

@app.post("/subscribe")
def subscribe(
    payload: SubscribeRequest,
    authorization: Optional[str] = Header(None),
):

    user = get_current_user(
        authorization
    )

    subscription = (
        user.get("subscription")
        or {}
    )

    # If already paid, go straight to dashboard.
    if subscription.get("status") == "active":

        return {

            "status": "already_active",

            "message": "Your subscription is already active.",

            "next": "dashboard",

            "user": serialize_user(user),

        }

    plan = (
        payload.plan.strip()
        or "pro"
    )

    receipt = (
        f"sub-"
        f"{user['username']}-"
        f"{int(time.time())}-"
        f"{uuid.uuid4().hex[:8]}"
    )

    checkout = create_razorpay_order(
        amount_rupees=SUBSCRIPTION_AMOUNT,
        receipt=receipt,
    )

    order_id = checkout["id"]

    # Store payment using Razorpay order ID.
    PAYMENTS[order_id] = {

        "order_id": order_id,

        "username": user["username"],

        "plan": plan,

        "amount": SUBSCRIPTION_AMOUNT,

        "status": "created",

        "created_at": int(time.time()),

    }

    # Mark subscription as pending.
    user["subscription"] = {

        "status": "pending",

        "plan": plan,

        "order_id": order_id,

    }

    # Store pending payment.
    user["pending_payment"] = {

        "order_id": order_id,

        "plan": plan,

        "amount": SUBSCRIPTION_AMOUNT,

        "created_at": int(time.time()),

    }

    print(
        "===================================="
    )

    print(
        "RAZORPAY ORDER CREATED"
    )

    print(
        "Username:",
        user["username"]
    )

    print(
        "Order ID:",
        order_id
    )

    print(
        "Amount:",
        checkout["amount"]
    )

    print(
        "===================================="
    )

    return {

        "status": "success",

        "provider": "razorpay",

        "message": (
            "Razorpay checkout created successfully."
        ),

        "username": user["username"],

        "email": user.get("email"),

        "plan": plan,

        # IMPORTANT:
        # No payment_event_id anymore.
        "checkout": {

            "key": RAZORPAY_KEY_ID,

            "order_id": order_id,

            "amount": checkout["amount"],

            "currency": checkout["currency"],

            "receipt": checkout.get("receipt"),

        },

    }


# ============================================================
# PAYMENT CONFIRM
# ============================================================

@app.post("/payment-confirm")
def payment_confirm(
    payload: PaymentConfirmRequest,
    authorization: Optional[str] = Header(None),
):

    user = get_current_user(
        authorization
    )

    payment_id = (
        payload.razorpay_payment_id
    )

    order_id = (
        payload.razorpay_order_id
    )

    signature = (
        payload.razorpay_signature
    )

    print(
        "===================================="
    )

    print(
        "PAYMENT CONFIRM REQUEST"
    )

    print(
        "Username:",
        user["username"]
    )

    print(
        "Payment ID:",
        payment_id
    )

    print(
        "Order ID:",
        order_id
    )

    print(
        "Signature received:",
        bool(signature)
    )

    print(
        "===================================="
    )

    pending = (
        user.get("pending_payment")
    )

    if not pending:

        raise HTTPException(
            status_code=400,
            detail=(
                "No pending payment was found "
                "for this account."
            ),
        )

    # Make sure order belongs to this user's
    # pending payment.
    if pending.get("order_id") != order_id:

        raise HTTPException(
            status_code=400,
            detail=(
                "This payment does not match "
                "the pending order."
            ),
        )

    payment = PAYMENTS.get(order_id)

    if not payment:

        raise HTTPException(
            status_code=404,
            detail="Payment order not found.",
        )

    if payment.get("username") != user["username"]:

        raise HTTPException(
            status_code=403,
            detail=(
                "This payment does not belong "
                "to this account."
            ),
        )

    # ========================================================
    # VERIFY RAZORPAY SIGNATURE
    # ========================================================

    valid = verify_razorpay_signature(
        order_id=order_id,
        payment_id=payment_id,
        signature=signature,
    )

    if not valid:

        payment["status"] = "verification_failed"

        print(
            "RAZORPAY SIGNATURE VERIFICATION FAILED"
        )

        raise HTTPException(
            status_code=400,
            detail=(
                "Razorpay payment verification failed."
            ),
        )

    # ========================================================
    # PAYMENT VERIFIED
    # ========================================================

    plan = (
        pending.get("plan")
        or "pro"
    )

    activation_time = int(
        time.time()
    )

    user["subscription"] = {

        "status": "active",

        "plan": plan,

        "payment_id": payment_id,

        "order_id": order_id,

        "activated_at": activation_time,

    }

    payment["status"] = "completed"

    payment["payment_id"] = payment_id

    payment["signature_verified"] = True

    payment["confirmed_at"] = activation_time

    # Remove pending payment.
    user.pop(
        "pending_payment",
        None,
    )

    print(
        "===================================="
    )

    print(
        "PAYMENT VERIFIED SUCCESSFULLY"
    )

    print(
        "Username:",
        user["username"]
    )

    print(
        "Plan:",
        plan
    )

    print(
        "Payment ID:",
        payment_id
    )

    print(
        "Order ID:",
        order_id
    )

    print(
        "SUBSCRIPTION ACTIVE"
    )

    print(
        "===================================="
    )

    # IMPORTANT:
    # Frontend can immediately redirect
    # to dashboard.
    return {

        "status": "success",

        "message": (
            "Payment verified successfully. "
            "Your subscription is active."
        ),

        "next": "dashboard",

        "payment_id": payment_id,

        "order_id": order_id,

        "subscription": user["subscription"],

        "user": serialize_user(user),

    }


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.post("/admin/login")
def admin_login(
    payload: AdminLoginRequest,
):

    if (
        payload.username != ADMIN_USERNAME
        or
        payload.password != ADMIN_PASSWORD
    ):

        raise HTTPException(
            status_code=401,
            detail="Invalid admin credentials.",
        )

    token = create_token()

    ADMIN_TOKENS[token] = int(
        time.time()
    )

    return {

        "status": "success",

        "token": token,

        "message": "Admin login successful.",

    }


# ============================================================
# ADMIN AUTH
# ============================================================

def admin_authorized(
    authorization: Optional[str],
) -> bool:

    token = extract_bearer_token(
        authorization
    )

    return bool(
        token
        and
        token in ADMIN_TOKENS
    )


# ============================================================
# ADMIN PAYMENTS
# ============================================================

@app.get("/admin/payments")
def admin_payments(
    authorization: Optional[str] = Header(None),
):

    if not admin_authorized(
        authorization
    ):

        raise HTTPException(
            status_code=401,
            detail="Unauthorized.",
        )

    return {

        "status": "success",

        "payments": list(
            PAYMENTS.values()
        ),

        "users": [

            {

                "username":
                    user["username"],

                "email":
                    user.get("email"),

                "subscription":
                    user.get("subscription"),

            }

            for user in USERS.values()

        ],

    }


# ============================================================
# EXTERNAL AI API
# ============================================================

def extract_value(
    response: Dict[str, Any],
    paths: List[str],
) -> Optional[Any]:

    for path in paths:

        parts = path.split(".")

        current = response

        for part in parts:

            if (
                isinstance(current, dict)
                and
                part in current
            ):

                current = current[part]

            else:

                break

        else:

            return current

    return None


def normalize_external_response(
    response: Dict[str, Any],
) -> Dict[str, Any]:

    if not isinstance(
        response,
        dict,
    ):

        return {}

    ai_score = extract_value(
        response,
        [
            "ai_score",
            "ai.score",
            "score",
            "ai_percentage",
            "ai.percent",
        ],
    )

    plag_score = extract_value(
        response,
        [
            "plagiarism_score",
            "plagiarism.score",
            "plag.score",
            "plagiarism_percentage",
        ],
    )

    ai_label = extract_value(
        response,
        [
            "ai_label",
            "ai.label",
            "label",
        ],
    )

    plag_label = extract_value(
        response,
        [
            "plagiarism_label",
            "plagiarism.label",
            "plag.label",
        ],
    )

    results = []

    raw_items = extract_value(
        response,
        [
            "paragraphs",
            "results",
            "items",
        ],
    ) or []

    if isinstance(
        raw_items,
        list,
    ):

        for item in raw_items:

            if not isinstance(
                item,
                dict,
            ):

                continue

            results.append({

                "ai_score":
                    extract_value(
                        item,
                        [
                            "ai_score",
                            "ai.score",
                            "score",
                        ],
                    ),

                "plagiarism_score":
                    extract_value(
                        item,
                        [
                            "plagiarism_score",
                            "plagiarism.score",
                            "plag.score",
                        ],
                    ),

                "ai_label":
                    extract_value(
                        item,
                        [
                            "ai_label",
                            "ai.label",
                            "label",
                        ],
                    ),

                "plagiarism_label":
                    extract_value(
                        item,
                        [
                            "plagiarism_label",
                            "plagiarism.label",
                        ],
                    ),

                "reason":
                    extract_value(
                        item,
                        [
                            "reason",
                            "explanation",
                            "details",
                        ],
                    ),

            })

    def safe_float(value):

        if value is None:
            return None

        try:

            return float(value)

        except (
            ValueError,
            TypeError,
        ):

            return None

    return {

        "ai_score":
            safe_float(ai_score),

        "plagiarism_score":
            safe_float(plag_score),

        "ai_label":
            ai_label,

        "plagiarism_label":
            plag_label,

        "items":
            results,

    }


def send_text_to_external_api(
    text: str,
) -> Optional[Dict[str, Any]]:

    if not ANALYSIS_API_URL:

        return None

    headers = {

        "Content-Type":
            "application/json",

    }

    if ANALYSIS_API_KEY:

        headers["Authorization"] = (
            f"Bearer {ANALYSIS_API_KEY}"
        )

    body = {

        "text":
            text,

        "features": [
            "plagiarism",
            "ai_detection",
        ],

    }

    if ANALYSIS_API_EXTRA:

        try:

            extra = json.loads(
                ANALYSIS_API_EXTRA
            )

            if isinstance(
                extra,
                dict,
            ):

                body.update(extra)

        except json.JSONDecodeError:

            print(
                "WARNING: ANALYSIS_API_EXTRA "
                "is not valid JSON."
            )

    response = requests.post(

        ANALYSIS_API_URL,

        json=body,

        headers=headers,

        timeout=60,

    )

    response.raise_for_status()

    return response.json()


# ============================================================
# ANALYZE INFO
# ============================================================

@app.get("/analyze")
def analyze_info():

    return {

        "status": "ok",

        "message": (
            "POST a .docx file to /analyze."
        ),

    }


# ============================================================
# ANALYZE DOCUMENT
# ============================================================

@app.post("/analyze")
async def analyze_document(

    file: UploadFile = File(...),

    mode: str = Form("ai"),

    authorization: Optional[str] =
        Header(None),

):

    # PAYMENT GATE
    user = get_active_user(
        authorization
    )

    if not file.filename:

        raise HTTPException(
            status_code=400,
            detail="No file was selected.",
        )

    if not file.filename.lower().endswith(
        ".docx"
    ):

        raise HTTPException(
            status_code=400,
            detail="Only .docx files are supported.",
        )

    if mode not in {
        "ai",
        "plagiarism",
    }:

        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid analysis mode. "
                "Use ai or plagiarism."
            ),
        )

    file_bytes = await file.read()

    if not file_bytes:

        raise HTTPException(
            status_code=400,
            detail="The uploaded file is empty.",
        )

    temp_path = None

    try:

        temp_file = NamedTemporaryFile(
            delete=False,
            suffix=".docx",
        )

        temp_file.write(
            file_bytes
        )

        temp_file.flush()

        temp_file.close()

        temp_path = temp_file.name

        paragraphs = load_paragraphs(
            temp_path
        )

        if not paragraphs:

            raise HTTPException(
                status_code=400,
                detail=(
                    "The uploaded document "
                    "contains no readable paragraphs."
                ),
            )

        document_text = "\n\n".join(

            paragraph["text"]

            for paragraph in paragraphs

        )

        external_data = None

        external_error = None

        try:

            raw_response = (
                send_text_to_external_api(
                    document_text
                )
            )

            if raw_response:

                external_data = (
                    normalize_external_response(
                        raw_response
                    )
                )

        except Exception as exc:

            external_error = str(exc)

            print(
                "EXTERNAL API ERROR:",
                repr(exc),
            )

        # Local fallback.
        if mode == "plagiarism":

            heuristic_results = (
                plagiarism_analyze(
                    paragraphs
                )
            )

        else:

            heuristic_results = analyze(
                paragraphs,
                use_openai=False,
            )

        constructed_results = []

        external_items = (

            external_data.get(
                "items",
                []
            )

            if external_data

            else []

        )

        for idx, paragraph in enumerate(
            heuristic_results
        ):

            item_data = (

                external_items[idx]

                if idx < len(
                    external_items
                )

                else {}

            )

            if mode == "plagiarism":

                score = item_data.get(
                    "plagiarism_score"
                )

            else:

                score = item_data.get(
                    "ai_score"
                )

            if score is None:

                score = paragraph["score"]

            constructed_results.append({

                "index":
                    paragraph["index"],

                "text":
                    paragraph["text"],

                "length":
                    paragraph["length"],

                "score":
                    float(score),

                "label": (

                    item_data.get(
                        "plagiarism_label"
                    )

                    or

                    item_data.get(
                        "ai_label"
                    )

                    or

                    paragraph["label"]

                ),

                "reason": (

                    item_data.get(
                        "reason"
                    )

                    or

                    paragraph["reason"]

                ),

                "plagiarism_score":
                    item_data.get(
                        "plagiarism_score"
                    ),

                "plagiarism_label":
                    item_data.get(
                        "plagiarism_label"
                    ),

            })

        if mode == "plagiarism":

            local_summary = (
                plagiarism_aggregate(
                    heuristic_results
                )
            )

            summary = {

                "overall_score": (

                    external_data.get(
                        "plagiarism_score"
                    )

                    if (
                        external_data
                        and
                        external_data.get(
                            "plagiarism_score"
                        ) is not None
                    )

                    else

                    local_summary[
                        "overall_score"
                    ]

                ),

                "plagiarism_score": (

                    external_data.get(
                        "plagiarism_score"
                    )

                    if (
                        external_data
                        and
                        external_data.get(
                            "plagiarism_score"
                        ) is not None
                    )

                    else

                    local_summary[
                        "plagiarism_score"
                    ]

                ),

                "plagiarism_label": (

                    external_data.get(
                        "plagiarism_label"
                    )

                    if external_data

                    else

                    local_summary[
                        "plagiarism_label"
                    ]

                ),

                "ai_label": (

                    external_data.get(
                        "ai_label"
                    )

                    if external_data

                    else None

                ),

            }

        else:

            local_summary = aggregate(
                heuristic_results
            )

            summary = {

                "overall_score": (

                    external_data.get(
                        "ai_score"
                    )

                    if (
                        external_data
                        and
                        external_data.get(
                            "ai_score"
                        ) is not None
                    )

                    else

                    local_summary[
                        "overall_score"
                    ]

                ),

                "plagiarism_score": (

                    external_data.get(
                        "plagiarism_score"
                    )

                    if external_data

                    else None

                ),

                "ai_label": (

                    external_data.get(
                        "ai_label"
                    )

                    if external_data

                    else None

                ),

                "plagiarism_label": (

                    external_data.get(
                        "plagiarism_label"
                    )

                    if external_data

                    else None

                ),

            }

        return JSONResponse(

            content={

                "status":
                    "success",

                "username":
                    user["username"],

                "results":
                    constructed_results,

                "aggregate":
                    summary,

                "external_source":
                    bool(external_data),

                "external_error":
                    external_error,

            }

        )

    finally:

        if temp_path:

            try:

                os.remove(
                    temp_path
                )

            except OSError:

                pass


# ============================================================
# DOWNLOAD PDF
# ============================================================

@app.post("/download-report")
def download_report(

    payload: Dict[str, Any],

    authorization: Optional[str] =
        Header(None),

):

    # PAYMENT GATE
    get_active_user(
        authorization
    )

    if not isinstance(
        payload,
        dict,
    ):

        raise HTTPException(
            status_code=400,
            detail="Invalid request body.",
        )

    try:

        print(
            "Generating PDF..."
        )

        pdf_bytes = (
            generate_report_pdf(
                payload
            )
        )

        if not isinstance(
            pdf_bytes,
            bytes,
        ):

            raise Exception(
                "PDF generator did not "
                "return bytes."
            )

        if not pdf_bytes:

            raise Exception(
                "PDF generator returned "
                "empty bytes."
            )

        if not pdf_bytes.startswith(
            b"%PDF"
        ):

            raise Exception(
                "Generated output is "
                "not a valid PDF."
            )

        print(
            f"PDF SUCCESS - "
            f"{len(pdf_bytes)} bytes"
        )

        return Response(

            content=pdf_bytes,

            media_type="application/pdf",

            headers={

                "Content-Disposition":
                    (
                        'attachment; '
                        'filename='
                        '"ai_plag_report.pdf"'
                    ),

                "Content-Length":
                    str(
                        len(pdf_bytes)
                    ),

            },

        )

    except HTTPException:

        raise

    except Exception as exc:

        print(
            "PDF GENERATION ERROR:",
            repr(exc),
        )

        raise HTTPException(

            status_code=500,

            detail=(
                "PDF generation failed: "
                f"{str(exc)}"
            ),

        )


# ============================================================
# HEALTH
# ============================================================

@app.get("/")
def health_check():

    return {

        "status":
            "ok",

        "message":
            "AI Plag Analyzer backend is running.",

    }


@app.get("/health")
def health():

    return {

        "status":
            "healthy",

        "users":
            len(USERS),

        "payments":
            len(PAYMENTS),

        "razorpay_configured":
            bool(
                RAZORPAY_KEY_ID
                and
                RAZORPAY_KEY_SECRET
            ),

    }


# ============================================================
# RUN SERVER
# ============================================================

if __name__ == "__main__":

    import uvicorn

    port = int(
        os.getenv(
            "PORT",
            "8000"
        )
    )

    uvicorn.run(

        "server:app",

        host="0.0.0.0",

        port=port,

        reload=False,

    )

