from flask import Flask, request, jsonify
import requests
import threading
import time
import logging
import signal
import sys

def handle_shutdown_signal(signum, frame):
    logging.info("Received shutdown signal. Cleaning up resources.")
    delayed_unsubscription()
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, handle_shutdown_signal)  # Handle Ctrl+C
signal.signal(signal.SIGTERM, handle_shutdown_signal)  # Handle Docker stop

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log", mode="a")
    ]
)

# Initialize the Flask application
app = Flask(__name__)

# Constants for Strava webhook subscription
CLIENT_ID = "155612"
CLIENT_SECRET = "7cd0b1dd7c81c3755da428082a3228182542886b"
CALLBACK_URL = "https://strava.schaetz.cz/exchange_token"
VERIFY_TOKEN = "STRAVA"
WEBHOOK_SUBSCRIPTION_URL = "https://www.strava.com/api/v3/push_subscriptions"

subscription_id = None
initialized = False
lock = threading.Lock()

def subscribe_to_webhook():
    global subscription_id
    logging.debug("Entering subscribe_to_webhook function.")
    payload = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'callback_url': CALLBACK_URL,
        'verify_token': VERIFY_TOKEN
    }
    logging.info(f"Payload for webhook subscription: {payload}")
    try:
        response = requests.post(WEBHOOK_SUBSCRIPTION_URL, data=payload)
        logging.debug(f"Webhook subscription response: {response.status_code} - {response.text}")
        if response.status_code == 201:
            with lock:
                subscription_id = response.json().get("id")
            logging.info(f"✅ Successfully subscribed to the webhook. Subscription ID: {subscription_id}")
            return subscription_id
        else:
            logging.error(f"❌ Failed to subscribe to the webhook. Status code: {response.status_code}")
            logging.error(f"Response body: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        logging.exception("An error occurred during webhook subscription.")
        return None

def unsubscribe_from_webhook(subscription_id):
    logging.debug("Entering unsubscribe_from_webhook function.")
    logging.info(f"Attempting to unsubscribe from webhook with Subscription ID: {subscription_id}")
    try:
        url = f"{WEBHOOK_SUBSCRIPTION_URL}/{subscription_id}"
        params = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET
        }
        logging.debug(f"Unsubscription URL: {url}, Params: {params}")
        response = requests.delete(url, params=params)
        logging.debug(f"Webhook unsubscription response: {response.status_code} - {response.text}")
        if response.status_code == 204:
            logging.info(f"✅ Successfully unsubscribed from the webhook. Subscription ID: {subscription_id}")
        else:
            logging.error(f"❌ Failed to unsubscribe from the webhook. Status code: {response.status_code}, Subscription ID: {subscription_id}")
            logging.error(f"Response body: {response.text}")
    except requests.exceptions.RequestException as e:
        logging.exception("An error occurred during webhook unsubscription.")

def delayed_subscription():
    logging.debug("Entering delayed_subscription function.")
    def task():
        time.sleep(5)
        global subscription_id
        with lock:
            subscription_id = subscribe_to_webhook()
    threading.Thread(target=task).start()

def delayed_unsubscription():
    logging.debug("Entering delayed_unsubscription function.")
    def task():
        time.sleep(5)
        global subscription_id
        with lock:
            if subscription_id:
                unsubscribe_from_webhook(subscription_id)
    threading.Thread(target=task).start()

@app.before_first_request
def initialize_subscription():
    logging.debug("Entering initialize_subscription function.")
    global initialized
    if not initialized:
        initialized = True
        logging.info("Initializing webhook subscription.")
        delayed_subscription()

@app.before_shutdown
def cleanup_subscription():
    logging.debug("Entering cleanup_subscription function.")
    delayed_unsubscription()

@app.route('/unsubscribe', methods=['POST'])
def manual_unsubscribe():
    global subscription_id
    with lock:
        if subscription_id:
            unsubscribe_from_webhook(subscription_id)
            subscription_id = None
            return "Unsubscribed successfully", 200
    return "No active subscription to unsubscribe", 400

@app.route('/exchange_token', methods=['GET'])
def exchange_token_handler():
    logging.debug("Entering exchange_token_handler function.")
    if 'hub.challenge' in request.args:
        if request.args.get('hub.verify_token') == VERIFY_TOKEN:
            logging.info("Webhook validation successful.")
            return jsonify({'hub.challenge': request.args.get('hub.challenge')}), 200
        else:
            logging.error("Invalid verify token received.")
            return jsonify({'error': 'Invalid verify token'}), 403
    logging.info("Returning default webhook endpoint response.")
    return "Webhook endpoint", 200

if __name__ == '__main__':
    logging.info("Starting Flask application.")
    app.run(debug=True, port=5000, host='0.0.0.0')