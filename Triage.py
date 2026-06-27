import streamlit as st
from transformers import pipeline
import torch
import sqlite3
import datetime

# --- 1. DATABASE SETUP ---
# This creates a file called clinic.db in your folder and makes a table for patients
conn = sqlite3.connect('clinic.db', check_same_thread=False)
c = conn.cursor()
c.execute('''
    CREATE TABLE IF NOT EXISTS triage_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        summary TEXT
    )
''')
conn.commit()

# Function to save summary to database
def save_to_db(summary_text):
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO triage_logs (date, summary) VALUES (?, ?)", (current_time, summary_text))
    conn.commit()

# --- 2. LOAD MODEL ---
@st.cache_resource
def load_model():
    # This securely pulls the token from your .streamlit/secrets.toml file!
    HF_TOKEN = st.secrets["HF_TOKEN"] 
    
    return pipeline(
        "text-generation", 
        model="google/medgemma-1.5-4b-it", 
        torch_dtype=torch.bfloat16, 
        device_map="auto",
        token=HF_TOKEN
    )
pipe = load_model()

SYSTEM_PROMPT = """You are a polite clinical triage assistant. 
Ask the patient ONE short question at a time about their symptoms. 
Do not diagnose. Keep your final response under 2 sentences."""

# --- 3. SIDEBAR NAVIGATION ---
st.sidebar.title("🏥 Clinic Portal")
app_mode = st.sidebar.radio("Select View:", ["Patient Triage", "Doctor's Dashboard"])

# ==========================================
#         VIEW 1: PATIENT TRIAGE
# ==========================================
if app_mode == "Patient Triage":
    st.title("🩺 Patient Triage Chatbot")

    if "messages" not in st.session_state:
        st.session_state.messages = [] 

    triage_complete = False
    if st.session_state.messages and "CLINICAL SUMMARY" in st.session_state.messages[-1]["content"]:
        triage_complete = True

    with st.chat_message("assistant"):
        st.markdown("Hello! I am the clinic's triage assistant. Can you briefly tell me what brings you in today?")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if triage_complete:
        st.success("Triage complete. The doctor will review your summary and see you shortly.")
        st.info("👈 Check the 'Doctor's Dashboard' in the sidebar to see your saved record!")
        
        # We offer the download button just as an extra feature
        st.download_button(
            label="📥 Download Local Copy",
            data=st.session_state.messages[-1]["content"],
            file_name="patient_summary.txt",
            mime="text/plain"
        )
        # --- RESET BUTTON FOR THE NEXT PATIENT ---
        st.divider() # Draws a neat visual line
        if st.button("🔄 Start Triage for Next Patient"):
            # This wipes the AI's memory clean!
            st.session_state.messages = []
            # This instantly reloads the page
            st.rerun()
        
    elif prompt := st.chat_input("Describe your symptoms..."):
        with st.chat_message("user"):
            st.markdown(prompt)
        
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("assistant"):
            with st.spinner("MedGemma is analyzing..."):
                
                user_turn_count = sum(1 for msg in st.session_state.messages if msg["role"] == "user")
                
                model_messages = []
                for i, msg in enumerate(st.session_state.messages):
                    if i == 0 and msg["role"] == "user":
                        combined_text = f"{SYSTEM_PROMPT}\n\nPatient says: {msg['content']}"
                        model_messages.append({"role": "user", "content": combined_text})
                    else:
                        model_messages.append(msg)
                
                if user_turn_count >= 5:
                    model_messages[-1] = {
                        "role": "user",
                        "content": model_messages[-1]["content"] + "\n\n[System Directive: I have provided enough information. Please output the CLINICAL SUMMARY now in 3 bullet points, starting exactly with 'CLINICAL SUMMARY:']"
                    }
                
                response = pipe(model_messages, max_new_tokens=1024)
                bot_reply_raw = response[0]['generated_text'][-1]['content']
                
                if "<unused94>" in bot_reply_raw:
                    if "<unused95>" in bot_reply_raw:
                        thought_process, final_answer = bot_reply_raw.split("<unused95>", 1)
                    else:
                        thought_process = bot_reply_raw
                        final_answer = "\n\n*System note: Thought process was very long, proceeding to next step.*"
                    
                    thought_process = thought_process.replace("<unused94>thought", "").strip()
                    final_answer = final_answer.strip()
                    
                    with st.expander("🧠 View AI Reasoning Trace"):
                        st.caption(thought_process)
                    
                    st.markdown(final_answer)
                    st.session_state.messages.append({"role": "assistant", "content": final_answer})
                else:
                    final_answer = bot_reply_raw
                    st.markdown(final_answer)
                    st.session_state.messages.append({"role": "assistant", "content": final_answer})
                
                # --- SAVE TO DATABASE TRIGGER ---
                if "CLINICAL SUMMARY" in final_answer:
                    save_to_db(final_answer) # Saves to SQLite immediately!
                    st.rerun()

# # ==========================================
#         VIEW 2: DOCTOR'S DASHBOARD
# ==========================================
elif app_mode == "Doctor's Dashboard":
    st.title("👨‍⚕️ Physician Dashboard")
    st.caption("Patients waiting in the virtual lobby:")
    
    # Optional: Add a button to wipe the whole database at the end of the day!
    if st.button("🚨 End of Day: Clear All Records", type="primary"):
        c.execute("DELETE FROM triage_logs")
        conn.commit()
        st.success("All patient records securely deleted for the day.")
        st.rerun()
        
    st.divider()
    
    # Fetch all records from the database
    c.execute("SELECT * FROM triage_logs ORDER BY id DESC")
    records = c.fetchall()
    
    if not records:
        st.info("No patients currently waiting. Time for a coffee break! ☕")
    else:
        # Loop through the database records
        for record in records:
            patient_id = record[0]
            timestamp = record[1]
            summary = record[2]
            
            # Create two columns: 80% width for the summary, 20% for the button
            col1, col2 = st.columns([0.8, 0.2])
            
            with col1:
                with st.expander(f"Waiting: Patient #{patient_id} (Arrived: {timestamp})", expanded=True):
                    st.markdown(summary)
            
            with col2:
                # Every button in Streamlit needs a unique key, so we use the patient_id
                if st.button(f"✅ Discharge #{patient_id}", key=f"discharge_{patient_id}"):
                    # DELETE the specific patient from the database
                    c.execute("DELETE FROM triage_logs WHERE id=?", (patient_id,))
                    conn.commit()
                    st.rerun() # Refresh the page to make them disappear!