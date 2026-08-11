import streamlit as st
import requests
from pathlib import Path
from app.core.logger import get_logger

logger = get_logger(__name__)

# Define the FastAPI backend URL
API_BASE_URL = "http://localhost:8000/api/v1"

st.set_page_config(page_title="RAG Chatbot", page_icon="🤖", layout="wide")

# Custom CSS for chat styling
st.markdown("""
<style>
/* User message styling (Right) */
div[data-testid="stChatMessage"]:has(.user-msg) {
    flex-direction: row-reverse;
    background-color: #e6f3ff;
    border: 1px solid #b3d9ff;
    border-radius: 15px;
    padding: 10px 15px;
    margin: 10px 0 10px auto;
    width: fit-content;
    max-width: 80%;
}
div[data-testid="stChatMessage"]:has(.user-msg) div[data-testid="stChatMessageAvatar"] {
    margin-left: 1rem;
    margin-right: 0;
}
div[data-testid="stChatMessage"]:has(.user-msg) .stMarkdown {
    text-align: right;
}

/* Assistant message styling (Left) */
div[data-testid="stChatMessage"]:has(.assistant-msg) {
    background-color: #f8f9fa;
    border: 1px solid #dee2e6;
    border-radius: 15px;
    padding: 10px 15px;
    margin: 10px auto 10px 0;
    width: fit-content;
    max-width: 80%;
}
</style>
""", unsafe_allow_html=True)

st.title("🤖 RAG Chatbot")

# Sidebar for document ingestion
with st.sidebar:
    st.header("Upload Document")
    collection_name = st.selectbox(
        "Select Collection",
        ["warranty", "user_manual", "inspection_report"]
    )
    uploaded_file = st.file_uploader("Choose a file (PDF or XLSX)", type=["pdf", "xlsx"])
    
    if st.button("Ingest Document"):
        if uploaded_file is not None:
            with st.spinner("Ingesting document..."):
                try:
                    logger.info("Uploading '%s' to collection '%s'", uploaded_file.name, collection_name)
                    files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                    params = {"collection_name": collection_name}
                    response = requests.post(f"{API_BASE_URL}/ingest", files=files, params=params)

                    if response.status_code == 200:
                        logger.info("Document '%s' successfully ingested into '%s'", uploaded_file.name, collection_name)
                        st.success(f"Document successfully ingested into '{collection_name}' collection!")
                    else:
                        try:
                            error_detail = response.json().get('detail', 'Unknown error')
                        except Exception as e:
                            logger.exception("Failed to parse ingest error response: %s", e)
                            error_detail = response.text
                        logger.error("Ingestion failed for '%s': %s", uploaded_file.name, error_detail)
                        st.error(f"Error: {error_detail}")
                except Exception as e:
                    logger.exception("Failed to connect to the backend while ingesting '%s': %s", uploaded_file.name, e)
                    st.error(f"Failed to connect to the backend: {str(e)}")
        else:
            st.warning("Please upload a file first.")
            
    st.divider()
    st.header("Manage Collections")
    clear_col = st.selectbox("Select Collection to Clear/Delete", ["warranty", "user_manual", "inspection_report"], key="clear_col")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Clear Collection"):
            with st.spinner(f"Clearing {clear_col}..."):
                try:
                    logger.info("Clearing collection '%s'", clear_col)
                    res = requests.delete(f"{API_BASE_URL}/clear/{clear_col}")
                    if res.status_code == 200:
                        logger.info("Collection '%s' cleared successfully", clear_col)
                        st.success("Cleared!")
                    else:
                        logger.error("Error clearing collection '%s': %s", clear_col, res.text)
                        st.error("Error clearing")
                except Exception as e:
                    logger.exception("Connection error while clearing collection '%s': %s", clear_col, e)
                    st.error("Connection error")
    with col2:
        if st.button("Delete Collection"):
            with st.spinner(f"Deleting {clear_col}..."):
                try:
                    logger.info("Deleting collection '%s'", clear_col)
                    res = requests.delete(f"{API_BASE_URL}/delete/{clear_col}")
                    if res.status_code == 200:
                        logger.info("Collection '%s' deleted successfully", clear_col)
                        st.success("Deleted!")
                    else:
                        logger.error("Error deleting collection '%s': %s", clear_col, res.text)
                        st.error("Error deleting")
                except Exception as e:
                    logger.exception("Connection error while deleting collection '%s': %s", clear_col, e)
                    st.error("Connection error")

# Main chat interface
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat messages from history on app rerun
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        marker = "<div class='user-msg'></div>" if message["role"] == "user" else "<div class='assistant-msg'></div>"
        st.markdown(marker + message["content"], unsafe_allow_html=True)
        if ("logs" in message and message["logs"]) or message.get("graph_response"):
            with st.expander("View Logs"):
                for log in message.get("logs", []):
                    st.write(log)
                graph_response = message.get("graph_response") or {}
                guardrail_events = graph_response.get("guardrail_events", [])
                if guardrail_events:
                    st.markdown("**Guardrail events**")
                    for event in guardrail_events:
                        icon = "✅" if event.get("passed") else "🚫"
                        st.write(f"{icon} `{event.get('stage')}`" + (f" — {event.get('reason')}" if event.get("reason") else ""))
                if graph_response:
                    st.markdown("**LangGraph node state (full schema)**")
                    st.json(graph_response)

# Accept user input
if prompt := st.chat_input("Ask a question about your documents..."):
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})
    # Display user message in chat message container
    with st.chat_message("user"):
        st.markdown("<div class='user-msg'></div>" + prompt, unsafe_allow_html=True)

    # Display assistant response in chat message container
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        with st.spinner("Thinking..."):
            try:
                logger.info("Sending chat question: %r", prompt)
                payload = {"question": prompt}
                response = requests.post(f"{API_BASE_URL}/chat", json=payload)

                if response.status_code == 200:
                    data = response.json()
                    answer = data.get("answer", "No answer received.")
                    images = data.get("images", [])
                    logs = data.get("logs", [])
                    graph_response = data.get("graph_response")
                    logger.info("Received chat answer (length=%d, images=%d)", len(answer or ""), len(images))

                    message_placeholder.markdown("<div class='assistant-msg'></div>" + answer, unsafe_allow_html=True)
                    # for image in images:
                    #     if image is not None and Path(image).exists():
                    #         st.image(str(Path(image)), caption="Relevant Image", width="stretch")
                    if logs or graph_response:
                        with st.expander("View Logs"):
                            for log in logs:
                                st.write(log)
                            guardrail_events = (graph_response or {}).get("guardrail_events", [])
                            if guardrail_events:
                                st.markdown("**Guardrail events**")
                                for event in guardrail_events:
                                    icon = "✅" if event.get("passed") else "🚫"
                                    st.write(f"{icon} `{event.get('stage')}`" + (f" — {event.get('reason')}" if event.get("reason") else ""))
                            if graph_response:
                                st.markdown("**LangGraph node state (full schema)**")
                                st.json(graph_response)

                    # Add assistant response to chat history
                    st.session_state.messages.append({"role": "assistant", "content": answer, "logs": logs, "graph_response": graph_response})
                else:
                    try:
                        error_msg = f"Error: {response.json().get('detail', 'Unknown error')}"
                    except Exception as e:
                        logger.exception("Failed to parse chat error response: %s", e)
                        error_msg = f"Error: {response.text}"
                    logger.error("Chat request failed: %s", error_msg)
                    message_placeholder.markdown("<div class='assistant-msg'></div>" + error_msg, unsafe_allow_html=True)
                    st.session_state.messages.append({"role": "assistant", "content": error_msg})
            except Exception as e:
                logger.exception("Failed to connect to the backend for chat question %r: %s", prompt, e)
                error_msg = f"Failed to connect to the backend: {str(e)}"
                message_placeholder.markdown("<div class='assistant-msg'></div>" + error_msg, unsafe_allow_html=True)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
