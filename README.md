# 📊 Pipe Analysis App

Streamlit app that reads large CSV files from Firebase Storage and analyzes payment status (success/failed) across clients.

## 🚀 Features

- 🔥 Firebase Firestore & Storage integration
- ⚡ Handles large CSVs using chunked reading
- 📈 Displays real-time status breakdowns

## 🔐 Firebase Setup

Add `serviceAccountKey.json` in the root directory (excluded in `.gitignore`).

## 💻 Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
