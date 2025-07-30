import streamlit as st
import pandas as pd
import os
import time
import firebase_admin
from firebase_admin import credentials, firestore, storage
import tempfile
import json

# --- Firebase Initialization ---
def initialize_firebase():
    try:
        if not firebase_admin._apps:
            cred_dict = json.loads(st.secrets["FIREBASE_CREDENTIALS"])
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred, {
                'storageBucket': 'pipe-analysis.firebasestorage.app'
            })
        db = firestore.client()
        bucket = storage.bucket()
        return db, bucket
    except Exception as e:
        st.error(f"❌ Firebase Initialization Failed: {e}")
        st.stop()

db, bucket = initialize_firebase()

# --- Page Setup ---
st.set_page_config(page_title="PG Analysis", layout="wide")
st.title("📊 Client Code-wise PG & Payment Mode Analysis")

# --- Firebase Storage Functions ---
def list_firebase_csv_files():
    return [blob.name for blob in bucket.list_blobs(prefix="pipe_data/") if blob.name.endswith(".csv")]

def load_firebase_csv(file_path):
    blob = bucket.blob(file_path)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        blob.download_to_filename(tmp.name)
        df = pd.read_csv(tmp.name, low_memory=False)
    os.remove(tmp.name)
    return df

# --- File Selection ---
available_files = list_firebase_csv_files()
if not available_files:
    st.warning("⚠️ No CSV files found in Firebase Storage under the 'pipe_data/' folder.")
    st.stop()

available_dates = sorted([os.path.basename(f).replace(".csv", "") for f in available_files])
selected_dates = st.multiselect("📅 Select Dates", options=available_dates, default=[available_dates[-1]] if available_dates else [])

if not selected_dates:
    st.info("ℹ️ Please select at least one date to view the analysis.")
    st.stop()

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
    st.warning("⚠️ Could not load data for the selected dates.")
    st.stop()

df = pd.concat(all_data, ignore_index=True)
st.subheader("📦 Raw Data Preview")
st.dataframe(df.head(50))

# --- Summary Generation ---
required_cols = ["client_name", "client_code", "pg_pay_mode", "payment_mode", "status"]
if not all(col in df.columns for col in required_cols + ["status"]):
    st.error("❌ Missing required columns in data.")
    st.stop()

filtered_df = df[df["status"].isin(["success", "failed"])]

summary = (
    filtered_df
    .groupby(["client_name", "client_code", "pg_pay_mode", "payment_mode", "status"])
    .size()
    .unstack(fill_value=0)
    .reset_index()
)

for col in ["success", "failed"]:
    if col not in summary.columns:
        summary[col] = 0

summary["Total Txn"] = summary["success"] + summary["failed"]
summary["Success %"] = round((summary["success"] / summary["Total Txn"]) * 100, 2).fillna(0)

# --- Add Status Column ---
def get_status(success_percent):
    if success_percent >= 90:
        return "Healthy"
    elif success_percent >= 70:
        return "Warning"
    else:
        return "Critical"

summary["Status"] = summary["Success %"].apply(get_status)

# --- UI and Controls ---
st.markdown("## 🚰 PIPE ANALYSIS")

colA1, colA2 = st.columns([1, 1])
if colA1.button("🔔 Alert (Critical Only)"):
    summary = summary[summary["Status"] == "Critical"]
if colA2.button("🔁 Refresh"):
    st.experimental_rerun()

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

# --- Action Buttons Per Row ---
summary["Action"] = ""
for i in summary.index:
    btn_id = f"change_pipe_{i}"
    if st.button("Change Pipe", key=btn_id):
        with st.modal("🔄 Change Pipe"):
            selected_pipe = st.selectbox("Select New Pipe", ["BOB", "AIRTEL", "YES BANK", "INDIAN BANK", "NPST", "HDFC", "ICICI BANK"])
            key_input = st.text_input("Enter Required KEYS")
            colX1, colX2 = st.columns([1, 1])
            if colX1.button("✅ Activate"):
                st.success(f"Pipe changed to {selected_pipe} with keys: {key_input}")
            if colX2.button("❌ Cancel"):
                st.info("Cancelled pipe change")

# --- Display Table ---
final_cols = [
    "client_name", "client_code", "pg_pay_mode", "payment_mode",
    "success", "failed", "Total Txn", "Success %", "Status", "Action"
]
summary = summary[final_cols]

def highlight_success(val):
    if val >= 95:
        bgcolor = "#2ecc71"
    elif val >= 80:
        bgcolor = "#f1c40f"
    else:
        bgcolor = "#e74c3c"
    return f"background-color: {bgcolor}; color: white; font-weight: bold;"

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

# --- Download and Upload Buttons ---
csv = summary.to_csv(index=False).encode("utf-8")
download_name = f"PIPE_Analysis_({'_'.join(selected_dates)}).csv"
st.download_button("📥 Download Summary as CSV", data=csv, file_name=download_name, mime="text/csv")

if st.button("📤 Upload Summary to Firebase Firestore"):
    with st.spinner("Uploading..."):
        try:
            collection_name = "pipe_summary"
            for doc in db.collection(collection_name).stream():
                doc.reference.delete()
            for _, row in summary.iterrows():
                doc_id = f"{row['client_code']}_{row['pg_pay_mode']}_{row['payment_mode']}"
                db.collection(collection_name).document(doc_id).set(row.to_dict())
            st.success("✅ Summary uploaded to Firebase Firestore successfully!")
        except Exception as e:
            st.error(f"❌ Firebase upload failed: {e}")

# --- Footer ---
load_summary = ", ".join([f"{k} ({v}s)" for k, v in load_durations.items()])
st.caption(f"⏱️ Files loaded: {load_summary}")
