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
    st.sidebar.caption("FastAPI backend with local sentence-transformers + FAISS retrieval.")
    st.sidebar.metric("Benefit rows", selected_plan["benefit_count"])
    st.sidebar.metric("Categories", selected_plan["category_count"])
    st.sidebar.metric("Sections", selected_plan["section_count"])
    st.sidebar.caption(
        "Retrieval mode: vector index"
        if selected_plan["vector_enabled"]
        else "Retrieval mode: keyword fallback"
    )

    st.title(APP_NAME)
    st.caption(
        "Ask coverage questions about the selected plan or start a claim draft in chat."
    )

    with st.container():
        st.markdown(f"**Selected plan:** `{selected_plan['display_name']}`")
        st.markdown(
            "Try: `Does my insurance cover MRI?`, "
            "`What is the maternity consultant fee cover?`, or "
            "`I want to file a claim for physiotherapy`."
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
    st.error("FastAPI backend is not reachable.")
    st.code("uvicorn backend.server:app --host 0.0.0.0 --port 8000", language="bash")
    st.caption("After the API is running, restart the Streamlit UI.")


def _apply_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(229, 241, 255, 0.9), transparent 35%),
                linear-gradient(180deg, #f6fbff 0%, #eef5f1 100%);
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
        }
        [data-testid="stSidebar"] * {
            color: #e2e8f0;
        }
        div[data-testid="stChatMessage"] {
            border-radius: 18px;
            border: 1px solid rgba(15, 23, 42, 0.08);
            box-shadow: 0 18px 50px rgba(15, 23, 42, 0.06);
            background: rgba(255, 255, 255, 0.78);
            backdrop-filter: blur(8px);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
