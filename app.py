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
        st.error("Please ensure your FIREBASE_CREDENTIALS secret is set correctly in your Streamlit Cloud app settings.")
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

# --- Data Processing and Analysis ---
# Column checks and normalization
required_cols = ["client_code", "pg_pay_mode", "payment_mode", "status"]
missing = [col for col in required_cols if col not in df.columns]
if missing:
    st.error(f"❌ The loaded files are missing required columns: {', '.join(missing)}")
    st.stop()

if "client_name" not in df.columns:
    df["client_name"] = "Unknown"

# Normalize data types and values
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
    st.warning("⚠️ No 'success' or 'failed' transactions found in the selected data.")
    st.stop()

# --- Display Metrics and Data ---
# Top bar metrics
total_success = (filtered_df["status"] == "success").sum()
total_failed = (filtered_df["status"] == "failed").sum()
total_all = total_success + total_failed
success_percent = round((total_success / total_all) * 100, 2) if total_all else 0
failed_percent = round((total_failed / total_all) * 100, 2) if total_all else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("🔢 Total Transactions", f"{total_all:,}")
c2.metric("✅ Success Count", f"{total_success:,}")
c3.metric("❌ Failed Count", f"{total_failed:,}")
c4.metric("✅ Success %", f"{success_percent}%")
c5.metric("❌ Failed %", f"{failed_percent}%")

# Group and summarize data
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

# Sorting dropdown
sort_option = st.selectbox("🔽 Sort by Success %", ["Default", "🔼 Lowest to Highest", "🔽 Highest to Lowest"])
if sort_option == "🔼 Lowest to Highest":
    summary = summary.sort_values("Success %", ascending=True)
elif sort_option == "🔽 Highest to Lowest":
    summary = summary.sort_values("Success %", ascending=False)

# Heatmap styling for the summary table
def highlight_success(val):
    color = "white"
    if val >= 95: bgcolor = "#2ecc71"  # Green
    elif val >= 80: bgcolor = "#f1c40f"  # Yellow
    else: bgcolor = "#e74c3c"  # Red
    return f"background-color: {bgcolor}; color: {color}; font-weight: bold;"

styled_df = summary.style.map(highlight_success, subset=["Success %"])
st.dataframe(styled_df, use_container_width=True, height=500)

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
