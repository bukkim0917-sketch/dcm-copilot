import os
import time
import requests
import streamlit as st


# =========================================================
# 1. 기본 설정
# =========================================================

st.set_page_config(
    page_title="DCM Copilot",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =========================================================
# 2. n8n Webhook URL
# =========================================================
#
# Streamlit Cloud를 사용한다면
# Settings → Secrets에 아래처럼 넣는 것을 권장합니다.
#
# START_WEBHOOK_URL = "https://buky87.app.n8n.cloud/webhook/DCM-analysis"
# RESULT_WEBHOOK_URL = "https://buky87.app.n8n.cloud/webhook/dcm-result"
#
# =========================================================

try:
    START_WEBHOOK_URL = st.secrets.get(
        "START_WEBHOOK_URL",
        os.getenv("START_WEBHOOK_URL", "https://buky87.app.n8n.cloud/webhook/DCM-analysis")
    )

    RESULT_WEBHOOK_URL = st.secrets.get(
        "RESULT_WEBHOOK_URL",
        os.getenv("RESULT_WEBHOOK_URL", "https://buky87.app.n8n.cloud/webhook/dcm-result")
    )

except Exception:
    START_WEBHOOK_URL = os.getenv("START_WEBHOOK_URL", "https://buky87.app.n8n.cloud/webhook/DCM-analysis")
    RESULT_WEBHOOK_URL = os.getenv("RESULT_WEBHOOK_URL", "https://buky87.app.n8n.cloud/webhook/dcm-result")


# =========================================================
# 3. CSS
# =========================================================

st.markdown(
    """
    <style>

    /* 전체 */
    .stApp {
        background-color: #ffffff;
    }

    /* 메인 영역 최대 폭 */
    .block-container {
        max-width: 1100px;
        padding-top: 3.0rem;
        padding-bottom: 4rem;
    }

    /* 제목 */
    .main-title {
        font-size: 46px;
        font-weight: 800;
        color: #10294A;
        margin-bottom: 2px;
        letter-spacing: -1.2px;
    }

    .sub-title {
        font-size: 17px;
        font-weight: 500;
        color: #65758B;
        letter-spacing: 1.5px;
        margin-bottom: 26px;
    }

    .top-line {
        border-top: 4px solid #10294A;
        margin-bottom: 28px;
    }

    .section-line {
        border-top: 1px solid #DCE3EA;
        margin-top: 24px;
        margin-bottom: 18px;
    }

    /* 안내 박스 */
    .info-box {
        background: #EAF4FC;
        padding: 22px 26px;
        border-radius: 10px;
        color: #07528C;
        font-weight: 700;
        font-size: 17px;
        line-height: 1.7;
        margin-top: 8px;
        margin-bottom: 28px;
    }

    /* 결과 */
    .result-title {
        font-size: 27px;
        font-weight: 800;
        color: #10294A;
        margin-top: 20px;
        margin-bottom: 12px;
    }

    /* 면책 */
    .disclaimer {
        font-size: 13px;
        color: #69788C;
        line-height: 1.7;
        margin-top: 18px;
    }

    /* 사이드바 */
    [data-testid="stSidebar"] {
        background-color: #F3F6FA;
    }

    [data-testid="stSidebar"] .block-container {
        padding-top: 2rem;
    }

    /* 버튼 */
    div.stButton > button {
        width: 100%;
        border-radius: 8px;
        min-height: 52px;
        font-size: 17px;
        font-weight: 700;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# =========================================================
# 4. 상태 초기화
# =========================================================

if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None

if "request_id" not in st.session_state:
    st.session_state.request_id = None

if "last_company" not in st.session_state:
    st.session_state.last_company = None


# =========================================================
# 5. n8n 통신 함수
# =========================================================

def start_analysis(payload: dict) -> str:
    """
    분석용 n8n Workflow에 요청을 보내고
    즉시 request_id를 받아옵니다.
    """

    if not START_WEBHOOK_URL:
        raise RuntimeError(
            "START_WEBHOOK_URL이 설정되지 않았습니다."
        )

    response = requests.post(
        START_WEBHOOK_URL,
        json=payload,
        timeout=30,
    )

    response.raise_for_status()

    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(
            f"분석 시작 Webhook이 JSON을 반환하지 않았습니다. "
            f"응답 내용: {response.text[:500]}"
        )

    request_id = data.get("request_id")
    status = data.get("status")

    if not request_id:
        raise RuntimeError(
            f"n8n에서 request_id를 받지 못했습니다.\n응답: {data}"
        )

    if status not in (None, "processing", "queued", "started"):
        raise RuntimeError(
            f"분석 요청 상태가 예상과 다릅니다.\n응답: {data}"
        )

    return str(request_id)


def get_analysis_result(request_id: str) -> dict:
    """
    Result Lookup Workflow를 호출해
    현재 분석 상태를 확인합니다.
    """

    if not RESULT_WEBHOOK_URL:
        raise RuntimeError(
            "RESULT_WEBHOOK_URL이 설정되지 않았습니다."
        )

    response = requests.get(
        RESULT_WEBHOOK_URL,
        params={
            "request_id": request_id
        },
        timeout=30,
    )

    response.raise_for_status()

    # n8n Get row(s) 결과가 없는 경우를 대비
    if not response.text.strip():
        return {
            "status": "processing",
            "result": ""
        }

    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(
            f"결과 조회 Webhook이 JSON을 반환하지 않았습니다. "
            f"응답 내용: {response.text[:500]}"
        )

    # 혹시 배열 형태로 반환될 경우도 대응
    if isinstance(data, list):
        if len(data) == 0:
            return {
                "status": "processing",
                "result": ""
            }

        data = data[0]

    return data


def wait_for_analysis(
    request_id: str,
    max_wait_seconds: int = 900,
    poll_interval: int = 5,
):
    """
    n8n 분석이 끝날 때까지 주기적으로 조회합니다.
    기본 최대 대기시간: 15분
    """

    started_at = time.time()

    status_container = st.empty()
    progress_bar = st.progress(0)

    while True:

        elapsed = int(time.time() - started_at)

        if elapsed > max_wait_seconds:
            progress_bar.empty()
            status_container.empty()

            raise TimeoutError(
                "15분 동안 분석이 완료되지 않았습니다. "
                "n8n Executions에서 해당 실행 상태를 확인해주세요."
            )

        # 예상 8분 기준으로 진행률 표시
        estimated_seconds = 480

        progress = min(
            int((elapsed / estimated_seconds) * 100),
            95
        )

        progress_bar.progress(progress)

        minutes = elapsed // 60
        seconds = elapsed % 60

        status_container.info(
            f"🔎 공개자료를 최대한 확인하며 분석하고 있습니다. "
            f"현재 {minutes}분 {seconds}초 경과"
        )

        try:
            data = get_analysis_result(request_id)

        except requests.exceptions.RequestException:
            # 조회 요청 자체가 한 번 실패해도
            # 전체 분석을 즉시 중단하지 않고 다음 polling 때 재시도
            time.sleep(poll_interval)
            continue

        status = str(data.get("status", "")).lower().strip()

        if status == "completed":

            progress_bar.progress(100)

            status_container.success(
                "✅ 공개자료 조사가 완료되었습니다."
            )

            result = data.get("result")

            if result is None:
                result = ""

            return result

        if status in ("error", "failed", "failure"):

            progress_bar.empty()
            status_container.empty()

            error_message = (
                data.get("result")
                or data.get("error")
                or "n8n 분석 과정에서 오류가 발생했습니다."
            )

            raise RuntimeError(error_message)

        time.sleep(poll_interval)


# =========================================================
# 6. 사이드바 - 기업정보 입력
# =========================================================

with st.sidebar:

    st.markdown("## 발행기업 정보 입력")

    company_name = st.text_input(
        "기업명",
        value="LG디스플레이",
        help="분석 대상 기업명을 입력하세요."
    )

    corp_code = st.text_input(
        "DART corp_code",
        value="00105873",
        help="OpenDART 고유번호 8자리를 입력하세요."
    )

    year = st.number_input(
        "분석연도",
        min_value=2015,
        max_value=2035,
        value=2025,
        step=1,
    )
    report_period = st.selectbox(
    "분석기간",
    options=[
        "사업보고서(연간)",
        "반기보고서",
        "1분기보고서",
        "3분기보고서",
    ],
    index=0,
)

report_code_map = {
    "사업보고서(연간)": "11011",
    "반기보고서": "11012",
    "1분기보고서": "11013",
    "3분기보고서": "11014",
}

reprt_code = report_code_map[report_period]

    funding_amount = st.text_input(
        "조달예정금액",
        value="3000억원",
        help="예: 3000억원"
    )

    funding_purpose = st.text_area(
        "조달목적",
        value="차환 및 운영자금",
        height=130,
        help=(
            "사용자가 예상하는 목적을 입력하세요. "
            "최종 분석에서는 설비투자·운전자금·차환을 모두 검토합니다."
        ),
    )

    analyze_clicked = st.button(
        "Analyze",
        type="primary",
        use_container_width=True,
    )


# =========================================================
# 7. 메인 화면
# =========================================================

st.markdown(
    '<div class="top-line"></div>',
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="main-title">DCM Copilot</div>',
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="sub-title">'
    'AI-POWERED CORPORATE FUNDING ANALYSIS'
    '</div>',
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="section-line"></div>',
    unsafe_allow_html=True,
)


# =========================================================
# 8. Analyze 실행
# =========================================================

if analyze_clicked:

    # 이전 결과 초기화
    st.session_state.analysis_result = None
    st.session_state.request_id = None

payload = {
    "company_name": company_name.strip(),
    "corp_code": corp_code.strip(),
    "year": int(year),
    "report_period": report_period,
    "reprt_code": reprt_code,
    "funding_amount": funding_amount.strip(),
    "funding_purpose": funding_purpose.strip(),
}
    # 필수 입력 검증
    missing = []

    if not payload["company_name"]:
        missing.append("기업명")

    if not payload["corp_code"]:
        missing.append("DART corp_code")

    if missing:

        st.error(
            "다음 항목을 입력해주세요: "
            + ", ".join(missing)
        )

    else:

        try:

            # ---------------------------------------------
            # 1) n8n에 분석 시작 요청
            # ---------------------------------------------
            with st.spinner(
                "분석 요청을 등록하고 있습니다..."
            ):

                request_id = start_analysis(payload)

                st.session_state.request_id = request_id
                st.session_state.last_company = company_name


            # ---------------------------------------------
            # 2) 결과 polling
            # ---------------------------------------------
            result = wait_for_analysis(
                request_id=request_id,
                max_wait_seconds=900,
                poll_interval=5,
            )

            st.session_state.analysis_result = result


        except requests.exceptions.Timeout:

            st.error(
                "n8n 서버 연결 시간이 초과되었습니다. "
                "n8n 실행 상태를 확인해주세요."
            )


        except requests.exceptions.HTTPError as e:

            status_code = (
                e.response.status_code
                if e.response is not None
                else "unknown"
            )

            response_text = (
                e.response.text[:500]
                if e.response is not None
                else ""
            )

            st.error(
                f"n8n Webhook 호출 중 HTTP 오류가 발생했습니다.\n\n"
                f"상태 코드: {status_code}\n\n"
                f"{response_text}"
            )


        except Exception as e:

            st.error(
                f"분석 중 오류가 발생했습니다.\n\n{e}"
            )


# =========================================================
# 9. 분석 결과 표시
# =========================================================

if st.session_state.analysis_result:

    st.markdown(
        '<div class="result-title">'
        '기업 자금조달 분석 결과'
        '</div>',
        unsafe_allow_html=True,
    )

    result = st.session_state.analysis_result

    # 문자열이면 Markdown 그대로 출력
    if isinstance(result, str):

        st.markdown(result)

    # 혹시 dict / list 형태가 넘어오면 JSON으로 표시
    else:

        st.json(result)


elif not analyze_clicked:

    st.markdown(
        """
        <div class="info-box">
        좌측에서 기업 정보를 입력하고
        <b>Analyze</b>를 누르면 분석 결과가 표시됩니다.
        </div>
        """,
        unsafe_allow_html=True,
    )


# =========================================================
# 10. 하단 안내
# =========================================================

st.markdown(
    '<div class="section-line"></div>',
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="disclaimer">
    본 도구는 공개 공시자료와 공개 웹자료를 기반으로 기업의
    자금조달 니즈를 분석하는 보조 도구이며 실제 투자 또는
    발행 의사결정을 대체하지 않습니다.
    </div>
    """,
    unsafe_allow_html=True,
)
