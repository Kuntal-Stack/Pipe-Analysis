import streamlit as st
import pandas as pd
import datetime
import firebase_admin
from firebase_admin import credentials, firestore

# Initialize Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate("your_firebase_key.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

st.set_page_config(page_title="PIPE ANALYSIS", layout="wide")
st.title("🧪 PIPE ANALYSIS")

# Upload Excel File
uploaded_file = st.file_uploader("Upload Excel file", type=["xlsx", "xls"])
if uploaded_file:
    df = pd.read_excel(uploaded_file)

    # Rename Columns
    df.rename(
        columns={
            "client_code": "Client Code",
            "pg_pay_mode": "PG Pay Mode",
            "payment_mode": "Payment Mode",
            "status": "Status",
            "txn_id": "Txn ID"
        }, inplace=True
    )

    # Success and Failed Flags
    df["success"] = df["Status"].apply(lambda x: 1 if str(x).lower() == "success" else 0)
    df["failed"] = df["Status"].apply(lambda x: 1 if str(x).lower() != "success" else 0)

    # Group Summary
    summary = df.groupby(["Client Code", "PG Pay Mode", "Payment Mode"]).agg(
        Transactions=("Txn ID", "count"),
        Success=("success", "sum"),
        Failed=("failed", "sum")
    ).reset_index()

    summary["Success %"] = round((summary["Success"] / summary["Transactions"]) * 100, 2)
    summary["Failure %"] = round((summary["Failed"] / summary["Transactions"]) * 100, 2)

    def get_status(success_percent):
        if success_percent >= 95:
            return "Healthy"
        elif success_percent >= 80:
            return "Warning"
        else:
            return "Critical"

    summary["Status"] = summary["Success %"].apply(get_status)

    # Top-level Metrics
    total_success = summary["Success"].sum()
    total_failed = summary["Failed"].sum()
    total_txn = total_success + total_failed
    success_percent = round((total_success / total_txn) * 100, 2) if total_txn else 0
    failed_percent = round((total_failed / total_txn) * 100, 2) if total_txn else 0

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("🔢 Total Transactions", f"{total_txn:,}")
    m2.metric("✅ Total Success", f"{total_success:,}")
    m3.metric("❌ Total Failed", f"{total_failed:,}")
    m4.metric("📈 Success %", f"{success_percent}%")
    m5.metric("📉 Failed %", f"{failed_percent}%")

    # Filter by Status
    status_counts = summary["Status"].value_counts().to_dict()
    selected_status = st.radio(
        "Filter by Pipe Health Status:",
        ["All"] + list(status_counts.keys()),
        horizontal=True,
    )

    if selected_status != "All":
        filtered_df = summary[summary["Status"] == selected_status]
    else:
        filtered_df = summary.copy()

    # Optional dropdown filters
    col1, col2, col3 = st.columns(3)
    with col1:
        pg_filter = st.selectbox("Filter PG Pay Mode", ["All"] + sorted(filtered_df["PG Pay Mode"].unique().tolist()))
    with col2:
        pm_filter = st.selectbox("Filter Payment Mode", ["All"] + sorted(filtered_df["Payment Mode"].unique().tolist()))
    with col3:
        status_filter = st.selectbox("Filter Status", ["All"] + sorted(filtered_df["Status"].unique().tolist()))

    if pg_filter != "All":
        filtered_df = filtered_df[filtered_df["PG Pay Mode"] == pg_filter]
    if pm_filter != "All":
        filtered_df = filtered_df[filtered_df["Payment Mode"] == pm_filter]
    if status_filter != "All":
        filtered_df = filtered_df[filtered_df["Status"] == status_filter]

    st.subheader("📊 Summary Table")
    st.dataframe(filtered_df.drop(columns=["success", "failed"]))

    st.markdown("---")

    # Change Pipe Modal Logic
    for idx, row in filtered_df.iterrows():
        col1, col2 = st.columns([5, 1])
        with col1:
            st.markdown(f"**{row['Client Code']} | {row['PG Pay Mode']} | {row['Payment Mode']}**")
        with col2:
            if st.button("🔄 Change Pipe", key=f"btn_{idx}"):
                with st.form(f"form_{idx}"):
                    st.write(f"### Change Pipe for {row['Client Code']}")
                    new_pg = st.text_input("New PG Pay Mode")
                    new_pm = st.text_input("New Payment Mode")
                    remarks = st.text_area("Remarks")
                    submitted = st.form_submit_button("Submit")
                    if submitted:
                        db.collection("pipe_changes").add({
                            "client_code": row["Client Code"],
                            "old_pg": row["PG Pay Mode"],
                            "old_pm": row["Payment Mode"],
                            "new_pg": new_pg,
                            "new_pm": new_pm,
                            "remarks": remarks,
                            "timestamp": datetime.datetime.now()
                        })
                        st.success("✅ Pipe change submitted!")

    # Export CSV
    csv = filtered_df.to_csv(index=False).encode("utf-8")
    st.download_button("📥 Download Filtered Data as CSV", csv, "pipe_analysis.csv", "text/csv")

