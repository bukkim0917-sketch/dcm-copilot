import os
import time
import requests
import streamlit as st


# =========================================================
# 1. PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="DCM Copilot",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =========================================================
# 2. N8N WEBHOOK URL
# =========================================================
#
# Streamlit Cloud
# Manage app → Settings → Secrets
#
# 아래 두 값을 등록해야 합니다.
#
START_WEBHOOK_URL = "https://buky87.app.n8n.cloud/webhook/DCM-analysis"
RESULT_WEBHOOK_URL = "https://buky87.app.n8n.cloud/webhook/dcm-result"
#
# 반드시 /webhook-test/ 가 아니라 /webhook/ Production URL 사용
# =========================================================

# =========================================================
# 3. DESIGN / CSS
# =========================================================

st.markdown(
    """
    <style>

    .stApp {
        background-color: #ffffff;
    }

    .block-container {
        max-width: 1100px;
        padding-top: 3rem;
        padding-bottom: 4rem;
    }

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

    .scope-box {
        background: #DCEFFC;
        padding: 14px 16px;
        border-radius: 8px;
        color: #07528C;
        font-size: 14px;
        line-height: 1.8;
        margin-bottom: 18px;
    }

    .result-title {
        font-size: 27px;
        font-weight: 800;
        color: #10294A;
        margin-top: 20px;
        margin-bottom: 12px;
    }

    .disclaimer {
        font-size: 13px;
        color: #69788C;
        line-height: 1.7;
        margin-top: 18px;
    }

    [data-testid="stSidebar"] {
        background-color: #F3F6FA;
    }

    [data-testid="stSidebar"] .block-container {
        padding-top: 2rem;
    }

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
# 4. SESSION STATE
# =========================================================

DEFAULT_STATE = {
    "analysis_result": None,
    "request_id": None,
    "analysis_running": False,
    "analysis_started_at": None,
    "analysis_error": None,
    "last_company": None,
}

for key, value in DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = value


# =========================================================
# 5. QUERY PARAM RECOVERY
# =========================================================
#
# Streamlit이 중간에 전체 rerun되더라도
# URL에 request_id를 남겨 두어 분석 상태를 복구합니다.
# =========================================================

try:
    saved_request_id = st.query_params.get("request_id")
    saved_started_at = st.query_params.get("started_at")

    if (
        saved_request_id
        and not st.session_state.request_id
        and not st.session_state.analysis_result
    ):
        st.session_state.request_id = str(saved_request_id)
        st.session_state.analysis_running = True

        try:
            st.session_state.analysis_started_at = float(saved_started_at)
        except (TypeError, ValueError):
            st.session_state.analysis_started_at = time.time()

except Exception:
    pass


# =========================================================
# 6. N8N API FUNCTIONS
# =========================================================


def start_analysis(payload: dict) -> str:
    """
    메인 OpenDART Financial Analysis Workflow에 요청합니다.

    n8n은 긴 분석을 기다리지 않고
    Return Job ID 노드에서 request_id만 즉시 반환합니다.
    """

    if not START_WEBHOOK_URL:
        raise RuntimeError(
            "START_WEBHOOK_URL이 설정되지 않았습니다.\n"
            "Streamlit Settings → Secrets를 확인해주세요."
        )

    try:
        response = requests.post(
            START_WEBHOOK_URL,
            json=payload,
            timeout=30,
        )

    except requests.exceptions.Timeout:
        raise RuntimeError(
            "분석 시작 Webhook 응답이 30초 안에 오지 않았습니다. "
            "n8n의 Return Job ID가 긴 분석보다 먼저 실행되는지 확인해주세요."
        )

    response.raise_for_status()

    try:
        data = response.json()

    except ValueError:
        raise RuntimeError(
            "분석 시작 Webhook이 JSON을 반환하지 않았습니다.\n"
            f"응답: {response.text[:500]}"
        )

    request_id = data.get("request_id")

    if request_id is None or str(request_id).strip() == "":
        raise RuntimeError(
            "n8n에서 request_id를 받지 못했습니다.\n"
            f"응답: {data}"
        )

    return str(request_id)


def get_analysis_result(request_id: str) -> dict:
    """
    DCM Result Lookup Workflow에 request_id를 보내
    Data Table의 현재 상태를 조회합니다.
    """

    if not RESULT_WEBHOOK_URL:
        raise RuntimeError(
            "RESULT_WEBHOOK_URL이 설정되지 않았습니다.\n"
            "Streamlit Settings → Secrets를 확인해주세요."
        )

    response = requests.get(
        RESULT_WEBHOOK_URL,
        params={"request_id": request_id},
        timeout=20,
    )

    response.raise_for_status()

    # Data Table에서 아직 행을 찾지 못했거나
    # 빈 응답이 올 경우 processing으로 간주
    if not response.text.strip():
        return {
            "status": "processing",
            "result": "",
        }

    try:
        data = response.json()

    except ValueError:
        raise RuntimeError(
            "결과 조회 Webhook이 JSON을 반환하지 않았습니다.\n"
            f"응답: {response.text[:500]}"
        )

    # n8n 설정에 따라 배열로 반환되는 경우 대응
    if isinstance(data, list):

        if len(data) == 0:
            return {
                "status": "processing",
                "result": "",
            }

        data = data[0]

    if not isinstance(data, dict):
        return {
            "status": "processing",
            "result": "",
        }

    return data


# =========================================================
# 7. ANALYSIS STATUS FRAGMENT
# =========================================================
#
# 기존 while True 방식은 사용하지 않습니다.
#
# 이 fragment만 5초마다 짧게 실행됩니다.
# 따라서 5~15분짜리 n8n 실행을 Streamlit Python 실행 하나가
# 계속 붙잡고 있지 않습니다.
# =========================================================


@st.fragment(run_every="60s")
def poll_analysis():

    if not st.session_state.analysis_running:
        return

    request_id = st.session_state.request_id

    if not request_id:
        return

    # ---------------------------------------------
    # 경과 시간 계산
    # ---------------------------------------------

    started_at = st.session_state.analysis_started_at

    if started_at is None:
        started_at = time.time()
        st.session_state.analysis_started_at = started_at

    elapsed = max(
        0,
        int(time.time() - float(started_at))
    )

    minutes = elapsed // 60
    seconds = elapsed % 60

    # ---------------------------------------------
    # 상태 UI
    # ---------------------------------------------

    st.info(
        "🔎 공개자료를 최대한 확인하며 분석하고 있습니다. "
        f"현재 {minutes}분 {seconds}초 경과"
    )

    # 실제 n8n 진행률이 아니라 참고용 시간 진행률
    estimated_seconds = 600

    progress = min(
        int((elapsed / estimated_seconds) * 100),
        95,
    )

    st.progress(progress)

    st.caption(
        "재무제표·채무구조·신용등급·회사채·시장금리·"
        "CAPEX 등 공개자료를 확인하고 있습니다. "
        "진행바는 예상시간 기준 참고용입니다."
    )

    # ---------------------------------------------
    # 결과 조회
    # ---------------------------------------------

    try:
        data = get_analysis_result(request_id)

    except requests.exceptions.RequestException:
        st.warning(
            "결과 조회 과정에서 일시적인 연결 오류가 발생했습니다. "
            "5초 후 자동으로 다시 확인합니다."
        )
        return

    except Exception as e:
        st.warning(
            "결과를 확인하는 중 일시적인 오류가 발생했습니다. "
            f"자동으로 다시 확인합니다. ({e})"
        )
        return

    status = str(
        data.get("status", "")
    ).strip().lower()

    # ---------------------------------------------
    # 완료
    # ---------------------------------------------

    if status == "completed":

        result = data.get("result")

        if result is None:
            result = ""

        st.session_state.analysis_result = result
        st.session_state.analysis_running = False
        st.session_state.analysis_error = None

        try:
            st.query_params.clear()
        except Exception:
            pass

        st.rerun()
        return

    # ---------------------------------------------
    # 실패
    # ---------------------------------------------

    if status in (
        "error",
        "failed",
        "failure",
    ):

        error_message = (
            data.get("result")
            or data.get("error")
            or "n8n 분석 과정에서 오류가 발생했습니다."
        )

        st.session_state.analysis_error = str(error_message)
        st.session_state.analysis_running = False

        try:
            st.query_params.clear()
        except Exception:
            pass

        st.rerun()
        return

    # 그 외:
    # processing / queued / started / 빈 값
    # → 아무것도 하지 않고 5초 후 다시 확인


# =========================================================
# 8. SIDEBAR
# =========================================================

with st.sidebar:

    st.markdown("## 발행기업 정보 입력")

    company_name = st.text_input(
        "기업명",
        value="LG디스플레이",
        help="분석 대상 기업명을 입력하세요.",
    )

    corp_code = st.text_input(
        "DART corp_code",
        value="00105873",
        help="OpenDART 기업 고유번호 8자리를 입력하세요.",
    )

    st.markdown("### 분석 범위")

    st.markdown(
        """
        <div class="scope-box">
        <b>분석기간:</b> 2025.01.01 ~ 2026.06.30<br>
        <b>분석기준일:</b> 2026.06.30
        </div>
        """,
        unsafe_allow_html=True,
    )

    funding_amount = st.text_input(
        "조달예정금액",
        value="3000억원",
        help="예: 3000억원",
    )

    funding_purpose = st.text_area(
        "조달목적",
        value="차환 및 운영자금",
        height=130,
        help=(
            "사용자가 예상하는 자금조달 목적입니다. "
            "최종 분석에서는 설비투자·운전자금·차환을 모두 검토합니다."
        ),
    )

    # 분석 중에는 중복 Analyze 방지
    analyze_clicked = st.button(
        "Analyze",
        type="primary",
        use_container_width=True,
        disabled=st.session_state.analysis_running,
    )

    # 분석 진행 중일 때 현재 Job 표시
    if st.session_state.analysis_running:
        st.caption(
            f"현재 분석 Job ID: "
            f"{st.session_state.request_id}"
        )

    # 결과 또는 오류가 있을 때 새 분석 버튼
    if (
        st.session_state.analysis_result is not None
        or st.session_state.analysis_error is not None
    ):

        if st.button(
            "새 분석 시작",
            use_container_width=True,
        ):
            st.session_state.analysis_result = None
            st.session_state.request_id = None
            st.session_state.analysis_running = False
            st.session_state.analysis_started_at = None
            st.session_state.analysis_error = None
            st.session_state.last_company = None

            try:
                st.query_params.clear()
            except Exception:
                pass

            st.rerun()


# =========================================================
# 9. MAIN HEADER
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
    """
    <div class="sub-title">
    AI-POWERED CORPORATE FUNDING ANALYSIS
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="section-line"></div>',
    unsafe_allow_html=True,
)


# =========================================================
# 10. ANALYZE REQUEST
# =========================================================

if analyze_clicked:

    # ---------------------------------------------
    # 이전 상태 초기화
    # ---------------------------------------------

    st.session_state.analysis_result = None
    st.session_state.analysis_error = None
    st.session_state.request_id = None
    st.session_state.analysis_running = False
    st.session_state.analysis_started_at = None

    # ---------------------------------------------
    # Payload
    # ---------------------------------------------
    #
    # 분석범위:
    # 2025 Annual + 2026 H1
    #
    # n8n에서
    # annual_year / annual_reprt_code
    # half_year / half_reprt_code
    # 를 사용할 수 있도록 함께 전달
    # ---------------------------------------------
st.write("DEBUG funding_purpose:", repr(funding_purpose))
    payload = {
        "company_name": company_name.strip(),
        "corp_code": corp_code.strip(),

        "analysis_start_date": "2025-01-01",
        "analysis_end_date": "2026-06-30",
        "analysis_base_date": "2026-06-30",

        # 2025 사업보고서
        "annual_year": 2025,
        "annual_reprt_code": "11011",

        # 2026 반기보고서
        "half_year": 2026,
        "half_reprt_code": "11012",

        "funding_amount": funding_amount.strip(),
        "funding_purpose": funding_purpose.strip(),
    }

    # ---------------------------------------------
    # 필수값 확인
    # ---------------------------------------------

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

            with st.spinner(
                "n8n에 분석 요청을 등록하고 있습니다..."
            ):

                request_id = start_analysis(payload)

            # -------------------------------------
            # Job 상태 저장
            # -------------------------------------

            started_at = time.time()

            st.session_state.request_id = str(request_id)
            st.session_state.analysis_running = True
            st.session_state.analysis_started_at = started_at
            st.session_state.last_company = company_name

            # -------------------------------------
            # URL에도 저장
            #
            # Streamlit 전체 rerun / 새로고침이 발생해도
            # 진행 중 Job을 복구하기 위한 장치
            # -------------------------------------

            try:
                st.query_params["request_id"] = str(request_id)
                st.query_params["started_at"] = str(started_at)
            except Exception:
                pass

            st.rerun()

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

            st.session_state.analysis_error = (
                "n8n Webhook 호출 중 HTTP 오류가 발생했습니다.\n\n"
                f"상태 코드: {status_code}\n\n"
                f"{response_text}"
            )

            st.session_state.analysis_running = False
            st.rerun()

        except Exception as e:

            st.session_state.analysis_error = str(e)
            st.session_state.analysis_running = False
            st.rerun()


# =========================================================
# 11. MAIN CONTENT
# =========================================================

if st.session_state.analysis_running:

    poll_analysis()


elif st.session_state.analysis_error:

    st.error(
        "분석 중 오류가 발생했습니다.\n\n"
        f"{st.session_state.analysis_error}"
    )


elif st.session_state.analysis_result is not None:

    st.success(
        "✅ 공개자료 조사가 완료되었습니다."
    )

    st.markdown(
        """
        <div class="result-title">
        기업 자금조달 분석 결과
        </div>
        """,
        unsafe_allow_html=True,
    )

    result = st.session_state.analysis_result

    if isinstance(result, str):

        if result.strip():
            st.markdown(result)
        
        else:
            st.warning(
                "분석은 완료되었지만 최종 결과가 비어 있습니다. "
                "n8n의 Update Job Result 노드를 확인해주세요."
            )

    else:
        st.json(result)


else:

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
# 12. FOOTER
# =========================================================

st.markdown(
    '<div class="section-line"></div>',
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="disclaimer">
    본 도구는 공개 공시자료와 공개 웹자료를 기반으로
    기업의 자금조달 니즈를 분석하는 보조 도구이며
    실제 투자 또는 발행 의사결정을 대체하지 않습니다.
    </div>
    """,
    unsafe_allow_html=True,
)
