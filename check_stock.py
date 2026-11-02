"""
디올 메달리옹 재입고 알림봇
- 1분마다 상품 페이지 제목(h1)에 "[품절]"이 붙어 있는지 확인합니다.
- 재입고되면 즉시 알림 + 1분마다 10분 동안 긴급 알림을 보냅니다 (총 10회).
- 1시간마다 현재 상태와 그동안의 확인 횟수를 알려줍니다.
- 확인 오류가 나면 즉시 알림 (계속되면 10분마다), 복구되면 복구 알림을 보냅니다.
- 한 번 실행이 5시간 동안 돌고, 대기 중이던 다음 실행이 이어받습니다.
"""
import json
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
HEARTBEAT_INTERVAL = 60 * 60   # 상태 알림 간격 (초)
RESTOCK_ALERT_COUNT = 10       # 재입고 발견 후 1분마다 보낼 알림 횟수 (= 10분)
ERROR_REPEAT = 10 * 60         # 오류가 계속될 때 재알림 간격 (초)
# 한 번 실행 시 동작 시간: 정확히 5시간(상태 알림 5번) 후 종료 → 대기 중이던 다음 실행이 이어받음
RUN_DURATION = int(os.environ.get("RUN_DURATION", 5 * 60 * 60 + 30))

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
    # JSON으로 보내면 제목의 한글·이모지가 깨지지 않습니다.
    payload = {
        "topic": NTFY_TOPIC,
        "title": title,
        "message": message,
        "priority": {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}[priority],
        "tags": [t for t in tags.split(",") if t],
        "click": PRODUCT_URL,
    }
    req = urllib.request.Request(
        "https://ntfy.sh/",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
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
    last_heartbeat = start          # 시작 후 1시간 뒤 첫 상태 알림
    restock_since = None            # 이번 재입고를 처음 발견한 시각
    restock_alerts = 0              # 이번 재입고에 보낸 알림 수
    checks = errors = 0
    last_status, last_detail = "unknown", ""
    error_since = None              # 연속 오류가 시작된 시각
    last_error_alert = 0.0

    while time.monotonic() - start < RUN_DURATION:
        loop_start = time.monotonic()
        status, detail = check_once()
        checks += 1
        log(f"{status}: {detail}")
        if status == "error":
            errors += 1
            # 오류가 나면 즉시 알림, 계속되면 10분마다 다시 알림
            if error_since is None or loop_start - last_error_alert >= ERROR_REPEAT:
                if error_since is None:
                    error_since = loop_start
                streak = int((loop_start - error_since) // 60)
                notify(
                    "⚠️ 재입고 알림봇 확인 오류",
                    f"페이지를 제대로 확인하지 못했어요.\n{detail}"
                    + (f"\n{streak}분째 계속 오류 중" if streak else "\n다음 확인은 1분 뒤예요."),
                    priority="high",
                    tags="warning",
                )
                last_error_alert = loop_start
        else:
            if error_since is not None:
                mins = max(1, round((loop_start - error_since) / 60))
                notify("✅ 재입고 알림봇 복구됨", f"오류가 해결돼서 다시 정상 확인 중이에요. (약 {mins}분간 오류)",
                       priority="default", tags="white_check_mark")
                error_since = None
            last_status = status
        last_detail = detail

        if status == "instock":
            if restock_since is None:
                restock_since = loop_start  # 재입고 발견 → 즉시 알림 시작
                restock_alerts = 0
            # 발견 후 10분 동안 1분마다 알림 (총 10회)
            if restock_alerts < RESTOCK_ALERT_COUNT:
                restock_alerts += 1
                n = restock_alerts
                notify(
                    f"🚨🚨 재입고!!! 디올 메달리옹 지금 구매 가능 🚨🚨 ({n}/10)",
                    "🔥🔥 지금 당장 들어가세요!!! 🔥🔥\n"
                    "⏰ 한정판이라 금방 다시 품절돼요!\n"
                    "👉 알림 누르면 바로 상품 페이지로 이동 👈\n"
                    "💄💄💄 GO GO GO 💄💄💄",
                    priority="urgent",
                    tags="rotating_light,fire,lipstick,warning",
                )
        elif status == "soldout":
            restock_since = None  # 다시 품절되면 다음 재입고 때 또 알림

        if loop_start - last_heartbeat >= HEARTBEAT_INTERVAL - 5:
            state = {"soldout": "품절", "instock": "재고 있음!", "unknown": "확인 안 됨"}[last_status]
            msg = f"현재 상태: {state}\n최근 1시간 동안 {checks}회 확인"
            if errors:
                msg += f" (오류 {errors}회)\n마지막 결과: {last_detail}"
            failing = errors == checks
            notify(
                "⚠️ 재입고 알림봇 확인 오류" if failing else f"알림봇 정상 작동 중 · {state}",
                msg,
                priority="high" if failing else "default",
                tags="warning" if failing else "white_check_mark",
            )
            last_heartbeat = loop_start
            checks = errors = 0

        time.sleep(max(0, CHECK_INTERVAL - (time.monotonic() - loop_start)))

    return 0


if __name__ == "__main__":
    sys.exit(main())
