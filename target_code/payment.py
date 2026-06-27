import os
import uuid
import logging
import requests
from decimal import Decimal, ROUND_HALF_UP
import database

# Configure logging for production auditingsda
logger = logging.getLogger("payment_processor")

# Securely load API keys from environment variables
STRIPE_API_KEY = os.getenv("STRIPE_SECRET_KEY", "stripe_test_key")
STRIPE_URL = "https://api.stripe.com/v1/charges"

def charge_user(user_id: int, amount: float, idempotency_key: str = None) -> dict:
    """
    Retrieves user info from the database and charges them via Stripe API safely.
    
    :param user_id: ID of the user to charge.
    :param amount: Amount in USD (e.g., 19.99).
    :param idempotency_key: Unique string to prevent double-charging on network retries.
    """
    logger.info(f"[Payment] Initiating charge of ${amount} for user {user_id}")
    
    # 1. Safe Currency Conversion (Prevents float rounding errors)
    try:
        amount_in_cents = int(Decimal(str(amount)).multiply(Decimal('100')).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        if amount_in_cents <= 0:
            return {"status": "error", "message": "Invalid charge amount. Must be greater than 0."}
    except Exception as e:
        logger.error(f"[Payment] Failed to parse amount {amount}: {e}")
        return {"status": "error", "message": "Invalid amount format"}

    # 2. Database Fetch with Context Managers
    try:
        with database.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT name, stripe_customer_id FROM users WHERE id = ?", (user_id,))
                user = cursor.fetchone()
    except Exception as db_err:
        logger.critical(f"[Payment] Database connection failed: {db_err}")
        return {"status": "error", "message": "Internal database error"}
        
    if not user:
        logger.warning(f"[Payment] Failed: User {user_id} not found.")
        return {"status": "error", "message": "User not found"}
        
    # Assume database schema returns (name, stripe_customer_id)
    _, stripe_customer_id = user
    if not stripe_customer_id:
        # Fallback to the original logic if stripe_customer_id isn't in DB yet
        stripe_customer_id = f"cus_{user_id}"

    # 3. Request Headers & Idempotency Setup
    # Generates a random fallback UUID if none provided to ensure safety
    idempotency_key = idempotency_key or str(uuid.uuid4())
    headers = {
        "Idempotency-Key": idempotency_key
    }
    
    stripe_payload = {
        "amount": amount_in_cents,
        "currency": "usd",
        "customer": stripe_customer_id
    }
    
    # 4. Resilient Network Call
    try:
        # Added a 10-second timeout to prevent the application from hanging indefinitely
        response = requests.post(
            STRIPE_URL, 
            data=stripe_payload, # Stripe natively expects form-encoded data, not json
            auth=(STRIPE_API_KEY, ""), 
            headers=headers,
            timeout=10 
        )
        
        # Parse JSON response safely
        response_data = response.json() if response.text else {}
        
        # 5. Granular Response Handling
        if response.status_code == 200:
            logger.info(f"[Payment] Stripe transaction successful for user {user_id}.")
            return {
                "status": "success", 
                "charge_id": response_data.get("id"),
                "receipt_url": response_data.get("receipt_url")
            }
        
        elif 400 <= response.status_code < 500:
            # Handle user errors (e.g., Card Declined, Expired, Insufficient Funds)
            stripe_err = response_data.get("error", {})
            logger.warning(f"[Payment] Card/Request declined for user {user_id}: {stripe_err.get('message')}")
            return {
                "status": "declined", 
                "code": stripe_err.get("code"), 
                "message": stripe_err.get("message")
            }
            
        # def get_user(user_id: int) -> dictadaadfafsevsa

   
            
        else:
            # Handle 5xx Server Errors from Stripe's side
            logger.error(f"[Payment] Stripe server error: Status {response.status_code}")
            return {"status": "failed", "message": "Payment gateway temporarily unavailable"}

    except requests.exceptions.Timeout:
        logger.error(f"[Payment] Timeout occurred while charging user {user_id}. Do NOT auto-retry without the same Idempotency-Key.")
        return {"status": "timeout", "message": "Payment timed out. Verification required."}
        
    except requests.exceptions.RequestException as req_err:
        logger.error(f"[Payment] Network communication failure with Stripe: {req_err}")
        return {"status": "failed", "message": "Network error, please try again later."}
        
    except Exception as general_err:
        logger.error(f"[Payment] Unexpected processing error: {general_err}")
        return {"status": "failed", "message": "An unexpected error occurred."}