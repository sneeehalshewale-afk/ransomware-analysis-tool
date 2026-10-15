
import os
import sys
from pathlib import Path

import pandas as pd
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# ============================================================
# PATH SETUP
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

# Allows:
# from src.predict import predict_ransomware
sys.path.insert(0, str(BASE_DIR))

from src.predict import predict_ransomware


# ============================================================
# CONFIGURATION
# ============================================================

# Your FastAPI backend
BACKEND_URL = "http://127.0.0.1:8000"

# Device API key used by the ML service to communicate
# with the backend.
ML_API_KEY = "920889df7d5444185de5e9f1cd223f3"

HEADERS = {
    "X-Device-Key": ML_API_KEY,
    "Content-Type": "application/json",
}

# Processed ML dataset
DATA_DIR = BASE_DIR / "data" / "processed"

X_TEST_FILE = DATA_DIR / "X_test.csv"
Y_TEST_FILE = DATA_DIR / "y_test.csv"


# ============================================================
# FASTAPI APPLICATION
# ============================================================

app = FastAPI(
    title="ML Behavioral Analysis Service",
    description=(
        "ML service for ransomware behavioral detection. "
        "Connects the ML prediction engine and SHAP explanations "
        "to the FastAPI ransomware backend."
    ),
    version="1.0.0",
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# SHAP CONVERSION
# ============================================================

def shap_dict_from_result(result):
    """
    Converts:

    top_contributing_features = [
        {
            "feature_name": "...",
            "shap_impact": ...
        }
    ]

    into:

    {
        "feature_name": shap_value
    }

    which is accepted by the backend alert schema.
    """

    features = result.get(
        "top_contributing_features",
        []
    )

    return {
        feature["feature_name"]:
        round(float(feature["shap_impact"]), 4)

        for feature in features
        if "feature_name" in feature
        and "shap_impact" in feature
    }


# ============================================================
# SEND ML RESULT TO BACKEND
# ============================================================

def forward_to_backend(reason, base_risk, result):

    ml_score = float(
        result.get("risk_score", 0)
    )

    shap_explanation = shap_dict_from_result(result)

    # --------------------------------------------------------
    # 1. CREATE EVENT
    # --------------------------------------------------------

    event_payload = {
        "event_type": "ml_analysis",
        "file_path": None,
        "features": None,
    }

    try:

        event_response = requests.post(
            f"{BACKEND_URL}/events",
            json=event_payload,
            headers=HEADERS,
            timeout=5,
        )

    except requests.RequestException as exc:

        raise HTTPException(
            status_code=503,
            detail=f"Backend event connection failed: {exc}",
        )


    if event_response.status_code not in (200, 201):

        raise HTTPException(
            status_code=event_response.status_code,
            detail=(
                "Backend rejected event: "
                f"{event_response.text}"
            ),
        )


    event_data = event_response.json()

    event_id = event_data.get("id")


    # --------------------------------------------------------
    # 2. CREATE ALERT
    # --------------------------------------------------------

    alert_payload = {
        "event_id": event_id,
        "reason": reason,
        "base_risk": float(base_risk),
        "ml_score": ml_score,
        "shap_explanation": shap_explanation,
    }


    try:

        alert_response = requests.post(
            f"{BACKEND_URL}/alerts",
            json=alert_payload,
            headers=HEADERS,
            timeout=5,
        )

    except requests.RequestException as exc:

        raise HTTPException(
            status_code=503,
            detail=f"Backend alert connection failed: {exc}",
        )


    if alert_response.status_code not in (200, 201):

        raise HTTPException(
            status_code=alert_response.status_code,
            detail=(
                "Backend rejected alert: "
                f"{alert_response.text}"
            ),
        )


    return alert_response.json()


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health", tags=["Health"])
def health():

    return {
        "status": "ok",
        "service": "ML Behavioral Analysis Service",
        "backend": BACKEND_URL,
    }


# ============================================================
# TEST BACKEND CONNECTION
# ============================================================

@app.get("/test/backend", tags=["Connection"])
def test_backend():

    try:

        response = requests.get(
            f"{BACKEND_URL}/",
            timeout=5,
        )

        return {
            "ml_service": "ok",
            "backend_status_code": response.status_code,
            "backend_response": response.json(),
            "connected": True,
        }

    except Exception as exc:

        return {
            "ml_service": "ok",
            "connected": False,
            "error": str(exc),
        }


# ============================================================
# SIMULATE RANSOMWARE
# ============================================================

@app.post(
    "/simulate/ransomware",
    tags=["ML Testing"],
)
def simulate_ransomware():

    if not X_TEST_FILE.exists():

        raise HTTPException(
            status_code=404,
            detail=f"Missing file: {X_TEST_FILE}",
        )

    if not Y_TEST_FILE.exists():

        raise HTTPException(
            status_code=404,
            detail=f"Missing file: {Y_TEST_FILE}",
        )


    X_test = pd.read_csv(X_TEST_FILE)
    y_test = pd.read_csv(Y_TEST_FILE)


    label_col = y_test.columns[0]


    ransomware_indices = y_test[
        y_test[label_col] == 1
    ].index


    if len(ransomware_indices) == 0:

        raise HTTPException(
            status_code=404,
            detail="No ransomware samples found in y_test.csv",
        )


    index = ransomware_indices[0]

    sample = X_test.iloc[index].to_dict()


    # ML prediction
    result = predict_ransomware(sample)


    # Send prediction to backend
    alert = forward_to_backend(
        reason=(
            "ML Behavioral Analysis - "
            "Ransomware-like process/registry pattern"
        ),
        base_risk=60,
        result=result,
    )


    return {
        "type": "ransomware",
        "ml_result": result,
        "backend_alert": alert,
        "backend_connected": True,
    }


# ============================================================
# SIMULATE BENIGN
# ============================================================

@app.post(
    "/simulate/benign",
    tags=["ML Testing"],
)
def simulate_benign():

    if not X_TEST_FILE.exists():

        raise HTTPException(
            status_code=404,
            detail=f"Missing file: {X_TEST_FILE}",
        )

    if not Y_TEST_FILE.exists():

        raise HTTPException(
            status_code=404,
            detail=f"Missing file: {Y_TEST_FILE}",
        )


    X_test = pd.read_csv(X_TEST_FILE)
    y_test = pd.read_csv(Y_TEST_FILE)


    label_col = y_test.columns[0]


    benign_indices = y_test[
        y_test[label_col] == 0
    ].index


    if len(benign_indices) == 0:

        raise HTTPException(
            status_code=404,
            detail="No benign samples found in y_test.csv",
        )


    index = benign_indices[0]

    sample = X_test.iloc[index].to_dict()


    # ML prediction
    result = predict_ransomware(sample)


    # Send prediction to backend
    alert = forward_to_backend(
        reason=(
            "ML Behavioral Analysis - "
            "routine activity pattern"
        ),
        base_risk=0,
        result=result,
    )


    return {
        "type": "benign",
        "ml_result": result,
        "backend_alert": alert,
        "backend_connected": True,
    }


# ============================================================
# LIVE FEATURE SCORING
# ============================================================

@app.post(
    "/score",
    tags=["ML Testing"],
)
def score_features(features: dict):

    if not features:

        raise HTTPException(
            status_code=400,
            detail="Feature dictionary cannot be empty.",
        )


    # Run ML model
    result = predict_ransomware(features)


    ml_score = float(
        result.get("risk_score", 0)
    )


    # Ignore very low-risk activity
    if ml_score < 10:

        return {
            "ml_result": result,
            "backend_alert": None,
            "forwarded": False,
            "reason": "Risk score below alert threshold",
        }


    # Send significant result to backend
    alert = forward_to_backend(
        reason=(
            "ML Behavioral Analysis - "
            "live telemetry scan"
        ),
        base_risk=0,
        result=result,
    )


    return {
        "ml_result": result,
        "backend_alert": alert,
        "forwarded": True,
    }


# ============================================================
# START ML SERVER
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8020,
    )
