import datetime

API_URL = "https://apirtt.mytennis.online/api/v1/public"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://rtt.mytennis.online",
    "Referer": "https://rtt.mytennis.online/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
    ),
}
RATING_FIELD = datetime.date.today().strftime("%Y%m011")

TOUR_ID = 307095
