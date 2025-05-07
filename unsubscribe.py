import requests

url = "https://strava.schaetz.cz/unsubscribe"
response = requests.post(url)

if response.status_code == 200:
    print("Unsubscribed successfully:", response.text)
else:
    print("Failed to unsubscribe:", response.status_code, response.text)