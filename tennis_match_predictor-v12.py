# Tennis Match Predictor with Elo Ratings, Head-to-Head, XGBoost + Web App

import pandas as pd
import numpy as np
import glob
import os
import joblib
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from xgboost import XGBClassifier
import matplotlib.pyplot as plt
import seaborn as sns
import streamlit as st
import stat
import time

# New for Kaggle API integration
import subprocess
import zipfile
import shutil
import requests
import io

# Streamlit UI setup
st.title("🎾 Tennis Match Predictor")
st.markdown("This app uses ATP match data from 1981–2024 to predict match outcomes using Elo ratings and machine learning.")

# Helper: remove read-only flag to allow folder deletion
def remove_readonly(func, path, _):
    os.chmod(path, stat.S_IWRITE)
    func(path)

# Retry helper for zip extraction
def try_extract_all(zipfile_obj, extract_path, max_retries=3):
    for attempt in range(max_retries):
        try:
            zipfile_obj.extractall(extract_path)
            return True
        except Exception as e:
            st.warning(f"Attempt {attempt+1} to extract zip failed: {e}")
            time.sleep(1.5 * (attempt + 1))
    return False

# Set up Kaggle credentials from Streamlit secrets
if "KAGGLE_USERNAME" in st.secrets and "KAGGLE_KEY" in st.secrets:
    os.environ["KAGGLE_USERNAME"] = st.secrets["KAGGLE_USERNAME"]
    os.environ["KAGGLE_KEY"] = st.secrets["KAGGLE_KEY"]

# Download and cache Jeff Sackmann ATP dataset
DATA_URL = "https://github.com/JeffSackmann/tennis_atp/archive/refs/heads/master.zip"
zipped_data_path = "cached_atp_dataset.zip"

if not os.path.exists("atp_data") or not os.listdir("atp_data"):
    with st.spinner("Downloading ATP dataset (~15MB)..."):
        try:
            if not os.path.exists(zipped_data_path):
                r = requests.get(DATA_URL)
                with open(zipped_data_path, "wb") as f:
                    f.write(r.content)

            with zipfile.ZipFile(zipped_data_path, 'r') as z:
                temp_dir = "_temp_tennis_data"

                if os.path.exists(temp_dir):
                    try:
                        shutil.rmtree(temp_dir, onerror=remove_readonly)
                    except Exception as e:
                        st.warning(f"Failed to clean temp directory: {e}")

                if not try_extract_all(z, temp_dir):
                    st.error("Could not extract ATP dataset after multiple retries.")
                    st.stop()

                extracted_dir = os.path.join(temp_dir, "tennis_atp-master")
                if os.path.exists(extracted_dir):
                    try:
                        if os.path.exists("atp_data"):
                            shutil.rmtree("atp_data", onerror=remove_readonly)
                        os.rename(extracted_dir, "atp_data")
                    except Exception as e:
                        st.error(f"Failed to move ATP data directory: {e}")
                else:
                    st.error("ATP data folder not found in extracted zip!")
                    st.stop()

                try:
                    shutil.rmtree(temp_dir, onerror=remove_readonly)
                except Exception as e:
                    st.warning(f"Could not fully delete temp folder (harmless): {e}")
        except Exception as e:
            st.error(f"Download failed: {e}")
            st.stop()

# 🔄 Download Kaggle dataset via API with caching and retry logic
kaggle_dir = "kaggle_data"
kaggle_file = os.path.join(kaggle_dir, "atp_matches.csv")
kaggle_zip_path = os.path.join(kaggle_dir, "atp-tennis-2000-2023daily-pull.zip")

if not os.path.exists(kaggle_file):
    try:
        st.info("Downloading updated ATP data from Kaggle...")
        os.makedirs(kaggle_dir, exist_ok=True)
        kaggle_dataset = "dissfya/atp-tennis-2000-2023daily-pull"

        if not os.path.exists(kaggle_zip_path):
            subprocess.run(["kaggle", "datasets", "download", "-d", kaggle_dataset, "-p", kaggle_dir], check=True)

        with zipfile.ZipFile(kaggle_zip_path, 'r') as zip_ref:
            if not try_extract_all(zip_ref, kaggle_dir):
                st.warning("Could not extract Kaggle dataset after multiple retries.")

    except Exception as e:
        st.warning(f"Could not download from Kaggle: {e}")

# Load and combine ATP data
all_files = sorted(glob.glob(os.path.join("atp_data", "atp_matches_*.csv")))
kaggle_df = pd.read_csv(kaggle_file) if os.path.exists(kaggle_file) else pd.DataFrame()

dfs = []
for f in all_files:
    try:
        dfs.append(pd.read_csv(f))
    except Exception as e:
        st.warning(f"Skipping {f}: {e}")

if kaggle_df.shape[0] > 0:
    dfs.append(kaggle_df)

if not dfs:
    st.error("No valid match data found.")
    st.stop()

df = pd.concat(dfs, ignore_index=True)
st.success(f"✅ Successfully loaded {len(df):,} match records.")

# Basic preprocessing for modeling
df = df[df["winner_name"].notnull() & df["loser_name"].notnull()]
df = df[(df["surface"].notnull()) & (df["tourney_level"].notnull())]

# Player select inputs
players = sorted(set(df['winner_name']).union(set(df['loser_name'])))
player1 = st.selectbox("Select Player 1", players)
player2 = st.selectbox("Select Player 2", players, index=players.index(player1)+1 if player1 in players[:-1] else 0)

# Match context inputs
surface = st.selectbox("Surface", df['surface'].dropna().unique())
tourney_level = st.selectbox("Tournament Level", df['tourney_level'].dropna().unique())

if st.button("Predict Winner"):
    match_data = df[(df["winner_name"].isin([player1, player2])) & (df["loser_name"].isin([player1, player2]))]
    if match_data.empty:
        st.warning("No head-to-head data between selected players.")
    else:
        match_data["p1_win"] = match_data["winner_name"] == player1

        features = match_data[["surface", "tourney_level"]]
        features = pd.get_dummies(features)
        X = features
        y = match_data["p1_win"]

        model = XGBClassifier(use_label_encoder=False, eval_metric="logloss")
        model.fit(X, y)

        test_input = pd.DataFrame([[surface, tourney_level]], columns=["surface", "tourney_level"])
        test_input = pd.get_dummies(test_input).reindex(columns=X.columns, fill_value=0)

        prediction = model.predict(test_input)[0]
        proba = model.predict_proba(test_input)[0][int(prediction)]

        winner = player1 if prediction else player2
        st.success(f"🎯 Predicted Winner: **{winner}** with {proba*100:.2f}% confidence")

