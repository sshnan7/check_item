"""
디올 메달리옹 재입고 알림봇
- 1분마다 상품 페이지 제목(h1)에 "[품절]"이 붙어 있는지 확인합니다.
- "[품절]"이 사라지면 ntfy로 긴급 알림을 보냅니다 (재고가 있는 동안 5분마다 반복).
- 1시간마다 "정상 작동 중" 알림을 보냅니다.
- GitHub Actions가 매시간 새로 실행하며, 새 실행이 이전 실행을 대체합니다.
"""
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

PRODUCT_URL = (
    "https://www.dior.com/ko_kr/beauty/products/"
    "%5B%ED%92%88%EC%A0%88%5D-%EB%94%94%EC%98%AC-%EB%A9%94%EB%8B%AC%EB%A6%AC%EC%98%B9-Y0000391.html"
)
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()

CHECK_INTERVAL = 60            # 재고 확인 간격 (초)
HEARTBEAT_INTERVAL = 60 * 60   # 정상 작동 알림 간격 (초)
RESTOCK_REPEAT = 5 * 60        # 재고가 있는 동안 재알림 간격 (초)
RUN_DURATION = int(os.environ.get("RUN_DURATION", 5 * 60 * 60 + 40 * 60))  # 한 번 실행 시 최대 동작 시간

KST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def log(msg: str) -> None:
    print(f"[{datetime.now(KST):%m-%d %H:%M:%S}] {msg}", flush=True)


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


def notify(title: str, message: str, priority: str = "default", tags: str = "") -> None:
    if not NTFY_TOPIC:
        log("NTFY_TOPIC이 없어 알림을 보내지 않습니다.")
        return
    headers = {"Title": title.encode("utf-8"), "Priority": priority, "Click": PRODUCT_URL}
    if tags:
        headers["Tags"] = tags
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=30)
    except Exception as e:
        log(f"알림 전송 실패: {e}")


def check_once() -> tuple[str, str]:
    """('soldout'|'instock'|'error', 설명)을 돌려줍니다."""
    try:
        html = fetch(PRODUCT_URL)
    except Exception as e:
        return "error", f"페이지 접속 실패: {e}"
    title = get_product_title(html)
    if title is None:
        return "error", "상품명을 찾지 못함 (사이트 구조 변경 또는 차단 가능성)"
    return ("soldout" if is_sold_out(title) else "instock"), title


def main() -> int:
    start = time.monotonic()
    last_heartbeat = None
    last_restock_alert = None
    checks = errors = 0
    last_status, last_detail = "unknown", ""

    while time.monotonic() - start < RUN_DURATION:
        loop_start = time.monotonic()
        status, detail = check_once()
        checks += 1
        last_status, last_detail = status, detail
        log(f"{status}: {detail}")

        if status == "error":
            errors += 1
        elif status == "instock":
            if last_restock_alert is None or loop_start - last_restock_alert >= RESTOCK_REPEAT:
                notify(
                    "디올 메달리옹 재입고!",
                    "지금 구매 가능해요. 알림을 눌러 바로 이동하세요.",
                    priority="urgent",
                    tags="tada,lipstick",
                )
                last_restock_alert = loop_start
        else:
            last_restock_alert = None

        if last_heartbeat is None or loop_start - last_heartbeat >= HEARTBEAT_INTERVAL:
            state = {"soldout": "아직 품절", "instock": "재고 있음!", "error": "확인 오류"}.get(last_status, last_status)
            msg = f"현재 상태: {state}\n최근 1시간 확인 {checks}회"
            if errors:
                msg += f", 오류 {errors}회\n마지막 오류: {last_detail}" if last_status == "error" else f", 오류 {errors}회"
            notify(
                "재입고 알림봇 정상 작동 중" if errors < checks else "재입고 알림봇 확인 오류",
                msg,
                priority="low" if errors < checks else "high",
                tags="white_check_mark" if errors < checks else "warning",
            )
            last_heartbeat = loop_start
            checks = errors = 0

        time.sleep(max(0, CHECK_INTERVAL - (time.monotonic() - loop_start)))

    return 0


if __name__ == "__main__":
    sys.exit(main())
