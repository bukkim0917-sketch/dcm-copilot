"""
DCM Copilot — AI-powered Corporate Funding Analysis
====================================================

기업 정보와 자금조달 계획을 입력하면 n8n 웹훅으로 전송하고,
돌아온 AI 분석 결과를 증권사 리포트 형식으로 보여주는 Streamlit 앱.

실행 방법
---------
    pip install -r requirements.txt
    cp .streamlit/secrets.toml.example .streamlit/secrets.toml
    # secrets.toml 을 열어 실제 n8n 웹훅 주소를 입력
    streamlit run app.py

웹훅 주소는 코드에 적지 않고 st.secrets 에서만 읽는다.
"""

from datetime import date

import requests
import streamlit as st

# ---------------------------------------------------------------------------
# 설정값 (수정이 필요한 값은 전부 여기에 모아둔다)
# ---------------------------------------------------------------------------

APP_TITLE = "DCM Copilot"
APP_SUBTITLE = "AI-powered Corporate Funding Analysis"

# n8n 워크플로우에서 LLM을 호출하면 응답이 느릴 수 있어 넉넉히 잡는다.
REQUEST_TIMEOUT_SECONDS = 120

# 검증 상태 판정에 쓰는 키워드. 대소문자와 구분자(_, -)는 무시하고 비교한다.
REVIEW_KEYWORDS = ["REVIEW REQUIRED", "REVIEWREQUIRED", "검토 필요", "검토필요"]
PASS_KEYWORDS = ["PASS"]

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="📈",
    layout="wide",
)

# ---------------------------------------------------------------------------
# 스타일 — 증권사 리서치 리포트 톤 (네이비 + 얇은 괘선, 장식 최소화)
# ---------------------------------------------------------------------------

CUSTOM_CSS = """
<style>
:root {
    --ink: #0B1F3A;
    --ink-soft: #55647B;
    --rule: #DCE1E8;
    --accent: #B8912F;
}

/* 상단 리포트 헤더 */
.dcm-header {
    border-top: 3px solid var(--ink);
    border-bottom: 1px solid var(--rule);
    padding: 20px 0 16px 0;
    margin-bottom: 4px;
}
.dcm-header .title {
    font-size: 32px;
    font-weight: 700;
    letter-spacing: -0.6px;
    color: var(--ink);
    line-height: 1.15;
}
.dcm-header .subtitle {
    font-size: 13px;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    color: var(--ink-soft);
    margin-top: 6px;
}

/* 섹션 제목 — 번호는 리포트 목차 순서를 뜻한다 */
.dcm-section {
    display: flex;
    align-items: baseline;
    gap: 10px;
    border-bottom: 1px solid var(--rule);
    padding-bottom: 6px;
    margin: 30px 0 16px 0;
}
.dcm-section .num {
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1.5px;
    color: var(--accent);
}
.dcm-section .label {
    font-size: 18px;
    font-weight: 700;
    letter-spacing: -0.2px;
    color: var(--ink);
}

/* 입력 요약 카드 */
.dcm-fact {
    border: 1px solid var(--rule);
    border-left: 3px solid var(--ink);
    padding: 12px 14px;
    height: 100%;
}
.dcm-fact .k {
    font-size: 11px;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--ink-soft);
    margin-bottom: 5px;
}
.dcm-fact .v {
    font-size: 16px;
    font-weight: 600;
    color: var(--ink);
    word-break: break-word;
}

/* 검증 상태 배지 */
.dcm-status {
    display: inline-block;
    padding: 8px 18px;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 1px;
    border: 1px solid;
    margin-bottom: 14px;
}
.dcm-status.pass {
    color: #14612F;
    border-color: #14612F;
    background: #F0F7F2;
}
.dcm-status.review {
    color: #8A5A00;
    border-color: #8A5A00;
    background: #FDF7EC;
}
.dcm-status.unknown {
    color: var(--ink-soft);
    border-color: var(--rule);
    background: #F7F8FA;
}

.dcm-disclaimer {
    border-top: 1px solid var(--rule);
    margin-top: 34px;
    padding-top: 12px;
    font-size: 12px;
    line-height: 1.6;
    color: var(--ink-soft);
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 도우미 함수
# ---------------------------------------------------------------------------

def render_section(number: str, label: str) -> None:
    """번호가 붙은 섹션 제목을 그린다."""
    st.markdown(
        f'<div class="dcm-section"><span class="num">{number}</span>'
        f'<span class="label">{label}</span></div>',
        unsafe_allow_html=True,
    )


def render_fact(key_label: str, value: str) -> None:
    """입력 요약용 카드 하나를 그린다."""
    safe_value = (value or "-").replace("<", "&lt;").replace(">", "&gt;")
    st.markdown(
        f'<div class="dcm-fact"><div class="k">{key_label}</div>'
        f'<div class="v">{safe_value}</div></div>',
        unsafe_allow_html=True,
    )


def get_webhook_url():
    """secrets 에서 웹훅 주소를 읽는다. 설정되지 않았으면 None."""
    try:
        url = st.secrets["N8N_WEBHOOK_URL"]
    except (KeyError, FileNotFoundError):
        return None
    url = str(url).strip()
    return url or None


def call_webhook(url: str, payload: dict) -> dict:
    """
    n8n 웹훅에 POST 요청을 보내고 응답을 dict 로 반환한다.
    네트워크/HTTP 오류는 예외로 올려보내고, 호출부에서 처리한다.
    """
    response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()

    try:
        data = response.json()
    except ValueError:
        raise ValueError("웹훅이 JSON 형식이 아닌 응답을 반환했습니다.")

    # n8n 은 보통 [{...}] 형태의 배열로 응답한다
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        raise ValueError("웹훅 응답 구조가 예상과 다릅니다. (객체가 아님)")
    return data


def detect_status(validation_text: str) -> str:
    """
    검증 결과 텍스트에서 상태를 판정한다.
    'pass' | 'review' | 'unknown' 중 하나를 반환.
    REVIEW REQUIRED 를 먼저 검사한다 — 두 단어가 함께 등장하면
    보수적으로 '검토 필요'로 본다.
    """
    if not validation_text:
        return "unknown"

    normalized = validation_text.upper().replace("_", " ").replace("-", " ")

    for keyword in REVIEW_KEYWORDS:
        if keyword.upper() in normalized:
            return "review"
    for keyword in PASS_KEYWORDS:
        if keyword.upper() in normalized:
            return "pass"
    return "unknown"


def render_status_badge(status: str) -> None:
    """판정된 상태를 배지로 크게 표시한다."""
    labels = {
        "pass": ("PASS · 검증 통과", "pass"),
        "review": ("REVIEW REQUIRED · 검토 필요", "review"),
        "unknown": ("판정 불가 · 상태 미표기", "unknown"),
    }
    text, css_class = labels[status]
    st.markdown(
        f'<div class="dcm-status {css_class}">{text}</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# 헤더
# ---------------------------------------------------------------------------

st.markdown(
    f'<div class="dcm-header">'
    f'<div class="title">{APP_TITLE}</div>'
    f'<div class="subtitle">{APP_SUBTITLE}</div>'
    f'</div>',
    unsafe_allow_html=True,
)

webhook_url = get_webhook_url()
if webhook_url is None:
    st.error(
        "웹훅 주소가 설정되지 않았습니다. `.streamlit/secrets.toml` 파일에 "
        '`N8N_WEBHOOK_URL = "https://..."` 를 추가한 뒤 앱을 다시 실행하세요.'
    )

# ---------------------------------------------------------------------------
# 입력 영역 (사이드바)
# ---------------------------------------------------------------------------

with st.sidebar:
    st.subheader("발행기업 정보 입력")

    with st.form("dcm_input_form"):
        company_name = st.text_input("기업명", placeholder="예) 삼성전자")
        corp_code = st.text_input(
            "DART corp_code",
            placeholder="예) 00126380",
            help="DART 전자공시시스템이 기업별로 부여하는 8자리 고유번호입니다.",
        )
        year = st.number_input(
            "분석연도",
            min_value=2015,
            max_value=date.today().year - 1,
            value=2025,
            step=1,
        )
        funding_amount = st.text_input("조달예정금액", placeholder="예) 1,000억원")
        funding_purpose = st.text_area(
            "조달목적",
            placeholder="예) 만기 회사채 차환 및 신규 설비투자 재원 확보",
            height=120,
        )

        submitted = st.form_submit_button(
            "Analyze", type="primary", use_container_width=True
        )

    st.caption("입력값은 n8n 워크플로우로 전송되어 AI 분석에 사용됩니다.")

# ---------------------------------------------------------------------------
# 분석 실행
# ---------------------------------------------------------------------------

# 세션 상태에 저장해두면 화면이 다시 그려져도 결과가 유지된다
if "result" not in st.session_state:
    st.session_state.result = None
    st.session_state.payload = None

if submitted:
    missing = []
    if not company_name.strip():
        missing.append("기업명")
    if not corp_code.strip():
        missing.append("DART corp_code")
    if not funding_amount.strip():
        missing.append("조달예정금액")
    if not funding_purpose.strip():
        missing.append("조달목적")

    if missing:
        st.warning("다음 항목을 입력하세요: " + ", ".join(missing))
    elif webhook_url is None:
        st.error("웹훅 주소가 없어 분석을 실행할 수 없습니다.")
    else:
        payload = {
            "company_name": company_name.strip(),
            "corp_code": corp_code.strip(),
            "year": int(year),
            "funding_amount": funding_amount.strip(),
            "funding_purpose": funding_purpose.strip(),
        }

        with st.spinner("분석을 진행 중입니다. 최대 2분까지 소요될 수 있습니다..."):
            try:
                st.session_state.result = call_webhook(webhook_url, payload)
                st.session_state.payload = payload
            except requests.exceptions.Timeout:
                st.session_state.result = None
                st.error(
                    f"{REQUEST_TIMEOUT_SECONDS}초 안에 응답이 오지 않았습니다. "
                    "n8n 워크플로우가 활성화되어 있는지 확인한 뒤 다시 시도하세요."
                )
            except requests.exceptions.ConnectionError:
                st.session_state.result = None
                st.error("웹훅 주소에 연결하지 못했습니다. 주소와 네트워크 상태를 확인하세요.")
            except requests.exceptions.HTTPError as error:
                st.session_state.result = None
                status_code = (
                    error.response.status_code if error.response is not None else "알 수 없음"
                )
                st.error(
                    f"웹훅이 오류 상태 코드 {status_code} 를 반환했습니다. "
                    "n8n 실행 로그에서 실패한 노드를 확인하세요."
                )
            except requests.exceptions.RequestException as error:
                st.session_state.result = None
                st.error(f"요청 처리 중 오류가 발생했습니다: {error}")
            except ValueError as error:
                st.session_state.result = None
                st.error(str(error))

# ---------------------------------------------------------------------------
# 결과 출력
# ---------------------------------------------------------------------------

result = st.session_state.result
payload = st.session_state.payload

if result is None:
    st.info("좌측에서 기업 정보를 입력하고 **Analyze** 를 누르면 분석 결과가 표시됩니다.")
else:
    strategy_analysis = str(result.get("strategy_analysis") or "").strip()
    validation_result = str(result.get("validation_result") or "").strip()

    # ---- 01. 입력 요약 ---------------------------------------------------
    render_section("01", "입력 요약")

    col1, col2, col3 = st.columns(3)
    with col1:
        render_fact("기업명", payload["company_name"])
    with col2:
        render_fact("DART corp_code", payload["corp_code"])
    with col3:
        render_fact("분석연도", str(payload["year"]))

    col4, col5 = st.columns([1, 2])
    with col4:
        render_fact("조달예정금액", payload["funding_amount"])
    with col5:
        render_fact("조달목적", payload["funding_purpose"])

    # ---- 02. DCM Strategy Analysis --------------------------------------
    render_section("02", "DCM Strategy Analysis")

    if strategy_analysis:
        # st.markdown 으로 렌더링해야 웹훅이 보낸 Markdown 서식이 적용된다
        with st.container(border=True):
            st.markdown(strategy_analysis)
    else:
        st.warning(
            "응답에 `strategy_analysis` 값이 없습니다. "
            "n8n 워크플로우의 최종 노드가 해당 필드를 반환하는지 확인하세요."
        )

    # ---- 03. AI Validation Result ---------------------------------------
    render_section("03", "AI Validation Result")

    if validation_result:
        render_status_badge(detect_status(validation_result))
        with st.container(border=True):
            st.markdown(validation_result)
    else:
        st.warning(
            "응답에 `validation_result` 값이 없습니다. "
            "n8n 워크플로우의 검증 노드 출력을 확인하세요."
        )

    with st.expander("원본 응답(JSON) 확인"):
        st.json(result)

# ---------------------------------------------------------------------------
# 하단 고지
# ---------------------------------------------------------------------------

st.markdown(
    '<div class="dcm-disclaimer">본 도구는 공개 공시자료 기반의 분석 보조 도구이며 '
    '실제 투자 또는 발행 의사결정을 대체하지 않습니다.</div>',
    unsafe_allow_html=True,
)
