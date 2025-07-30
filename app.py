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
st.set_page_config(page_title="PIPE Analysis", layout="wide")
st.markdown("## 🔌 PIPE ANALYSIS")

# Alert / Refresh Buttons
alert_col, refresh_col = st.columns([1, 1])
alert_clicked = alert_col.button("🔔 Alert (Critical Only)")
refresh_clicked = refresh_col.button("🔁 Refresh")

# --- Firebase Storage ---
def list_firebase_csv_files():
    return [blob.name for blob in bucket.list_blobs(prefix="pipe_data/") if blob.name.endswith(".csv")]

def load_firebase_csv(file_path):
    blob = bucket.blob(file_path)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        blob.download_to_filename(tmp.name)
        df = pd.read_csv(tmp.name, low_memory=False)
    os.remove(tmp.name)
    return df

# --- Load CSVs ---
available_files = list_firebase_csv_files()
if not available_files:
    st.warning("⚠️ No CSVs found in Firebase Storage.")
    st.stop()

available_dates = sorted([os.path.basename(f).replace(".csv", "") for f in available_files])
selected_dates = st.multiselect("📅 Select Dates", options=available_dates, default=[available_dates[-1]])

if not selected_dates:
    st.info("ℹ️ Please select at least one date.")
    st.stop()

# Load all selected files
all_data = []
load_durations = {}
for date_str in selected_dates:
    file_path = f"pipe_data/{date_str}.csv"
    try:
        start = time.time()
        df = load_firebase_csv(file_path)
        df["__source_date"] = date_str
        all_data.append(df)
        load_durations[date_str] = round(time.time() - start, 2)
    except Exception as e:
        st.error(f"❌ Failed loading {file_path}: {e}")

if not all_data:
    st.stop()

df = pd.concat(all_data, ignore_index=True)

# --- Data Normalization ---
required_cols = ["client_code", "pg_pay_mode", "payment_mode", "status"]
missing = [col for col in required_cols if col not in df.columns]
if missing:
    st.error(f"Missing columns: {', '.join(missing)}")
    st.stop()

if "client_name" not in df.columns:
    df["client_name"] = "Unknown"

for col in ["status", "pg_pay_mode", "payment_mode", "client_code", "client_name"]:
    df[col] = df[col].astype(str).str.strip()

def normalize_status(val):
    val = val.lower()
    if "success" in val: return "success"
    if "fail" in val: return "failed"
    return "other"

df["status"] = df["status"].apply(normalize_status)
filtered_df = df[df["status"].isin(["success", "failed"])]
if filtered_df.empty:
    st.warning("⚠️ No valid transactions found.")
    st.stop()

# --- Grouped Summary ---
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

# ➕ Status Column
def get_status(p):
    if p >= 90: return "Healthy"
    elif p >= 70: return "Warning"
    else: return "Critical"
summary["Status"] = summary["Success %"].apply(get_status)

# --- Top Summary Metrics ---
total_success = summary["success"].sum()
total_failed = summary["failed"].sum()
total_txn = total_success + total_failed
success_percent = round((total_success / total_txn) * 100, 2) if total_txn else 0
failed_percent = round((total_failed / total_txn) * 100, 2) if total_txn else 0

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("🔢 Total Transactions", f"{total_txn:,}")
m2.metric("✅ Total Success", f"{total_success:,}")
m3.metric("❌ Total Failed", f"{total_failed:,}")
m4.metric("📈 Success %", f"{success_percent}%")
m5.metric("📉 Failed %", f"{failed_percent}%")

# --- Summary Buttons ---
status_counts = summary["Status"].value_counts().to_dict()
col1, col2, col3 = st.columns(3)

def summary_button(col, label, color, count, status_type):
    if col.button(f"{label} ({count})"):
        st.session_state["status_filter"] = status_type
    with col:
        st.markdown(f"<div style='padding:8px; background:{color}; color:white; border-radius:5px; text-align:center; font-weight:bold'>{label}: {count}</div>", unsafe_allow_html=True)

if "status_filter" not in st.session_state:
    st.session_state["status_filter"] = None
if alert_clicked:
    st.session_state["status_filter"] = "Critical"
if refresh_clicked:
    st.session_state["status_filter"] = None

summary_button(col1, "🟢 Healthy", "#2ecc71", status_counts.get("Healthy", 0), "Healthy")
summary_button(col2, "🟡 Warning", "#f1c40f", status_counts.get("Warning", 0), "Warning")
summary_button(col3, "🔴 Critical", "#e74c3c", status_counts.get("Critical", 0), "Critical")

# --- Filtering ---
if st.session_state["status_filter"]:
    summary = summary[summary["Status"] == st.session_state["status_filter"]]

# --- Sorting ---
sort_option = st.selectbox("🔽 Sort by Success %", ["Default", "🔼 Lowest to Highest", "🔽 Highest to Lowest"])
if sort_option == "🔼 Lowest to Highest":
    summary = summary.sort_values("Success %", ascending=True)
elif sort_option == "🔽 Highest to Lowest":
    summary = summary.sort_values("Success %", ascending=False)

# --- Pipe Action Logic ---
if "selected_pipe_row" not in st.session_state:
    st.session_state["selected_pipe_row"] = None

st.markdown("### 📋 PIPE STATUS TABLE")
for idx, row in summary.iterrows():
    cols = st.columns([2, 2, 2, 2, 1, 1, 1, 1.5, 1, 1])
    cols[0].write(row["client_name"])
    cols[1].write(row["client_code"])
    cols[2].write(row["pg_pay_mode"])
    cols[3].write(row["payment_mode"])
    cols[4].write(int(row["success"]))
    cols[5].write(int(row["failed"]))
    cols[6].write(int(row["Total Txn"]))
    cols[7].write(f"{row['Success %']}%")
    cols[8].write(row["Status"])
    if cols[9].button("Change Pipe", key=f"change_pipe_{idx}"):
        st.session_state["selected_pipe_row"] = row.to_dict()

# --- Modal for Change Pipe ---
if st.session_state["selected_pipe_row"]:
    row = st.session_state["selected_pipe_row"]
    with st.modal(f"🔧 Change Pipe for {row['client_code']}", key="pipe_modal"):
        st.markdown("### 🧰 Update Pipe Information")
        selected_pipe = st.selectbox("Select New Pipe", ["BOB", "AIRTEL", "YES BANK", "INDIAN BANK", "NPST", "HDFC", "ICICI BANK"])
        entered_keys = st.text_area("🔑 Enter Required Keys", placeholder="E.g., token, pipe_key, secret...")

        col1, col2 = st.columns(2)
        if col1.button("✅ Activate"):
            st.success(f"✅ Pipe changed for {row['client_code']} → {selected_pipe}")
            st.session_state["selected_pipe_row"] = None
        if col2.button("❌ Cancel"):
            st.session_state["selected_pipe_row"] = None

# --- Download Button ---
csv = summary.to_csv(index=False).encode("utf-8")
download_name = f"PIPE_Analysis_({'_'.join(selected_dates)}).csv"
st.download_button("📥 Download Summary", data=csv, file_name=download_name, mime="text/csv")

# --- Upload to Firestore ---
if st.button("📤 Upload to Firestore"):
    with st.spinner("Uploading..."):
        try:
            collection = "pipe_summary"
            for doc in db.collection(collection).stream():
                doc.reference.delete()
            for _, row in summary.iterrows():
                db.collection(collection).document(f"{row['client_code']}_{row['pg_pay_mode']}_{row['payment_mode']}").set(row.to_dict())
            st.success("✅ Uploaded successfully to Firestore.")
        except Exception as e:
            st.error(f"❌ Upload failed: {e}")

# Footer
load_summary = ", ".join([f"{k} ({v}s)" for k, v in load_durations.items()])
st.caption(f"⏱️ Files loaded: {load_summary}")
