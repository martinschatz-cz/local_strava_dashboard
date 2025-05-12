from flask import Flask, request, jsonify, render_template
from stravalib import Client
import logging
import threading
import time
from datetime import datetime, timedelta
import pandas as pd

# Initialize Flask app
app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log", mode="a")
    ]
)

# Strava API constants
CLIENT_ID = "155612"  # Replace with your actual Strava Client ID
CLIENT_SECRET = "7cd0b1dd7c81c3755da428082a3228182542886b"  # Replace with your actual Strava Client Secret
REDIRECT_URI = "https://strava.schaetz.cz/exchange_token"
VERIFY_TOKEN = "STRAVA"

# Global variables
client = Client()
subscription_id = None
lock = threading.Lock()

@app.route('/exchange_token', methods=['GET', 'POST'])
def exchange_token_handler():
    """
    Handles the exchange of authorization code for tokens and processes Strava activities.
    """
    if request.method == 'GET':
        # Webhook validation
        hub_challenge = request.args.get('hub.challenge')
        verify_token = request.args.get('hub.verify_token')
        if hub_challenge and verify_token == VERIFY_TOKEN:
            logging.info("Webhook validation successful.")
            return jsonify({"hub.challenge": hub_challenge}), 200

        # OAuth token exchange
        authorization_code = request.args.get('code')
        if authorization_code:
            try:
                access_token = client.exchange_code_for_token(
                    client_id=CLIENT_ID,
                    client_secret=CLIENT_SECRET,
                    code=authorization_code
                )
                client.access_token = access_token['access_token']
                client.refresh_token = access_token['refresh_token']
                client.token_expires_at = access_token['expires_at']
                logging.info("Token exchange successful.")
                activities_df = get_strava_activities_as_dataframe(client, days_back=30)
                elevation_summary = summarize_elevation_data(activities_df)
                return render_template('exchange_result.html', elevation_summary=elevation_summary)
            except Exception as e:
                logging.error(f"Error during token exchange: {e}")
                return render_template('error.html', error="Failed to exchange authorization code.")
        else:
            error = request.args.get('error')
            return render_template('error.html', error=f"Authorization failed: {error}")

@app.route('/subscribe', methods=['POST'])
def subscribe_to_webhook():
    """
    Subscribes to the Strava webhook.
    """
    global subscription_id
    try:
        response = client.create_subscription(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            callback_url=REDIRECT_URI,
            verify_token=VERIFY_TOKEN
        )
        subscription_id = response['id']
        logging.info(f"Successfully subscribed to webhook. Subscription ID: {subscription_id}")
        return jsonify({"message": "Webhook subscription successful", "subscription_id": subscription_id}), 201
    except Exception as e:
        logging.error(f"Error subscribing to webhook: {e}")
        return jsonify({"error": "Failed to subscribe to webhook"}), 500

@app.route('/unsubscribe', methods=['POST'])
def unsubscribe_from_webhook():
    """
    Unsubscribes from the Strava webhook.
    """
    global subscription_id
    if subscription_id:
        try:
            client.delete_subscription(subscription_id)
            logging.info(f"Successfully unsubscribed from webhook. Subscription ID: {subscription_id}")
            subscription_id = None
            return jsonify({"message": "Webhook unsubscription successful"}), 200
        except Exception as e:
            logging.error(f"Error unsubscribing from webhook: {e}")
            return jsonify({"error": "Failed to unsubscribe from webhook"}), 500
    else:
        return jsonify({"error": "No active subscription to unsubscribe"}), 400

def get_strava_activities_as_dataframe(client, days_back: int) -> pd.DataFrame:
    """
    Fetches Strava activities for the given number of days and returns them as a DataFrame.
    """
    activities = []
    after_date = datetime.now() - timedelta(days=days_back)
    for activity in client.get_activities(after=after_date):
        activities.append({
            "name": activity.name,
            "activity_type": activity.type,
            "date": activity.start_date_local,
            "distance_km": activity.distance.num / 1000 if activity.distance else 0,
            "elevation_gain_m": activity.total_elevation_gain.num if activity.total_elevation_gain else 0
        })
    return pd.DataFrame(activities)

def summarize_elevation_data(df):
    """
    Summarizes elevation data from a DataFrame containing Strava activities.
    """
    if df.empty:
        return "No activities found for elevation analysis."
    df['date'] = pd.to_datetime(df['date']).dt.date
    last_30_days = df[df['date'] >= (datetime.now() - timedelta(days=30)).date()]
    total_elevation = last_30_days['elevation_gain_m'].sum()
    return f"Total elevation gain in the last 30 days: {total_elevation:.2f} meters"

if __name__ == '__main__':
    logging.info("Starting Flask application.")
    app.run(debug=True, port=5000, host='0.0.0.0')