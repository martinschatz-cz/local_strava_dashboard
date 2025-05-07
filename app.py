from flask import Flask, request, jsonify
import requests
import threading
import time
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

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

def subscribe_to_webhook():
    payload = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'callback_url': CALLBACK_URL,
        'verify_token': VERIFY_TOKEN
    }
    response = requests.post(WEBHOOK_SUBSCRIPTION_URL, data=payload)
    if response.status_code == 201:
        return response.json().get("id")
    return None

def unsubscribe_from_webhook(subscription_id):
    url = f"{WEBHOOK_SUBSCRIPTION_URL}/{subscription_id}"
    params = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET
    }
    requests.delete(url, params=params)

def delayed_subscription():
    def task():
        time.sleep(5)  # Wait for 5 seconds before subscribing
        global subscription_id
        subscription_id = subscribe_to_webhook()
    threading.Thread(target=task).start()

def delayed_unsubscription():
    def task():
        time.sleep(10)  # Wait for 10 seconds before unsubscribing
        if subscription_id:
            unsubscribe_from_webhook(subscription_id)
    threading.Thread(target=task).start()

@app.before_request
def initialize_subscription():
    global initialized
    if not initialized:
        initialized = True
        delayed_subscription()

@app.teardown_appcontext
def cleanup_subscription(exception=None):
    delayed_unsubscription()

@app.route('/exchange_token', methods=['GET'])
def exchange_token_handler():
    if 'hub.challenge' in request.args:
        if request.args.get('hub.verify_token') == VERIFY_TOKEN:
            return jsonify({'hub.challenge': request.args.get('hub.challenge')}), 200
        else:
            return jsonify({'error': 'Invalid verify token'}), 403
    return "Webhook endpoint", 200

if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')