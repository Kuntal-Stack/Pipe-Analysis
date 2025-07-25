import streamlit as st
import pandas as pd
from datetime import datetime
import os
import time
import firebase_admin
from firebase_admin import credentials, firestore, storage
import tempfile
import json

# Firebase Initialization (Safe & Correct)
if not firebase_admin._apps:
    cred_dict = json.loads(st.secrets["FIREBASE_CREDENTIALS"])
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred, {
        'storageBucket': 'pipe-analysis.appspot.com'
    })

db = firestore.client()
bucket = storage.bucket()

# 🔹 Page setup
st.set_page_config(page_title="PG Analysis", layout="wide")
st.title("📊 Client Code-wise PG & Payment Mode Analysis")

import firebase_admin
from firebase_admin import credentials, firestore, storage
import streamlit as st

# 🔐 Firebase setup
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate("serviceAccountKey.json")
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'pipe-analysis.firebasestorage.app'  # ✅ Not 'firebasestorage.app'
        })
    
    # Firestore client
    db = firestore.client()
    
    # Correct way to get the bucket from initialized app
    bucket = storage.bucket()  # ✅ This works because the bucket was set during initialize_app

except Exception as e:
    st.error(f"❌ Firebase Initialization Failed: {e}")
    st.stop()

# 🔹 Get list of files from Firebase Storage
def list_firebase_csv_files():
    return [blob.name for blob in bucket.list_blobs(prefix="pipe_data/") if blob.name.endswith(".csv")]

available_files = list_firebase_csv_files()
available_dates = [os.path.basename(f).replace(".csv", "") for f in available_files]

if not available_dates:
    st.warning("⚠️ No CSV files found in Firebase Storage under 'pipe_data/'")
    st.stop()

# 🔹 Multiselect date input
selected_dates = st.multiselect("📅 Select Dates", options=available_dates, default=[available_dates[-1]])

if not selected_dates:
    st.info("ℹ️ Please select at least one date to view analysis.")
    st.stop()

# 🔹 Load data from Firebase
all_data = []
load_durations = {}

def load_firebase_csv(file_path):
    blob = bucket.blob(file_path)
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        blob.download_to_filename(tmp.name)
        df = pd.read_csv(tmp.name)
    return df

for date_str in selected_dates:
    file_path = f"pipe_data/{date_str}.csv"
    start_time = time.time()
    try:
        df = load_firebase_csv(file_path)
        df["__source_date"] = date_str
        all_data.append(df)
        load_durations[date_str] = round(time.time() - start_time, 2)
    except Exception as e:
        st.error(f"❌ Error loading {file_path}: {e}")

if not all_data:
    st.warning("⚠️ No valid files loaded.")
    st.stop()

df = pd.concat(all_data, ignore_index=True)

# 🔹 Required column checks
required_cols = ["client_code", "pg_pay_mode", "payment_mode", "status"]
missing = [col for col in required_cols if col not in df.columns]
if missing:
    st.error(f"❌ Missing columns: {missing}")
    st.stop()

if "client_name" not in df.columns:
    df["client_name"] = "Unknown"

# 🔹 Normalize
df["status"] = df["status"].astype(str).str.strip().str.lower()
df["pg_pay_mode"] = df["pg_pay_mode"].astype(str).str.strip()
df["payment_mode"] = df["payment_mode"].astype(str).str.strip()
df["client_code"] = df["client_code"].astype(str).str.strip()
df["client_name"] = df["client_name"].astype(str).str.strip()

# 🔹 Map status
def normalize_status(val):
    val = str(val).lower().strip()
    if "success" in val:
        return "success"
    elif "fail" in val:
        return "failed"
    return "other"

df["status"] = df["status"].apply(normalize_status)
filtered_df = df[df["status"].isin(["success", "failed"])]

if filtered_df.empty:
    st.warning("⚠️ No 'success' or 'failed' transactions.")
    st.stop()

# 🔹 Metrics
total_success = filtered_df[filtered_df["status"] == "success"].shape[0]
total_failed = filtered_df[filtered_df["status"] == "failed"].shape[0]
total_all = total_success + total_failed
success_percent = round((total_success / total_all) * 100, 2) if total_all else 0
failed_percent = round((total_failed / total_all) * 100, 2) if total_all else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("🔢 Total Transactions", f"{total_all:,}")
c2.metric("✅ Success Count", f"{total_success:,}")
c3.metric("❌ Failed Count", f"{total_failed:,}")
c4.metric("✅ Success %", f"{success_percent} %")
c5.metric("❌ Failed %", f"{failed_percent} %")

# 🔹 Group and summarize
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

summary = summary[[ 
    "client_name", "client_code", "pg_pay_mode", "payment_mode", 
    "success", "failed", "Total Txn", "Success %" 
]]

# 🔹 Sorting dropdown
sort_option = st.selectbox("🔽 Sort by Success %", ["ALL", "🔼 Lowest to Highest", "🔽 Highest to Lowest"])
if sort_option == "🔼 Lowest to Highest":
    summary = summary.sort_values("Success %", ascending=True)
elif sort_option == "🔽 Highest to Lowest":
    summary = summary.sort_values("Success %", ascending=False)

# 🔹 Heatmap styling
def highlight_success(val):
    color = "white"
    if val >= 95:
        bgcolor = "#2ecc71"
    elif val >= 80:
        bgcolor = "#f1c40f"
    else:
        bgcolor = "#e74c3c"
    return f"background-color: {bgcolor}; color: {color}; font-weight: bold;"

styled_df = summary.style.applymap(highlight_success, subset=["Success %"])
st.dataframe(styled_df, use_container_width=True)

# 🔹 Load durations
load_summary = ", ".join([f"{k} ({v}s)" for k, v in load_durations.items()])
st.caption(f"⏱️ Loaded files: {load_summary}")

# 🔹 Download CSV
csv = summary.to_csv(index=False).encode("utf-8")
download_name = f"PIPE Analysis ({'-'.join(selected_dates)}).csv"

st.download_button("📥 Download Summary as CSV", data=csv, file_name=download_name, mime="text/csv")

# 🔹 Firebase Firestore Upload
if st.button("📤 Upload to Firebase"):
    try:
        collection_name = "pipe_summary"
        docs = db.collection(collection_name).stream()
        for doc in docs:
            doc.reference.delete()

        for idx, row in summary.iterrows():
            doc_data = row.to_dict()
            doc_id = f"{row['client_code']}_{row['pg_pay_mode']}_{row['payment_mode']}"
            db.collection(collection_name).document(doc_id).set(doc_data)

        st.success("✅ Uploaded to Firebase Firestore.")
    except Exception as e:
        st.error(f"❌ Firebase upload failed: {e}")
import streamlit as st
import pandas as pd
from datetime import datetime
import os
import time

# 🔹 Page setup
st.set_page_config(page_title="PG Analysis", layout="wide")
st.title("📊 Client Code-wise PG & Payment Mode Analysis")

# 🔹 Get available dates from data folder
DATA_FOLDER = "data"
available_files = sorted([f for f in os.listdir(DATA_FOLDER) if f.endswith(".csv")])
available_dates = [f.replace(".csv", "") for f in available_files]

if not available_dates:
    st.warning("⚠️ No CSV files found in 'data/' folder.")
    st.stop()

# 🔹 Multiselect date input
selected_dates = st.multiselect("📅 Select Dates", options=available_dates, default=[available_dates[-1]])

if not selected_dates:
    st.info("ℹ️ Please select at least one date to view analysis.")
    st.stop()

# 🔹 Load data for all selected dates
all_data = []
load_durations = {}

for date_str in selected_dates:
    file_name = date_str + ".csv"
    file_path = os.path.join(DATA_FOLDER, file_name)
    start_time = time.time()

    if not os.path.exists(file_path):
        st.error(f"❌ File not found: `{file_name}`")
        continue

    try:
        df = pd.read_csv(file_path)
        df["__source_date"] = date_str  # Add source info
        all_data.append(df)
        load_durations[date_str] = round(time.time() - start_time, 2)
    except Exception as e:
        st.error(f"❌ Error reading {file_name}: {e}")

if not all_data:
    st.warning("⚠️ No valid files loaded. Please check file contents or selection.")
    st.stop()

df = pd.concat(all_data, ignore_index=True)

# 🔹 Required columns check
required_cols = ["client_code", "pg_pay_mode", "payment_mode", "status"]
missing = [col for col in required_cols if col not in df.columns]
if missing:
    st.error(f"❌ Missing columns: {missing}")
    st.stop()

# 🔹 Optional client_name check
if "client_name" not in df.columns:
    st.warning("⚠️ 'client_name' column not found. Defaulting to 'Unknown'.")
    df["client_name"] = "Unknown"

# 🔹 Clean and normalize
df["status"] = df["status"].astype(str).str.strip().str.lower()
df["pg_pay_mode"] = df["pg_pay_mode"].astype(str).str.strip()
df["payment_mode"] = df["payment_mode"].astype(str).str.strip()
df["client_code"] = df["client_code"].astype(str).str.strip()
df["client_name"] = df["client_name"].astype(str).str.strip()

# 🔹 Normalize status
def normalize_status(val):
    val = str(val).lower().strip()
    if "success" in val:
        return "success"
    elif "fail" in val:
        return "failed"
    else:
        return "other"

df["status"] = df["status"].apply(normalize_status)

# 🔹 Filter only success/failed
filtered_df = df[df["status"].isin(["success", "failed"])]

if filtered_df.empty:
    st.warning("⚠️ No transactions with 'success' or 'failed' status found.")
    st.stop()

# 🔹 Top bar metrics
total_success = filtered_df[filtered_df["status"] == "success"].shape[0]
total_failed = filtered_df[filtered_df["status"] == "failed"].shape[0]
total_all = total_success + total_failed
success_percent = round((total_success / total_all) * 100, 2) if total_all > 0 else 0
failed_percent = round((total_failed / total_all) * 100, 2) if total_all > 0 else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("🔢 Total Transactions", f"{total_all:,}")
c2.metric("✅ Success Count", f"{total_success:,}")
c3.metric("❌ Failed Count", f"{total_failed:,}")
c4.metric("✅ Success %", f"{success_percent} %")
c5.metric("❌ Failed %", f"{failed_percent} %")

# 🔹 Group and summarize
summary = (
    filtered_df
    .groupby(["client_name", "client_code", "pg_pay_mode", "payment_mode", "status"])
    .size()
    .unstack(fill_value=0)
    .reset_index()
)

# 🔹 Ensure success/failed columns exist
for col in ["success", "failed"]:
    if col not in summary.columns:
        summary[col] = 0

summary["Total Txn"] = summary["success"] + summary["failed"]
summary["Success %"] = round((summary["success"] / summary["Total Txn"]) * 100, 2).fillna(0)

summary = summary[[ 
    "client_name", "client_code", "pg_pay_mode", "payment_mode", 
    "success", "failed", "Total Txn", "Success %" 
]]

# 🔹 Dropdown for sorting
sort_option = st.selectbox("🔽 Sort by Success %", ["ALL", "🔼 Lowest to Highest", "🔽 Highest to Lowest"], index=0)
if sort_option == "🔼 Lowest to Highest":
    summary = summary.sort_values("Success %", ascending=True)
elif sort_option == "🔽 Highest to Lowest":
    summary = summary.sort_values("Success %", ascending=False)

# 🔹 Define heatmap style
def highlight_success(val):
    color = "white"
    if val >= 95:
        bgcolor = "#2ecc71"
    elif val >= 80:
        bgcolor = "#f1c40f"
    else:
        bgcolor = "#e74c3c"
    return f"background-color: {bgcolor}; color: {color}; font-weight: bold;"

styled_df = summary.style.applymap(highlight_success, subset=["Success %"])

# 🔹 Show styled table
st.dataframe(styled_df, use_container_width=True)

# 🔹 Show load durations
load_summary = ", ".join([f"{k} ({v}s)" for k, v in load_durations.items()])
st.caption(f"⏱️ Loaded files: {load_summary}")

# 🔹 Download CSV
csv = summary.to_csv(index=False).encode("utf-8")
download_name = f"PIPE Analysis ({'-'.join(selected_dates)}).csv"

st.download_button(
    label="📥 Download Summary as CSV",
    data=csv,
    file_name=download_name,
    mime="text/csv",
)
# e6cd86c (Initial commit with .gitignore to protect Firebase key)
