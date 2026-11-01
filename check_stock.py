"""
디올 메달리옹 재입고 알림봇
- 상품 페이지의 제목(h1)에 "[품절]"이 붙어 있는지 확인합니다.
- "[품절]"이 사라지면 ntfy 앱으로 핸드폰에 푸시 알림을 보냅니다.
"""
import os
import re
import sys
import urllib.request

PRODUCT_URL = (
    "https://www.dior.com/ko_kr/beauty/products/"
    "%5B%ED%92%88%EC%A0%88%5D-%EB%94%94%EC%98%AC-%EB%A9%94%EB%8B%AC%EB%A6%AC%EC%98%B9-Y0000391.html"
)
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def get_product_title(html: str) -> str | None:
    """페이지의 상품명(h1) 텍스트를 꺼냅니다."""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
    if not m:
        return None
    text = re.sub(r"<[^>]+>", "", m.group(1))
    return re.sub(r"\s+", " ", text).strip()


def is_sold_out(title: str) -> bool:
    return "품절" in title


def notify(title: str, message: str) -> None:
    if not NTFY_TOPIC:
        print("NTFY_TOPIC이 설정되지 않아 알림을 보내지 않습니다.")
        return
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={
            "Title": title.encode("utf-8"),
            "Priority": "urgent",
            "Tags": "tada,lipstick",
            "Click": PRODUCT_URL,
        },
        method="POST",
    )
    urllib.request.urlopen(req, timeout=30)


def main() -> int:
    try:
        html = fetch(PRODUCT_URL)
    except Exception as e:
        print(f"페이지를 불러오지 못했습니다: {e}")
        return 1  # 실패로 표시 (GitHub에서 확인 가능)

    title = get_product_title(html)
    if title is None:
        print("상품명을 찾지 못했습니다. 사이트 구조가 바뀌었거나 접속이 차단됐을 수 있어요.")
        return 1

    print(f"현재 상품명: {title}")
    if is_sold_out(title):
        print("아직 품절입니다.")
        return 0

    print("재입고 감지! 알림을 보냅니다.")
    notify("디올 메달리옹 재입고!", "지금 구매 가능해요. 알림을 눌러 바로 이동하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
