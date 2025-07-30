import streamlit as st
import pandas as pd
import os
import time
import firebase_admin
from firebase_admin import credentials, firestore, storage
import tempfile
import json

# --- Firebase Initialization ---
# This function handles the connection to Firebase using secrets.
def initialize_firebase():
    """
    Initializes the Firebase Admin SDK using Streamlit secrets.
    Returns Firestore and Storage clients.
    """
    try:
        # Check if the app is already initialized to prevent errors.
        if not firebase_admin._apps:
            # The secret is stored as a single string, so we parse it as JSON.
            # This is the line that was causing the KeyError before.
            cred_dict = json.loads(st.secrets["FIREBASE_CREDENTIALS"])
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred, {
                'storageBucket': 'pipe-analysis.firebasestorage.app'
            })
        
        # Get the Firestore and Storage clients after initialization.
        db = firestore.client()
        bucket = storage.bucket()
        return db, bucket

    except Exception as e:
        st.error(f"❌ Firebase Initialization Failed: {e}")
        st.error("Please ensure your `FIREBASE_CREDENTIALS` secret is set correctly in your Streamlit Cloud app settings.")
        st.stop()

# Initialize Firebase at the start of the app.
db, bucket = initialize_firebase()

# --- Page Setup ---
st.set_page_config(page_title="PG Analysis", layout="wide")
st.title("📊 Client Code-wise PG & Payment Mode Analysis")

# --- Firebase Storage Functions ---
def list_firebase_csv_files():
    """Lists all CSV files in the 'pipe_data/' folder in Firebase Storage."""
    return [blob.name for blob in bucket.list_blobs(prefix="pipe_data/") if blob.name.endswith(".csv")]

def load_firebase_csv(file_path):
    """Downloads a CSV from Firebase Storage and loads it into a DataFrame."""
    blob = bucket.blob(file_path)
    # Use a temporary file to download the data.
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        blob.download_to_filename(tmp.name)
        df = pd.read_csv(tmp.name, low_memory=False)
    os.remove(tmp.name) # Clean up the temporary file
    return df

# --- Main App Logic ---
available_files = list_firebase_csv_files()
if not available_files:
    st.warning("⚠️ No CSV files found in Firebase Storage under the 'pipe_data/' folder.")
    st.stop()

# Extract clean dates from file paths for the selector.
available_dates = sorted([os.path.basename(f).replace(".csv", "") for f in available_files])

# Multiselect for date selection.
selected_dates = st.multiselect("📅 Select Dates", options=available_dates, default=[available_dates[-1]] if available_dates else [])

if not selected_dates:
    st.info("ℹ️ Please select at least one date to view the analysis.")
    st.stop()

# Load data from Firebase for the selected dates.
all_data = []
load_durations = {}

for date_str in selected_dates:
    file_path = f"pipe_data/{date_str}.csv"
    start_time = time.time()
    try:
        df = load_firebase_csv(file_path)
        df["__source_date"] = date_str
        all_data.append(df)
        load_durations[date_str] = round(time.time() - start_time, 2)
    except Exception as e:
        st.error(f"❌ Error loading {file_path} from Firebase: {e}")

if not all_data:
    st.warning("⚠️ Could not load data for the selected dates. Please check file contents or selection.")
    st.stop()

df = pd.concat(all_data, ignore_index=True)

# --- Update Page Heading and Add Buttons ---
st.markdown("## 🚰 PIPE ANALYSIS")

colA1, colA2 = st.columns([1, 1])
if colA1.button("🔔 Alert (Critical Only)"):
    summary = summary.assign(Status=summary["Success %"].apply(
        lambda x: "Critical" if x < 70 else "Warning" if x < 90 else "Healthy"))
    summary = summary[summary["Status"] == "Critical"]
if colA2.button("🔁 Refresh"):
    st.experimental_rerun()

# --- Add Status Column ---
def get_status(success_percent):
    if success_percent >= 90:
        return "Healthy"
    elif success_percent >= 70:
        return "Warning"
    else:
        return "Critical"
# Define the function before applying it
def get_status(success_percent):
    if success_percent >= 90:
        return "Healthy"
    elif success_percent >= 70:
        return "Warning"
    else:
        return "Critical"
summary["Status"] = summary["Success %"].apply(get_status)

# --- Summary Counts ---
healthy_count = (summary["Status"] == "Healthy").sum()
warning_count = (summary["Status"] == "Warning").sum()
critical_count = (summary["Status"] == "Critical").sum()

s1, s2, s3 = st.columns(3)
if s1.button(f"🟢 Healthy: {healthy_count}"):
    summary = summary[summary["Status"] == "Healthy"]
if s2.button(f"🟡 Warning: {warning_count}"):
    summary = summary[summary["Status"] == "Warning"]
if s3.button(f"🔴 Critical: {critical_count}"):
    summary = summary[summary["Status"] == "Critical"]

# --- Add Action Column ---
summary["Action"] = ""

for i in summary.index:
    btn_id = f"change_pipe_{i}"
    if st.button("Change Pipe", key=btn_id):
        with st.modal("🔄 Change Pipe"):
            selected_pipe = st.selectbox(
                "Select New Pipe",
                ["BOB", "AIRTEL", "YES BANK", "INDIAN BANK", "NPST", "HDFC", "ICICI BANK"]
            )
            key_input = st.text_input("Enter Required KEYS")
            colX1, colX2 = st.columns([1, 1])
            if colX1.button("✅ Activate"):
                st.success(f"Pipe changed to {selected_pipe} with keys: {key_input}")
            if colX2.button("❌ Cancel"):
                st.info("Cancelled pipe change")

# --- Reorder Columns for Final Display ---
final_cols = [
    "client_name", "client_code", "pg_pay_mode", "payment_mode",
    "success", "failed", "Total Txn", "Success %", "Status", "Action"
]
summary = summary[final_cols]

# --- Styled Display ---
def highlight_success(val):
    color = "white"
    if val >= 95:
        bgcolor = "#2ecc71"
    elif val >= 80:
        bgcolor = "#f1c40f"
    else:
        bgcolor = "#e74c3c"
    return f"background-color: {bgcolor}; color: {color}; font-weight: bold;"

def highlight_status(val):
    if val == "Healthy":
        return "background-color: #2ecc71; color: white"
    elif val == "Warning":
        return "background-color: #f1c40f; color: black"
    elif val == "Critical":
        return "background-color: #e74c3c; color: white"
    return ""

styled_df = summary.style.map(highlight_success, subset=["Success %"]).map(highlight_status, subset=["Status"])
st.dataframe(styled_df, use_container_width=True, height=600)

# --- Download and Upload Actions ---
# Download button
csv = summary.to_csv(index=False).encode("utf-8")
download_name = f"PIPE_Analysis_({'_'.join(selected_dates)}).csv"
st.download_button("📥 Download Summary as CSV", data=csv, file_name=download_name, mime="text/csv")

# Upload to Firestore button
if st.button("📤 Upload Summary to Firebase Firestore"):
    with st.spinner("Uploading..."):
        try:
            collection_name = "pipe_summary"
            # Clear existing collection before upload
            for doc in db.collection(collection_name).stream():
                doc.reference.delete()
            
            # Upload new summary
            for _, row in summary.iterrows():
                doc_data = row.to_dict()
                # Create a unique document ID
                doc_id = f"{row['client_code']}_{row['pg_pay_mode']}_{row['payment_mode']}"
                db.collection(collection_name).document(doc_id).set(doc_data)
            
            st.success("✅ Summary uploaded to Firebase Firestore successfully!")
        except Exception as e:
            st.error(f"❌ Firebase upload failed: {e}")

# Footer with load times
load_summary = ", ".join([f"{k} ({v}s)" for k, v in load_durations.items()])
st.caption(f"⏱️ Files loaded: {load_summary}")
