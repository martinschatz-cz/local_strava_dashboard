FROM python:3.9-slim-buster

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt --no-cache-dir

COPY . .

EXPOSE 5000

ENV CLIENT_ID=${CLIENT_ID}
ENV CLIENT_SECRET=${CLIENT_SECRET}
# adding port did not change anything 
ENV REDIRECT_URI=strava.schaetz.cz/exchange_token

CMD ["python", "app.py"]
