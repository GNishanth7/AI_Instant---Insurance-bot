from __future__ import annotations

import html
import json
from uuid import uuid4

import streamlit as st

from client import ApiError, BackendUnavailableError, PolicyApiClient
from config import API_BASE_URL, APP_NAME, MAX_QUESTION_LENGTH, STARTER_QUICK_REPLIES


st.set_page_config(
    page_title=APP_NAME,
    layout="wide",
    initial_sidebar_state="expanded",
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
    plan_ids = list(plan_lookup.keys())
    selected_plan_id = _render_sidebar_plan_picker(plan_lookup, plan_ids)
    _ensure_session_state(selected_plan_id)

    try:
        selected_plan = client.get_plan(selected_plan_id)
    except (BackendUnavailableError, ApiError) as exc:
        st.error(str(exc))
        return

    show_debug = _render_sidebar_controls(client, selected_plan)
    _render_header(selected_plan)
    _render_messages(show_debug)

    quick_reply = _render_quick_reply_bar(_current_quick_replies())
    user_input = st.chat_input("Ask about cover, or tap a reply below to continue the claim flow.")
    submitted_message = quick_reply or user_input
    if submitted_message:
        _submit_message(client, selected_plan_id, submitted_message)


def _render_sidebar_plan_picker(plan_lookup: dict[str, dict], plan_ids: list[str]) -> str:
    st.sidebar.markdown(
        """
        <div class="sidebar-brand">
            <div class="sidebar-brand__eyebrow">Control Room</div>
            <div class="sidebar-brand__title">Plan Assistant</div>
            <div class="sidebar-brand__copy">Private-by-default coverage lookup and claim drafting.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    default_plan_id = st.session_state.get("selected_plan_id", plan_ids[0])
    default_index = plan_ids.index(default_plan_id) if default_plan_id in plan_ids else 0
    return st.sidebar.selectbox(
        "Policy Plan",
        options=plan_ids,
        index=default_index,
        format_func=lambda plan_id: plan_lookup[plan_id]["display_name"],
    )


def _render_sidebar_controls(client: PolicyApiClient, selected_plan: dict) -> bool:
    with st.sidebar:
        st.markdown(
            """
            <div class="sidebar-section-label">Actions</div>
            """,
            unsafe_allow_html=True,
        )
        rebuild_requested = st.button("Rebuild index", use_container_width=True)
        reset_requested = st.button("New conversation", use_container_width=True)
        show_debug = st.checkbox("Show retrieved sources", value=False)

        if rebuild_requested:
            try:
                with st.spinner("Rebuilding the selected plan index..."):
                    client.rebuild_plan(selected_plan["id"])
                st.success("Index rebuilt.")
            except (BackendUnavailableError, ApiError) as exc:
                st.error(str(exc))

        if reset_requested:
            _reset_conversation(client)

        st.markdown(
            """
            <div class="sidebar-section-label">Plan Snapshot</div>
            """,
            unsafe_allow_html=True,
        )
        stat_1, stat_2 = st.columns(2)
        stat_1.metric("Benefits", selected_plan["benefit_count"])
        stat_2.metric("Sections", selected_plan["section_count"])
        st.metric("Categories", selected_plan["category_count"])
        retrieval_label = "Vector index" if selected_plan["vector_enabled"] else "Keyword fallback"
        st.markdown(
            f"""
            <div class="sidebar-note">
                <strong>Retrieval mode</strong><br>
                {html.escape(retrieval_label)}
            </div>
            <div class="sidebar-note">
                <strong>Runtime</strong><br>
                Local embeddings + FAISS + deterministic answers
            </div>
            """,
            unsafe_allow_html=True,
        )

    return show_debug


def _render_header(selected_plan: dict) -> None:
    plan_name = html.escape(selected_plan["display_name"])
    retrieval_mode = "Vector index" if selected_plan["vector_enabled"] else "Keyword fallback"
    st.markdown(
        f"""
        <section class="hero-shell">
            <div class="hero-shell__badges">
                <span class="hero-badge">Local only</span>
                <span class="hero-badge hero-badge--soft">{html.escape(retrieval_mode)}</span>
                <span class="hero-badge hero-badge--soft">{selected_plan["benefit_count"]} benefit rows</span>
            </div>
            <h1>{html.escape(APP_NAME)}</h1>
            <p>
                Ask direct coverage questions against the selected plan, or start a claim draft and move
                through the next steps using buttons instead of typing where it makes sense.
            </p>
            <div class="hero-shell__grid">
                <div class="hero-panel">
                    <div class="hero-panel__label">Selected plan</div>
                    <div class="hero-panel__value">{plan_name}</div>
                </div>
                <div class="hero-panel">
                    <div class="hero-panel__label">Claim drafting</div>
                    <div class="hero-panel__value">Guided, step-by-step</div>
                </div>
                <div class="hero-panel">
                    <div class="hero-panel__label">Source format</div>
                    <div class="hero-panel__value">JSON plan citations</div>
                </div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_messages(show_debug: bool) -> None:
    for index, message in enumerate(st.session_state.messages):
        role = message["role"]
        role_label = "Policy assistant" if role == "assistant" else "You"
        with st.chat_message(role):
            st.markdown(
                f'<div class="message-kicker message-kicker--{role}">{role_label}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(message["content"])
            if message.get("claim_summary"):
                _render_claim_summary(message["claim_summary"], key_prefix=f"summary-{index}")
            if message.get("citation") or message.get("disclaimer"):
                _render_meta_row(message.get("citation", ""), message.get("disclaimer", ""))
            if show_debug and message.get("sources"):
                with st.expander("Retrieved sources", expanded=False):
                    for source in message["sources"]:
                        st.markdown(
                            f"- `{source['score']}` {source['benefit']}: {source['coverage']}"
                        )
                        st.caption(source["citation"])


def _render_quick_reply_bar(replies: list[str]) -> str | None:
    options = [reply for reply in replies if reply]
    if not options:
        return None

    is_binary = set(options).issubset({"Yes", "No", "Cancel"})
    helper_copy = "Tap a response" if is_binary else "Start faster"
    sub_copy = (
        "Use buttons for the next step, or type a custom reply below."
        if is_binary
        else "Use a starter action or type your own question."
    )
    st.markdown(
        f"""
        <div class="action-shell">
            <div class="action-shell__title">{helper_copy}</div>
            <div class="action-shell__copy">{sub_copy}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    columns = st.columns(len(options))
    for index, reply in enumerate(options):
        if columns[index].button(
            reply,
            key=f"quick-reply-{len(st.session_state.messages)}-{index}",
            use_container_width=True,
        ):
            return reply
    return None


def _submit_message(client: PolicyApiClient, plan_id: str, raw_message: str) -> None:
    cleaned_input = raw_message.strip()
    if not cleaned_input:
        _append_message(role="assistant", content="Please enter a question.")
        st.rerun()

    _append_message(role="user", content=cleaned_input)

    if len(cleaned_input) > MAX_QUESTION_LENGTH:
        _append_message(
            role="assistant",
            content=f"Questions must be {MAX_QUESTION_LENGTH} characters or fewer.",
            quick_replies=_current_quick_replies(fallback=list(STARTER_QUICK_REPLIES)),
        )
        st.rerun()

    try:
        with st.spinner("Checking the selected policy data..."):
            response = client.chat(
                plan_id=plan_id,
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
            "quick_replies": list(STARTER_QUICK_REPLIES),
        }

    _append_message(
        role="assistant",
        content=response["content"],
        citation=response.get("citation", ""),
        sources=response.get("sources", []),
        claim_summary=response.get("claim_summary"),
        disclaimer=response.get("disclaimer", ""),
        quick_replies=response.get("quick_replies", []),
    )
    st.rerun()


def _render_claim_summary(summary: dict, key_prefix: str) -> None:
    fields = [
        ("Treatment", summary.get("claim_type", "Not provided")),
        ("Date of service", summary.get("date_of_service", "Not provided")),
        ("Amount", _format_amount(summary.get("amount_eur"))),
        ("Receipt", _format_bool(summary.get("has_receipt"))),
        ("Covered", _format_bool(summary.get("policy_covered"))),
        ("Coverage source", summary.get("coverage_source", "Not provided")),
        ("Coverage details", summary.get("coverage_details", "Not provided")),
    ]

    st.markdown(
        '<div class="summary-shell__title">Draft claim summary</div>',
        unsafe_allow_html=True,
    )
    for row_index in range(0, len(fields), 2):
        columns = st.columns(2)
        left_label, left_value = fields[row_index]
        columns[0].markdown(
            _summary_card_html(left_label, left_value),
            unsafe_allow_html=True,
        )
        if row_index + 1 < len(fields):
            right_label, right_value = fields[row_index + 1]
            columns[1].markdown(
                _summary_card_html(right_label, right_value),
                unsafe_allow_html=True,
            )


def _render_meta_row(citation: str, disclaimer: str) -> None:
    parts: list[str] = []
    if citation:
        parts.append(
            f'<div class="meta-pill"><span class="meta-pill__label">Source</span>{html.escape(citation)}</div>'
        )
    if disclaimer:
        parts.append(
            f'<div class="meta-pill"><span class="meta-pill__label">Note</span>{html.escape(disclaimer)}</div>'
        )
    if parts:
        st.markdown(
            f'<div class="meta-row">{"".join(parts)}</div>',
            unsafe_allow_html=True,
        )


def _summary_card_html(label: str, value: str) -> str:
    return (
        '<div class="summary-card">'
        f'<div class="summary-card__label">{html.escape(label)}</div>'
        f'<div class="summary-card__value">{html.escape(value)}</div>'
        "</div>"
    )


def _format_amount(value: float | None) -> str:
    if value is None:
        return "Not provided"
    return f"EUR {value:,.2f}"


def _format_bool(value: bool | None) -> str:
    if value is None:
        return "Not provided"
    return "Yes" if value else "No"


def _current_quick_replies(fallback: list[str] | None = None) -> list[str]:
    for message in reversed(st.session_state.messages):
        if message["role"] == "assistant":
            replies = message.get("quick_replies", [])
            if replies:
                return list(replies)
    return list(fallback or STARTER_QUICK_REPLIES)


def _reset_conversation(client: PolicyApiClient) -> None:
    session_id = st.session_state.get("api_session_id")
    if session_id:
        try:
            client.reset_session(session_id)
        except (BackendUnavailableError, ApiError):
            pass

    st.session_state.messages = [_initial_message()]
    st.session_state.api_session_id = str(uuid4())
    st.rerun()


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
            "Pick a starter action below or ask directly about a benefit. "
            "For claims, the next steps will surface as clickable buttons where appropriate."
        ),
        "citation": "",
        "sources": [],
        "claim_summary": None,
        "disclaimer": "",
        "quick_replies": list(STARTER_QUICK_REPLIES),
    }


def _append_message(
    role: str,
    content: str,
    citation: str = "",
    sources: list[dict] | None = None,
    claim_summary: dict | None = None,
    disclaimer: str = "",
    quick_replies: list[str] | None = None,
) -> None:
    st.session_state.messages.append(
        {
            "role": role,
            "content": content,
            "citation": citation,
            "sources": sources or [],
            "claim_summary": claim_summary,
            "disclaimer": disclaimer,
            "quick_replies": quick_replies or [],
        }
    )


def _render_backend_unavailable() -> None:
    _apply_styles()
    st.markdown(
        """
        <section class="hero-shell hero-shell--empty">
            <div class="hero-shell__badges">
                <span class="hero-badge hero-badge--soft">Backend offline</span>
            </div>
            <h1>FastAPI backend is not reachable</h1>
            <p>Start the API first, then reload the UI.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    st.code("uvicorn backend.server:app --host 0.0.0.0 --port 8000", language="bash")


def _apply_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --ink: #17332d;
            --ink-soft: #557068;
            --pine: #12372f;
            --pine-deep: #0b201d;
            --card: rgba(255, 252, 246, 0.86);
            --card-strong: rgba(255, 255, 255, 0.92);
            --line: rgba(23, 51, 45, 0.12);
            --mist: #f7f2e8;
            --sage: #dce9df;
            --clay: #b86436;
            --clay-soft: rgba(184, 100, 54, 0.12);
        }

        .stApp {
            background:
                radial-gradient(circle at top left, rgba(206, 230, 218, 0.85), transparent 26%),
                radial-gradient(circle at top right, rgba(245, 212, 190, 0.65), transparent 30%),
                linear-gradient(180deg, #f9f5ef 0%, #eef3ed 100%);
            color: var(--ink);
            font-family: "Aptos", "Segoe UI Variable", "Trebuchet MS", sans-serif;
        }

        .stApp h1, .stApp h2, .stApp h3 {
            color: var(--ink);
            font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
            letter-spacing: -0.03em;
        }

        .stApp p, .stApp li, .stApp label {
            color: var(--ink);
        }

        [data-testid="stSidebar"] {
            background:
                radial-gradient(circle at top, rgba(90, 142, 119, 0.28), transparent 34%),
                linear-gradient(180deg, var(--pine) 0%, var(--pine-deep) 100%);
            border-right: 1px solid rgba(255, 255, 255, 0.08);
        }

        [data-testid="stSidebar"] * {
            color: #edf5f1;
        }

        .sidebar-brand {
            padding: 0.3rem 0 1.1rem;
        }

        .sidebar-brand__eyebrow,
        .sidebar-section-label {
            font-size: 0.72rem;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: rgba(237, 245, 241, 0.72);
            margin-bottom: 0.35rem;
        }

        .sidebar-brand__title {
            font-size: 1.45rem;
            font-weight: 700;
            margin-bottom: 0.4rem;
        }

        .sidebar-brand__copy {
            color: rgba(237, 245, 241, 0.78);
            line-height: 1.55;
            font-size: 0.94rem;
        }

        .sidebar-note {
            border: 1px solid rgba(255, 255, 255, 0.12);
            background: rgba(255, 255, 255, 0.06);
            border-radius: 18px;
            padding: 0.9rem 1rem;
            margin-top: 0.7rem;
            line-height: 1.5;
        }

        .sidebar-note strong {
            display: block;
            font-size: 0.74rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            margin-bottom: 0.25rem;
            color: rgba(237, 245, 241, 0.66);
        }

        [data-testid="stSidebar"] div.stButton > button {
            background: linear-gradient(135deg, #f2e8d6 0%, #ffffff 100%);
            color: var(--pine-deep);
            border: none;
            border-radius: 999px;
            font-weight: 700;
            min-height: 3rem;
            box-shadow: 0 16px 30px rgba(2, 6, 23, 0.18);
        }

        [data-testid="stSidebar"] div.stButton > button:hover {
            background: linear-gradient(135deg, #ffffff 0%, #f7e4d6 100%);
            color: #7f431e;
        }

        [data-testid="stSidebar"] [data-testid="stMetricValue"] {
            color: #ffffff;
            font-size: 1.45rem;
            font-weight: 700;
        }

        [data-testid="stSidebar"] [data-testid="stMetricLabel"] {
            color: rgba(237, 245, 241, 0.7);
            font-size: 0.74rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
        }

        [data-testid="stSidebar"] .stCheckbox label {
            color: rgba(237, 245, 241, 0.92);
        }

        .hero-shell {
            border: 1px solid rgba(18, 55, 47, 0.12);
            border-radius: 30px;
            padding: 1.7rem 1.8rem 1.5rem;
            background:
                radial-gradient(circle at top right, rgba(255, 255, 255, 0.34), transparent 24%),
                linear-gradient(135deg, rgba(18, 55, 47, 0.98) 0%, rgba(33, 82, 71, 0.96) 58%, rgba(184, 100, 54, 0.93) 100%);
            box-shadow: 0 28px 60px rgba(17, 39, 34, 0.18);
            color: #f7fbf8;
            margin-bottom: 1.1rem;
        }

        .hero-shell--empty {
            margin-top: 1rem;
        }

        .hero-shell h1,
        .hero-shell p {
            color: #f7fbf8;
        }

        .hero-shell h1 {
            margin: 0.2rem 0 0.45rem;
            font-size: clamp(2.1rem, 4vw, 3.2rem);
        }

        .hero-shell p {
            max-width: 56rem;
            line-height: 1.65;
            font-size: 1rem;
            margin-bottom: 1.15rem;
        }

        .hero-shell__badges {
            display: flex;
            gap: 0.55rem;
            flex-wrap: wrap;
        }

        .hero-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            border-radius: 999px;
            padding: 0.42rem 0.8rem;
            background: rgba(255, 255, 255, 0.16);
            border: 1px solid rgba(255, 255, 255, 0.14);
            font-size: 0.76rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: #fef6f0;
        }

        .hero-badge--soft {
            background: rgba(17, 39, 34, 0.24);
        }

        .hero-shell__grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.85rem;
        }

        .hero-panel {
            background: rgba(255, 255, 255, 0.12);
            border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 20px;
            padding: 1rem 1.05rem;
            backdrop-filter: blur(8px);
        }

        .hero-panel__label {
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: rgba(247, 251, 248, 0.72);
            margin-bottom: 0.45rem;
        }

        .hero-panel__value {
            font-size: 1rem;
            font-weight: 700;
            color: #fdf9f6;
            line-height: 1.45;
        }

        div[data-testid="stChatMessage"] {
            background: var(--card-strong);
            border: 1px solid var(--line);
            border-radius: 24px;
            padding: 0.25rem 0.3rem;
            box-shadow: 0 18px 38px rgba(23, 51, 45, 0.08);
            margin-bottom: 0.8rem;
        }

        .message-kicker {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            border-radius: 999px;
            padding: 0.28rem 0.62rem;
            margin-bottom: 0.35rem;
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            font-weight: 700;
        }

        .message-kicker--assistant {
            background: rgba(18, 55, 47, 0.08);
            color: var(--pine);
        }

        .message-kicker--user {
            background: var(--clay-soft);
            color: #7b421d;
        }

        div[data-testid="stChatMessage"] p,
        div[data-testid="stChatMessage"] li,
        div[data-testid="stChatMessage"] span {
            color: var(--ink);
            line-height: 1.7;
            font-size: 0.97rem;
        }

        .meta-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.55rem;
            margin-top: 0.8rem;
        }

        .meta-pill {
            flex: 1 1 15rem;
            border-radius: 16px;
            border: 1px solid rgba(18, 55, 47, 0.1);
            background: rgba(220, 233, 223, 0.4);
            padding: 0.75rem 0.9rem;
            color: var(--ink);
            font-size: 0.88rem;
            line-height: 1.55;
        }

        .meta-pill__label {
            display: block;
            font-size: 0.68rem;
            font-weight: 700;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: var(--ink-soft);
            margin-bottom: 0.25rem;
        }

        .summary-shell__title {
            margin-top: 0.85rem;
            margin-bottom: 0.45rem;
            font-size: 0.76rem;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: var(--ink-soft);
            font-weight: 700;
        }

        .summary-card {
            border: 1px solid rgba(18, 55, 47, 0.1);
            background: linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(247, 242, 232, 0.92) 100%);
            border-radius: 20px;
            padding: 0.95rem 1rem;
            min-height: 6.5rem;
            margin-bottom: 0.75rem;
        }

        .summary-card__label {
            font-size: 0.72rem;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: var(--ink-soft);
            margin-bottom: 0.45rem;
            font-weight: 700;
        }

        .summary-card__value {
            font-size: 0.98rem;
            line-height: 1.55;
            color: var(--ink);
            font-weight: 600;
        }

        .action-shell {
            display: flex;
            flex-direction: column;
            gap: 0.2rem;
            margin: 0.3rem 0 0.8rem;
            padding: 1rem 1.1rem;
            border-radius: 20px;
            border: 1px solid rgba(18, 55, 47, 0.1);
            background: rgba(255, 255, 255, 0.68);
            box-shadow: 0 12px 28px rgba(23, 51, 45, 0.06);
        }

        .action-shell__title {
            font-size: 0.76rem;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: var(--ink-soft);
            font-weight: 700;
        }

        .action-shell__copy {
            color: var(--ink);
            font-size: 0.96rem;
        }

        div.stButton > button {
            min-height: 3rem;
            border-radius: 999px;
            border: 1px solid rgba(18, 55, 47, 0.12);
            background: linear-gradient(180deg, rgba(255, 255, 255, 0.96) 0%, rgba(247, 242, 232, 0.92) 100%);
            color: var(--pine);
            font-weight: 700;
            box-shadow: 0 12px 24px rgba(23, 51, 45, 0.08);
            white-space: normal;
            line-height: 1.3;
        }

        div.stButton > button:hover {
            border-color: rgba(184, 100, 54, 0.35);
            color: #7b421d;
            background: linear-gradient(180deg, #ffffff 0%, #faeee2 100%);
        }

        [data-testid="stChatInput"] {
            background: rgba(255, 255, 255, 0.88);
            border-radius: 22px;
            border: 1px solid rgba(18, 55, 47, 0.12);
            box-shadow: 0 18px 38px rgba(23, 51, 45, 0.08);
        }

        [data-testid="stChatInput"] textarea,
        [data-testid="stChatInput"] input {
            color: var(--ink);
        }

        .stExpander {
            border-radius: 18px;
            border: 1px solid rgba(18, 55, 47, 0.1);
            background: rgba(255, 255, 255, 0.68);
        }

        @media (max-width: 980px) {
            .hero-shell__grid {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
