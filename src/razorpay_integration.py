"""
Razorpay Test Gateway Integration
----------------------------------
Calls the actual Razorpay v1 REST API in TEST mode.

Usage:
    from src.razorpay_integration import RazorpayTestClient

    client = RazorpayTestClient()
    result = client.retry_payment(txn_id, amount, customer_id)
"""
import os
import logging
from typing import Dict, Any

import requests
from dotenv import load_dotenv

from src.retry_handler import exponential_backoff

load_dotenv()

logger = logging.getLogger(__name__)


class RazorpayTestClient:
    """
    Thin wrapper around the Razorpay v1 REST API (test mode).

    All calls are authenticated with HTTP Basic Auth using the
    test key_id / key_secret pair from environment variables.
    Network failures on retry_payment are automatically retried
    up to 3 times with exponential backoff (1 s, 2 s) before failing.
    """

    BASE_URL = "https://api.razorpay.com/v1"

    def __init__(self) -> None:
        self.key_id: str = os.getenv("RAZORPAY_TEST_KEY_ID", "")
        self.key_secret: str = os.getenv("RAZORPAY_TEST_KEY_SECRET", "")

        if not self.key_id or not self.key_secret:
            logger.warning(
                "Razorpay credentials not found in environment. "
                "Set RAZORPAY_TEST_KEY_ID and RAZORPAY_TEST_KEY_SECRET in .env"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retry_payment(
        self,
        txn_id: str,
        amount: int,
        customer_id: str,
        currency: str = "INR",
    ) -> Dict[str, Any]:
        """
        Create a Razorpay order as a payment-recovery retry attempt.

        Razorpay's recommended recovery flow is to create a fresh Order
        (linked to the original transaction) and re-present it to the
        customer or initiate an auto-charge via a saved token.

        Args:
            txn_id:      Original failed transaction ID (used as receipt tag)
            amount:      Amount in **rupees** (converted to paise internally)
            customer_id: Razorpay customer ID for the payer
            currency:    ISO 4217 currency code (default: INR)

        Returns:
            dict with keys:
                success     (bool)
                order_id    (str, on success)
                status      (str)
                response    (dict, raw Razorpay JSON)
                error       (str, on failure)
                status_code (int, on HTTP failure)
        """
        if not self.key_id or not self.key_secret:
            return {
                "success": False,
                "error": "Razorpay credentials not configured",
            }

        payload: dict = {
            "amount": int(amount) * 100,  # Razorpay uses paise (1 INR = 100 paise)
            "currency": currency,
            "receipt": f"recovery_{txn_id}",
            "notes": {
                "recovery_attempt": "true",
                "original_txn_id": txn_id,
            },
        }

        # Only pass customer_id when it looks like a real Razorpay customer ID.
        # Real Razorpay customer IDs: "cust_" prefix + 14-char alphanumeric = ~19+ chars.
        # Placeholder / synthetic IDs (e.g. "cust_placeholder") cause a 400 BAD_REQUEST.
        if customer_id and customer_id.startswith("cust_") and len(customer_id) >= 19:
            payload["customer_id"] = customer_id

        # _post_order has built-in exponential backoff for transient failures
        response = self._post_order(payload)

        if response is None:
            # Backoff exhausted — all retry attempts timed out / connection failed
            logger.error("Razorpay API unreachable for txn %s after retries", txn_id)
            return {"success": False, "error": "API unreachable after retries"}

        if response.status_code == 200:
            order = response.json()
            return {
                "success": True,
                "order_id": order.get("id"),
                "status": order.get("status", "created"),
                "response": order,
            }

        logger.error(
            "Razorpay API error %s for txn %s: %s",
            response.status_code, txn_id, response.text[:200],
        )
        return {
            "success": False,
            "error": response.text,
            "status_code": response.status_code,
        }

    def get_order(self, order_id: str) -> Dict[str, Any]:
        """
        Fetch an existing Razorpay order by ID.

        Args:
            order_id: Razorpay order ID (e.g. order_xxxxx)

        Returns:
            dict with success flag and raw order payload
        """
        try:
            response = requests.get(
                f"{self.BASE_URL}/orders/{order_id}",
                auth=(self.key_id, self.key_secret),
                timeout=5,
            )
            if response.status_code == 200:
                return {"success": True, "order": response.json()}
            return {
                "success": False,
                "error": response.text,
                "status_code": response.status_code,
            }
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Internal (with exponential backoff)
    # ------------------------------------------------------------------

    @exponential_backoff(
        max_attempts=3,
        base_delay=1.0,
        exceptions=(requests.Timeout, requests.ConnectionError),
        reraise=False,   # return None on exhaustion; retry_payment handles None
    )
    def _post_order(self, payload: dict) -> requests.Response | None:
        """Internal POST to /v1/orders — retried automatically on network errors."""
        return requests.post(
            f"{self.BASE_URL}/orders",
            json=payload,
            auth=(self.key_id, self.key_secret),
            timeout=5,
        )
