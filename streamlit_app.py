import os
import uuid

import requests
import streamlit as st

API_BASE_URL = os.getenv("MANASI_API_URL", "http://localhost:8000")

st.set_page_config(page_title="Manasi — ManaScience AI Guide", page_icon="🧠")

if "session_id" not in st.session_state:
    st.session_state.session_id = "8eb39625-c719-4456-a5d7-a19871e3150a"
if "messages" not in st.session_state:
    st.session_state.messages = []

st.title("🧠 Manasi — ManaScience AI Guide")

with st.sidebar:
    st.subheader("Session")
    st.caption(f"ID: `{st.session_state.session_id[:8]}`")
    if st.button("Reset conversation"):
        try:
            requests.delete(f"{API_BASE_URL}/chat/{st.session_state.session_id}", timeout=10)
        except requests.RequestException:
            pass
        st.session_state.messages = []
        st.rerun()

    st.divider()
    try:
        health = requests.get(f"{API_BASE_URL}/health", timeout=3)
        if health.ok:
            st.success("Backend online")
        else:
            st.error("Backend unhealthy")
    except requests.RequestException:
        st.error("Backend unreachable — start it with:\n\n`venv/bin/uvicorn app.main:app`")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("cta"):
            cta = message["cta"]
            st.link_button(cta["cta_trigger"], cta["cta_url"])
        if message.get("sources"):
            with st.expander("Sources"):
                for source in message["sources"]:
                    st.markdown(f"**{source['source']}**\n\n{source['content']}")

if prompt := st.chat_input("Ask Manasi about ManaScience..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        placeholder.markdown("Thinking...")
        try:
            response = requests.post(
                f"{API_BASE_URL}/chat",
                json={"message": prompt, "session_id": st.session_state.session_id},
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            answer = data["answer"]
            sources = data.get("sources", [])
            cta = data.get("cta")
            placeholder.markdown(answer)
            if cta and cta.get("cta_found"):
                st.link_button(cta["cta_trigger"], cta["cta_url"])
            if sources:
                with st.expander("Sources"):
                    for source in sources:
                        st.markdown(f"**{source['source']}**\n\n{source['content']}")
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": answer,
                    "sources": sources,
                    "cta": cta if cta and cta.get("cta_found") else None,
                }
            )
        except requests.RequestException as exc:
            error_text = f"Could not reach Manasi's backend: {exc}"
            placeholder.markdown(error_text)
            st.session_state.messages.append({"role": "assistant", "content": error_text})
