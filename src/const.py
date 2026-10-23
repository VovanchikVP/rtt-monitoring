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
# таймаут запросов к внешнему API, секунды
HTTP_TIMEOUT = 15
# пауза между запросами к внешнему API, секунды
REQUEST_DELAY = 10
# с какой паузы начинать, когда внешнее API требует проверку и своей не называет
THROTTLE_DELAY = 600
# потолок паузы: дальше удваивать бессмысленно, задачи просто протухнут
THROTTLE_MAX_DELAY = 4 * 3600
