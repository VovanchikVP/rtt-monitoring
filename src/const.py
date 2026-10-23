API_URL = "https://apirtt.mytennis.online/api/v1/public"
# HEADERS = {
#     "Accept": "application/json, text/plain, */*",
#     "Origin": "https://rtt.mytennis.online",
#     "Referer": "https://rtt.mytennis.online/",
#     "User-Agent": (
#         "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
#         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
#     ),
# }

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru,en-US;q=0.9,en;q=0.8,th;q=0.7",
    "Connection": "keep-alive",
    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
    "Origin": "https://rtt.mytennis.online",
    "Referer": "https://rtt.mytennis.online/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
}
COOKIES = {
    "_ym_uid": "1772026133812119450",
    "_ym_d": "1789518383",
    "_ym_isad": "2",
    "mdd": "1",
    "S35cad37321ccabf": "8r7a5g3aknuvd0rpspf7nmtjj2",
}
# таймаут запросов к внешнему API, секунды
HTTP_TIMEOUT = 15
# пауза между запросами к внешнему API, секунды
REQUEST_DELAY = 4
# сколько ждать, когда внешнее API требует проверку и своей паузы не называет
THROTTLE_DELAY = 600
