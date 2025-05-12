from flask import Flask, request, render_template, jsonify, make_response
import requests
import threading
import time
import logging
import signal
import sys
import json
import pandas as pd
from datetime import datetime, timedelta

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
app = Flask(__name__, template_folder='/app/templates')

# Constants for Strava API integration
CLIENT_ID = "155612"  # Replace with your actual Strava Client ID
CLIENT_SECRET = "7cd0b1dd7c81c3755da428082a3228182542886b"  # Replace with your actual Strava Client Secret
REDIRECT_URI = "https://strava.schaetz.cz/exchange_token"  # Redirect URI for OAuth
TOKEN_URL = "https://www.strava.com/oauth/token"  # URL to exchange authorization code for tokens
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"  # URL to fetch activities
WEBHOOK_SUBSCRIPTION_URL = "https://www.strava.com/api/v3/push_subscriptions"  # URL for webhook subscription
CALLBACK_URL = "https://strava.schaetz.cz/exchange_token"  # Callback URL for webhook
VERIFY_TOKEN = "STRAVA"  # Token to verify webhook requests

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

@app.before_request
def initialize_subscription():
    logging.debug("Entering initialize_subscription function.")
    global initialized
    if not initialized:
        initialized = True
        logging.info("Initializing webhook subscription.")
        delayed_subscription()

@app.route('/unsubscribe', methods=['POST'])
def manual_unsubscribe():
    global subscription_id
    with lock:
        if subscription_id:
            unsubscribe_from_webhook(subscription_id)
            subscription_id = None
            return "Unsubscribed successfully", 200
    return "No active subscription to unsubscribe", 400

@app.route('/exchange_token', methods=['GET', 'POST'])
def exchange_token_handler():
    """
    Handles the exchange of authorization code for tokens and processes Strava activities.
    Returns:
        Response: HTML response with the result of the token exchange and activity processing.
    """
    if request.method == 'GET':

        if 'hub.challenge' in request.args:
            if request.args.get('hub.verify_token') == VERIFY_TOKEN:
                logging.info("Webhook validation successful.")
                return jsonify({'hub.challenge': request.args.get('hub.challenge')}), 200
            else:
                logging.error("Invalid verify token received.")
                return jsonify({'error': 'Invalid verify token'}), 403

        # if 'hub.challenge' in request.args and request.args.get('hub.verify_token') == VERIFY_TOKEN:
        #     logging.info("Webhook validation successful.")
        #     # return jsonify({'hub.challenge': request.args.get('hub.challenge')}), 200 #old
        #     response = make_response(jsonify({"hub.challenge": request.args.get("hub.challenge")}), 200)
        #     response.headers["Content-Type"] = "application/json"
        #     return response
        # elif 'hub.challenge' in request.args:
        #     logging.error("Invalid verify token received.")
        #     return jsonify({'error': 'Invalid verify token'}), 403
        else:
            logging.info("Returning default webhook endpoint response.")
            return "Default webhook endpoint response", 200

    # Handle token exchange and data processing
    authorization_code = request.args.get('code')
    state = request.args.get('state')
    scope = request.args.get('scope')

    if authorization_code:
        print(f"Authorization Code received: {authorization_code}")
        access_token, refresh_token = get_strava_api_access_token(CLIENT_ID, CLIENT_SECRET, authorization_code)

        if access_token:
            activities_df = get_strava_activities_as_dataframe(access_token, days_back=30)
            elevation_summary = ""
            if not activities_df.empty:
                elevation_summary = summarize_elevation_data(activities_df.copy())

            unsubscribe_from_webhook(subscription_id)

            return render_template('exchange_result.html',
                                   authorization_code=authorization_code,
                                   access_token=access_token,
                                   refresh_token=refresh_token,
                                   state=state,
                                   scope=scope,
                                   elevation_summary=elevation_summary)
        else:
            return render_template('error.html', error="Failed to exchange authorization code.")
    else:
        error = request.args.get('error')
        return render_template('error.html', error=f"Authorization failed: {error}")

def summarize_elevation_data(df):
    """
    Summarizes elevation data from a DataFrame containing Strava activities.
    Args:
        df (pd.DataFrame): DataFrame containing activity data.
    Returns:
        str: A summary of elevation data for the last 7 and 30 days.
    """
    selection_df = df[df['activity_type'].isin(['Run', 'Walk', 'Hike'])].copy()
    if selection_df.empty:
        return "No relevant activities (Run, Walk, Hike) found for elevation analysis."

    selection_df['date'] = pd.to_datetime(selection_df['date']).dt.date
    daily_elevation = selection_df.groupby('date')['elevation_gain_m'].sum().reset_index()

    if daily_elevation.empty:
        return "No elevation gain data available for the selected activities."

    last_7_days = daily_elevation[daily_elevation['date'] >= (datetime.now() - timedelta(days=7)).date()]
    last_30_days = daily_elevation[daily_elevation['date'] >= (datetime.now() - timedelta(days=30)).date()]
    cumulative_elevation = daily_elevation.copy()
    cumulative_elevation['cumulative_elevation'] = cumulative_elevation['elevation_gain_m'].cumsum()
    cumulative_last_30_days = cumulative_elevation[cumulative_elevation['date'] >= (datetime.now() - timedelta(days=30)).date()].iloc[-1]['cumulative_elevation'] if not cumulative_elevation[cumulative_elevation['date'] >= (datetime.now() - timedelta(days=30)).date()].empty else 0

    summary = "\n--- Elevation Summary (Last 30 Days) ---\n"
    if not last_7_days.empty:
        total_elevation_last_7_days = last_7_days['elevation_gain_m'].sum()
        average_elevation_last_7_days = last_7_days['elevation_gain_m'].mean()
        summary += f"Total elevation gain (last 7 days): {total_elevation_last_7_days:.2f} meters\n"
        summary += f"Average daily elevation gain (last 7 days): {average_elevation_last_7_days:.2f} meters\n"
    else:
        summary += "No elevation data for the last 7 days.\n"

    if not last_30_days.empty:
        total_elevation_last_30_days = last_30_days['elevation_gain_m'].sum()
        average_elevation_last_30_days = last_30_days['elevation_gain_m'].mean()
        summary += f"Total elevation gain (last 30 days): {total_elevation_last_30_days:.2f} meters\n"
        summary += f"Average daily elevation gain (last 30 days): {average_elevation_last_30_days:.2f} meters\n"
    else:
        summary += "No elevation data for the last 30 days.\n"

    summary += f"Cumulative elevation gain (last 30 days): {cumulative_last_30_days:.2f} meters\n"

    return summary

def get_strava_api_access_token(client_id, client_secret, authorization_code):
    """
    Exchanges an authorization code for an access token and refresh token.
    Args:
        client_id (str): Strava Client ID.
        client_secret (str): Strava Client Secret.
        authorization_code (str): Authorization code received from Strava.
    Returns:
        tuple: Access token and refresh token if successful, (None, None) otherwise.
    """
    payload = {
        'client_id': client_id,
        'client_secret': client_secret,
        'code': authorization_code,
        'grant_type': 'authorization_code'
    }
    print(f"Attempting to exchange authorization code for tokens...")
    try:
        response = requests.post(TOKEN_URL, data=payload)
        if response.status_code == 200:
            token_data = response.json()
            access_token = token_data.get('access_token')
            refresh_token = token_data.get('refresh_token')
            expires_at = token_data.get('expires_at')
            print("\nToken exchange successful!")
            print("-" * 30)
            if access_token:
                print(f"Access Token: {access_token}")
            else:
                print("Access Token not found in response.")
            if refresh_token:
                print(f"Refresh Token: {refresh_token}")
            else:
                print("Refresh Token not found in response.")
            if expires_at is not None:
                expires_datetime = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(expires_at))
                print(f"Access Token Expiration Date (Unix Timestamp): {expires_at}")
                print(f"Access Token Expiration Date (UTC): {expires_datetime}")
            else:
                print("Access Token Expiration Date not found in response.")
            print("-" * 30)
            return access_token, refresh_token
        else:
            print(f"\nError during token exchange. Status code: {response.status_code}")
            try:
                error_details = response.json()
                print("Error Details:")
                print(json.dumps(error_details, indent=4))
            except json.JSONDecodeError:
                print("Could not decode error response as JSON.")
                print("Response body:")
                print(response.text)
            return None, None
    except requests.exceptions.RequestException as e:
        print(f"\nAn error occurred during the request: {e}")
        return None, None

def get_strava_activities_as_dataframe(access_token: str, days_back: int) -> pd.DataFrame:
    """
    Fetches Strava activities for the given number of days and returns them as a DataFrame.
    Args:
        access_token (str): Access token for Strava API.
        days_back (int): Number of days to fetch activities for.
    Returns:
        pd.DataFrame: DataFrame containing activity data.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    after_date = datetime.now() - timedelta(days=days_back)
    after_timestamp = int(after_date.timestamp())
    print(f"Attempting to fetch activities from the last {days_back} days...")
    try:
        response = requests.get(
            ACTIVITIES_URL,
            headers=headers,
            params={"after": after_timestamp, "per_page": 200, "page": 1}
        )
        if response.status_code == 200:
            activities = response.json()
            print(f"\n✅ Successfully fetched {len(activities)} activities.")
            activity_list = []
            if activities:
                for act in activities:
                    name = act.get("name", "Unnamed Activity")
                    activity_type = act.get("type", "Unknown Type")
                    date_str = act.get("start_date", "Unknown Date")
                    distance_meters = act.get("distance", 0)
                    elevation_gain_meters = act.get("total_elevation_gain", 0)
                    distance_km = distance_meters / 1000
                    activity_list.append({
                        "name": name,
                        "activity_type": activity_type,
                        "date": date_str,
                        "distance_km": round(distance_km, 2),
                        "elevation_gain_m": round(elevation_gain_meters, 2)
                    })
            df = pd.DataFrame(activity_list)
            return df
        else:
            print(f"\n❌ Failed to fetch activities. Status code: {response.status_code}")
            try:
                error_details = response.json()
                print("Error Details:")
                print(json.dumps(error_details, indent=4))
            except json.JSONDecodeError:
                print("Could not decode error response as JSON.")
                print("Response body:")
                print(response.text)
            return pd.DataFrame()
    except requests.exceptions.RequestException as e:
        print(f"\nAn error occurred during the request: {e}")
        return pd.DataFrame()

if __name__ == '__main__':
    logging.info("Starting Flask application.")
    app.run(debug=True, port=5000, host='0.0.0.0')