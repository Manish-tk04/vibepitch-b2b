import streamlit as st
import google.generativeai as genai
import os
import pandas as pd
import time
from dotenv import load_dotenv

# --- 1. Security & Auth (Upgraded for Cloud) ---
# First, try to fetch the key from Streamlit's Cloud Secrets
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except KeyError:
    # If not on the cloud, fallback to the local .env file
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    st.error("🚨 SECURITY HALT: API Key not found. Check Streamlit Secrets or local .env file.")
    st.stop()

genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.5-flash') 

# ... (Leave the rest of your app.py code exactly as it is below this)

genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.5-flash') 

# --- 2. Page Config & Memory ---
st.set_page_config(page_title="VibePitch B2B", layout="wide")
st.title("⚡ VibePitch: AI Sponsorship Automator")

if "single_email_body" not in st.session_state:
    st.session_state.single_email_body = None
if "single_email_subject" not in st.session_state:
    st.session_state.single_email_subject = None
if "bulk_data" not in st.session_state:
    st.session_state.bulk_data = None

# --- 3. Core Event Configuration ---
with st.expander("⚙️ 1. Core Event & Sender Details", expanded=True):
    event_name = st.text_input("Organization & Fest Name")
    
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        start_date = st.date_input("Start Date")
    with col_d2:
        end_date = st.date_input("End Date")
        
    col1, col2 = st.columns(2)
    with col1:
        footfall = st.number_input("Expected Footfall", min_value=0, step=1000, value=0)
    with col2:
        deck_url = st.text_input("Sponsorship Deck Link")
        
    sender_signature = st.text_area("Your Email Signature (Applies to all emails)")

# --- 4. The Logic Engine ---
def generate_pitch(b_name, b_url, b_vibe, custom_ctx="None", activations=[]):
    prompt = f"""
    You are an elite B2B sales copywriter writing a sponsorship cold email.
    
    ABSOLUTE ROLES (DO NOT HALLUCINATE):
    - SENDER: You represent {event_name}.
    - RECIPIENT: You are pitching TO the marketing team at {b_name} ({b_url}).
    
    CONTEXT:
    - Event Dates: {start_date} to {end_date}
    - Expected Footfall: {footfall}
    - Requested Activations: {', '.join(activations) if activations else 'Suggest one logical integration.'}
    - Strategic Override: {custom_ctx}
    - Required Vibe/Tone: {b_vibe}
    
    FORMATTING RULES:
    1. Do not act like you are the brand. You are pitching the brand.
    2. Output EXACTLY in this format:
    SUBJECT: [Your subject line]
    BODY: 
    [Email body]
    
    3. Conclude the email body EXACTLY with this signature, do not add placeholders:
    {sender_signature}
    """
    response_text = model.generate_content(prompt).text
    
    if "BODY:" in response_text:
        parts = response_text.split("BODY:", 1)
        sub = parts[0].replace("SUBJECT:", "").strip()
        body = parts[1].strip()
    else:
        sub = "Sponsorship Proposal"
        body = response_text
    return sub, body

# --- 5. Tabs Layout ---
tab1, tab2 = st.tabs(["🎯 Single Pitch", "🚀 Bulk Processing Grid"])

# --- TAB 1: SINGLE PITCH ---
with tab1:
    st.subheader("Target Brand Intelligence")
    brand_name = st.text_input("Target Brand Name")
    brand_url = st.text_input("Target Website URL")
    pitch_tone = st.selectbox("Desired Pitch Tone", ["Corporate/Professional", "Aggressive/Energetic", "Playful/Creative", "Culturally Authentic"])
    activations = st.multiselect("Specific Activations to Pitch", ["Pro-Shows", "Food Court", "Hackathon", "Gaming Zone"])
    custom_context = st.text_area("Additional Strategic Context")
    
    if st.button("Generate Single Pitch"):
        if not event_name or not brand_name:
            st.error("Please fill out the Event Name and Brand Name.")
        else:
            with st.spinner(f"Drafting pitch to {brand_name}..."):
                try:
                    sub, body = generate_pitch(brand_name, brand_url, pitch_tone, custom_context, activations)
                    st.session_state.single_email_subject = sub
                    st.session_state.single_email_body = body
                    st.success("Generated!")
                except Exception as e:
                    st.error(f"Error: {e}")

    if st.session_state.single_email_body:
        st.divider()
        st.markdown(f"**Subject:** {st.session_state.single_email_subject}")
        col_edit, col_ai = st.columns(2)
        with col_edit:
            edited_body = st.text_area("Manual Editor", value=st.session_state.single_email_body, height=300)
            if st.button("Save Manual Edit"):
                st.session_state.single_email_body = edited_body
                st.success("Saved!")
        with col_ai:
            refinement = st.text_input("AI Refinement Command")
            if st.button("Refine with AI (Single)"):
                with st.spinner("Rewriting..."):
                    ref_prompt = f"Rewrite this email based on this command: {refinement}. Only output the new plain text body.\n\n{st.session_state.single_email_body}"
                    st.session_state.single_email_body = model.generate_content(ref_prompt).text
                    st.rerun()

# --- TAB 2: BULK PROCESSING GRID ---
with tab2:
    st.subheader("Interactive Leads Grid")
    
    default_df = pd.DataFrame([{"Brand Name": "", "Website URL": "", "Desired Vibe": "Corporate/Professional"}])
    
    uploaded_file = st.file_uploader("Upload CSV (Optional)", type=["csv"])
    if uploaded_file is not None:
        grid_data = pd.read_csv(uploaded_file)
    else:
        grid_data = default_df

    # Configure the dropdown for the grid
    column_config = {
        "Desired Vibe": st.column_config.SelectboxColumn(
            "Desired Vibe",
            options=["Corporate/Professional", "Aggressive/Energetic", "Playful/Creative", "Culturally Authentic"],
            required=True
        )
    }

    edited_df = st.data_editor(grid_data, num_rows="dynamic", use_container_width=True, column_config=column_config)
    
    if st.button("Run Bulk Engine on Grid"):
        run_df = edited_df[edited_df["Brand Name"].str.strip() != ""]
        if run_df.empty:
            st.error("Add at least one brand to the grid before running.")
        else:
            run_df["Generated_Subject"] = ""
            run_df["Generated_Body"] = ""
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for index, row in run_df.iterrows():
                status_text.text(f"Processing: {row['Brand Name']}...")
                try:
                    sub, body = generate_pitch(row['Brand Name'], row['Website URL'], row['Desired Vibe'])
                    run_df.at[index, "Generated_Subject"] = sub
                    run_df.at[index, "Generated_Body"] = body
                except Exception as e:
                    run_df.at[index, "Generated_Body"] = f"ERROR: {e}"
                
                progress_bar.progress((index + 1) / len(run_df))
                time.sleep(1)
            
            status_text.text("Bulk Generation Complete!")
            st.session_state.bulk_data = run_df
            st.rerun()

    if st.session_state.bulk_data is not None:
        st.divider()
        st.subheader("Review & Refine Bulk Results")
        df_results = st.session_state.bulk_data
        selected_brand = st.selectbox("Select a brand to review:", df_results['Brand Name'].tolist())
        current_sub = df_results.loc[df_results['Brand Name'] == selected_brand, 'Generated_Subject'].values[0]
        current_body = df_results.loc[df_results['Brand Name'] == selected_brand, 'Generated_Body'].values[0]
        
        st.markdown(f"**Subject:** {current_sub}")
        col_b1, col_b2 = st.columns(2)
        with col_b1:
            edited_bulk = st.text_area("Manual Editor (Bulk)", value=current_body, height=300)
            if st.button("Save Edit to Grid"):
                st.session_state.bulk_data.loc[st.session_state.bulk_data['Brand Name'] == selected_brand, 'Generated_Body'] = edited_bulk
                st.success("Saved!")
        with col_b2:
            refine_bulk = st.text_input("Refine Command")
            if st.button("Refine with AI (Bulk)"):
                with st.spinner("Rewriting..."):
                    ref_prompt = f"Rewrite this email based on this command: {refine_bulk}. Output only the final plain text.\n\n{current_body}"
                    new_body = model.generate_content(ref_prompt).text
                    st.session_state.bulk_data.loc[st.session_state.bulk_data['Brand Name'] == selected_brand, 'Generated_Body'] = new_body
                    st.rerun()

        st.divider()
        csv_export = st.session_state.bulk_data.to_csv(index=False).encode('utf-8')
        st.download_button("Download Approved Campaigns (CSV)", data=csv_export, file_name="vibepitch_final.csv", mime="text/csv")