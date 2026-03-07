from __future__ import annotations

import json
from uuid import uuid4

import streamlit as st

from client import ApiError, BackendUnavailableError, PolicyApiClient
from config import API_BASE_URL, APP_NAME, MAX_QUESTION_LENGTH


st.set_page_config(
    page_title=APP_NAME,
    layout="wide",
)


@st.cache_resource(show_spinner=False)
def get_api_client() -> PolicyApiClient:
    return PolicyApiClient(API_BASE_URL)


def main() -> None:
    _apply_styles()
    client = get_api_client()

    try:
        plans = client.list_plans()
    except BackendUnavailableError:
        _render_backend_unavailable()
        return
    except ApiError as exc:
        st.error(str(exc))
        return

    if not plans:
        st.error("No plan JSON files were found in the working directory.")
        return

    plan_lookup = {plan["id"]: plan for plan in plans}
    selected_plan_id = st.sidebar.selectbox(
        "Select a policy plan",
        options=list(plan_lookup.keys()),
        format_func=lambda plan_id: plan_lookup[plan_id]["display_name"],
    )
    _ensure_session_state(selected_plan_id)

    if st.sidebar.button("Rebuild selected index", use_container_width=True):
        try:
            with st.spinner("Rebuilding the selected plan index..."):
                client.rebuild_plan(selected_plan_id)
            st.sidebar.success("Index rebuilt.")
        except (BackendUnavailableError, ApiError) as exc:
            st.sidebar.error(str(exc))

    try:
        selected_plan = client.get_plan(selected_plan_id)
    except (BackendUnavailableError, ApiError) as exc:
        st.error(str(exc))
        return

    show_debug = st.sidebar.checkbox("Show retrieved sources", value=False)
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        '<p style="font-size:0.7rem;text-transform:uppercase;letter-spacing:1px;'
        'color:#94a3b8;margin-bottom:0.5rem">Plan Stats</p>',
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.sidebar.columns(3)
    c1.metric("Benefits", selected_plan["benefit_count"])
    c2.metric("Categories", selected_plan["category_count"])
    c3.metric("Sections", selected_plan["section_count"])
    st.sidebar.markdown("---")
    st.sidebar.caption("Gemini LLM + FAISS vector retrieval")

    st.markdown(
        '<div style="margin-bottom:0.25rem">'
        '<span style="font-size:2rem;font-weight:700;color:#0f172a;letter-spacing:-0.5px">'
        f'{APP_NAME}</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="color:#64748b;font-size:0.95rem;margin-top:0">'
        'Ask coverage questions about the selected plan or start a claim draft in chat.</p>',
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns(3)
    col1.markdown(
        '<div style="background:#f1f5f9;border-radius:10px;padding:12px 16px;text-align:center;'
        'border:1px solid #e2e8f0">'
        '<span style="font-size:0.75rem;color:#64748b;text-transform:uppercase;letter-spacing:0.5px">'
        'Selected Plan</span><br>'
        f'<span style="font-size:1.05rem;font-weight:600;color:#0f172a">{selected_plan["display_name"]}</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    col2.markdown(
        '<div style="background:#f1f5f9;border-radius:10px;padding:12px 16px;text-align:center;'
        'border:1px solid #e2e8f0">'
        '<span style="font-size:0.75rem;color:#64748b;text-transform:uppercase;letter-spacing:0.5px">'
        'Benefits</span><br>'
        f'<span style="font-size:1.05rem;font-weight:600;color:#0f172a">{selected_plan["benefit_count"]} rows</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    col3.markdown(
        '<div style="background:#f1f5f9;border-radius:10px;padding:12px 16px;text-align:center;'
        'border:1px solid #e2e8f0">'
        '<span style="font-size:0.75rem;color:#64748b;text-transform:uppercase;letter-spacing:0.5px">'
        'Retrieval</span><br>'
        '<span style="font-size:1.05rem;font-weight:600;color:#0f172a">'
        f'{"Vector" if selected_plan["vector_enabled"] else "Keyword"}</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="margin:1rem 0 0.5rem;display:flex;gap:8px;flex-wrap:wrap">'
        '<span style="background:#e0f2fe;color:#0369a1;padding:6px 14px;border-radius:20px;'
        'font-size:0.82rem;cursor:default">Does my insurance cover MRI?</span>'
        '<span style="background:#e0f2fe;color:#0369a1;padding:6px 14px;border-radius:20px;'
        'font-size:0.82rem;cursor:default">What is the maternity consultant fee cover?</span>'
        '<span style="background:#dcfce7;color:#166534;padding:6px 14px;border-radius:20px;'
        'font-size:0.82rem;cursor:default">I want to file a claim for physiotherapy</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    _render_messages(show_debug)

    user_input = st.chat_input("Ask a question about cover, or start a claim draft.")
    if not user_input:
        return

    cleaned_input = user_input.strip()
    _append_message(role="user", content=cleaned_input)

    if not cleaned_input:
        _append_message(role="assistant", content="Please enter a question.")
        st.rerun()

    if len(cleaned_input) > MAX_QUESTION_LENGTH:
        _append_message(
            role="assistant",
            content=f"Questions must be {MAX_QUESTION_LENGTH} characters or fewer.",
        )
        st.rerun()

    try:
        with st.spinner("Checking the selected policy data..."):
            response = client.chat(
                plan_id=selected_plan_id,
                message=cleaned_input,
                session_id=st.session_state.api_session_id,
            )
        st.session_state.api_session_id = response["session_id"]
    except (BackendUnavailableError, ApiError) as exc:
        response = {
            "content": str(exc),
            "citation": "",
            "sources": [],
            "claim_summary": None,
            "disclaimer": "",
        }

    _append_message(
        role="assistant",
        content=response["content"],
        citation=response.get("citation", ""),
        sources=response.get("sources", []),
        claim_summary=response.get("claim_summary"),
        disclaimer=response.get("disclaimer", ""),
    )
    st.rerun()


def _render_messages(show_debug: bool) -> None:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("claim_summary"):
                st.code(
                    json.dumps(message["claim_summary"], indent=2),
                    language="json",
                )
            if message.get("citation"):
                st.caption(f"Source: {message['citation']}")
            if message.get("disclaimer"):
                st.caption(message["disclaimer"])
            if show_debug and message.get("sources"):
                with st.expander("Retrieved sources"):
                    for source in message["sources"]:
                        st.markdown(
                            f"- `{source['score']}` {source['benefit']}: {source['coverage']}"
                        )
                        st.caption(source["citation"])


def _ensure_session_state(selected_plan_id: str) -> None:
    if "selected_plan_id" not in st.session_state:
        st.session_state.selected_plan_id = selected_plan_id

    if "messages" not in st.session_state:
        st.session_state.messages = [_initial_message()]

    if "api_session_id" not in st.session_state:
        st.session_state.api_session_id = str(uuid4())

    if st.session_state.selected_plan_id != selected_plan_id:
        st.session_state.selected_plan_id = selected_plan_id
        st.session_state.messages = [_initial_message()]
        st.session_state.api_session_id = str(uuid4())


def _initial_message() -> dict:
    return {
        "role": "assistant",
        "content": (
            "Ask about coverage in the selected plan, or start with "
            "`I want to file a claim for physiotherapy`."
        ),
        "citation": "",
        "sources": [],
        "claim_summary": None,
        "disclaimer": "",
    }


def _append_message(
    role: str,
    content: str,
    citation: str = "",
    sources: list[dict] | None = None,
    claim_summary: dict | None = None,
    disclaimer: str = "",
) -> None:
    st.session_state.messages.append(
        {
            "role": role,
            "content": content,
            "citation": citation,
            "sources": sources or [],
            "claim_summary": claim_summary,
            "disclaimer": disclaimer,
        }
    )


def _render_backend_unavailable() -> None:
    st.error("Backend is not reachable.")
    st.code("uvicorn backend.server:app --host 0.0.0.0 --port 8000", language="bash")
    st.caption("After the API is running, restart the Streamlit UI.")


def _apply_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        /* ── Global ── */
        .stApp {
            background: #f8fafc;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        }

        /* ── Sidebar ── */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
            border-right: 1px solid rgba(255,255,255,0.06);
        }
        [data-testid="stSidebar"] * {
            color: #cbd5e1;
        }
        [data-testid="stSidebar"] [data-testid="stMetricValue"] {
            color: #f1f5f9 !important;
            font-size: 1.4rem !important;
            font-weight: 700 !important;
        }
        [data-testid="stSidebar"] [data-testid="stMetricLabel"] {
            color: #94a3b8 !important;
            font-size: 0.7rem !important;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        [data-testid="stSidebar"] button {
            background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%) !important;
            color: #fff !important;
            border: none !important;
            border-radius: 10px !important;
            font-weight: 600 !important;
            padding: 0.55rem 1rem !important;
            transition: all 0.2s ease !important;
        }
        [data-testid="stSidebar"] button:hover {
            background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%) !important;
            box-shadow: 0 4px 12px rgba(37,99,235,0.35) !important;
        }
        [data-testid="stSidebar"] hr {
            border-color: rgba(148,163,184,0.15) !important;
        }

        /* ── Chat messages ── */
        div[data-testid="stChatMessage"] {
            border-radius: 16px;
            border: 1px solid #e2e8f0;
            box-shadow: 0 1px 3px rgba(15,23,42,0.04);
            background: #ffffff;
            padding: 1rem 1.25rem;
            margin-bottom: 0.75rem;
        }
        div[data-testid="stChatMessage"] p,
        div[data-testid="stChatMessage"] li,
        div[data-testid="stChatMessage"] span {
            color: #1e293b !important;
            font-size: 0.92rem;
            line-height: 1.65;
        }

        /* ── Chat input ── */
        [data-testid="stChatInput"] {
            border-radius: 14px !important;
            border: 2px solid #e2e8f0 !important;
            background: #ffffff !important;
            box-shadow: 0 2px 8px rgba(15,23,42,0.04) !important;
        }
        [data-testid="stChatInput"]:focus-within {
            border-color: #3b82f6 !important;
            box-shadow: 0 0 0 3px rgba(59,130,246,0.12) !important;
        }

        /* ── Typography ── */
        .stApp h1, .stApp h2, .stApp h3 {
            color: #0f172a !important;
            font-weight: 700 !important;
        }
        .stApp p, .stApp span, .stApp label {
            color: #334155;
        }
        .stApp .stMarkdown code {
            color: #0f172a;
            background: #f1f5f9;
            padding: 2px 7px;
            border-radius: 6px;
            font-size: 0.85rem;
        }

        /* ── Metric cards on main area ── */
        [data-testid="stMetricValue"] {
            color: #0f172a !important;
        }

        /* ── Expander ── */
        details {
            border: 1px solid #e2e8f0 !important;
            border-radius: 10px !important;
            background: #f8fafc !important;
        }

        /* ── Spinner ── */
        .stSpinner > div {
            border-top-color: #3b82f6 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
