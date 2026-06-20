import streamlit as st
import matplotlib.pyplot as plt
import numpy as np
import json
import os
from github import Github
from datetime import datetime, timedelta
import pytz

# --- KONFIGURATION ---
st.set_page_config(page_title="Mein Hybrid-Wettermodell", layout="wide")

# GitHub Einstellungen (Müssen in den Streamlit Secrets stehen!)
# Erstelle in Streamlit unter "Advanced Settings" -> "Secrets" folgendes:
# GITHUB_TOKEN = "dein_github_token"
# REPO_NAME = "dein_username/dein_repo"

# --- FUNKTIONEN ---

@st.cache_data(ttl=300) # Aktualisiert sich alle 5 Minuten
def load_settings():
    """Lädt die Einstellungen aus der lokalen JSON (die von GitHub kommt)."""
    if os.path.exists("settings.json"):
        with open("settings.json", "r") as f:
            return json.load(f)
    return {}

def save_settings_to_github(new_settings):
    """Speichert Änderungen direkt zurück ins GitHub Repo."""
    try:
        token = st.secrets["GITHUB_TOKEN"]
        repo_name = st.secrets["REPO_NAME"]
        
        g = Github(token)
        repo = g.get_repo(repo_name)
        contents = repo.get_contents("settings.json")
        
        repo.update_file(
            contents.path, 
            "Aktualisiere Farbskalen (Auto-Commit Streamlit)", 
            json.dumps(new_settings, indent=4), 
            contents.sha
        )
        st.sidebar.success("✅ JSON in GitHub aktualisiert!")
    except Exception as e:
        st.sidebar.error(f"Fehler beim Speichern in GitHub: {e}")

def get_hybrid_data(parameter, lead_time, correction_factor):
    """
    Simuliert das Laden von AROME, ICON-D2 und RUC.
    Hier binden wir später die echten GRIB2-Daten/APIs ein!
    """
    # Platzhalter: Wir generieren zufällige "Wetterkarten" als 100x100 Matrizen
    np.random.seed(lead_time) # Damit die Karte pro Stunde gleich aussieht
    arome = np.random.rand(100, 100) * 20
    icon_d2 = np.random.rand(100, 100) * 18
    icon_ruc = np.random.rand(100, 100) * 22
    
    # Hybrid-Modell bilden (Mischung)
    hybrid = (arome + icon_d2 + icon_ruc) / 3.0
    
    # Synoptiker-Korrektur anwenden (Dein Eingriff!)
    hybrid = hybrid * correction_factor
    return hybrid

def plot_static_map(data, settings, parameter):
    """Erstellt die statische Modellkarte."""
    fig, ax = plt.subplots(figsize=(10, 6))
    
    cmap = settings.get(parameter, {}).get("cmap", "viridis")
    vmin = settings.get(parameter, {}).get("vmin", 0)
    vmax = settings.get(parameter, {}).get("vmax", 50)
    
    # Karte zeichnen
    c = ax.contourf(data, levels=20, cmap=cmap, vmin=vmin, vmax=vmax)
    fig.colorbar(c, ax=ax, label=parameter)
    ax.set_title(f"Hybrid-Modell Karte: {parameter}")
    ax.axis('off') # Achsen ausblenden für sauberen Look
    
    return fig

# --- APP LAYOUT ---

st.title("🌦️ Mein Hybrid MOS-MIX Wettermodell")

# Initialisiere Session State für die Zeit
if "lead_time" not in st.session_state:
    st.session_state.lead_time = 0

# --- SIDEBAR (Menü) ---
st.sidebar.header("⚙️ Steuerung")

# 1. Parameter Auswahl
parameter = st.sidebar.selectbox("Parameter wählen", ["Niederschlagsrate", "Windböen"])

# 2. Synoptische Korrektur
st.sidebar.subheader("👨‍🔬 Synoptische Korrektur")
st.sidebar.write("Modell rechnet zu wenig/viel?")
correction = st.sidebar.slider(f"Korrekturfaktor {parameter}", min_value=0.0, max_value=3.0, value=1.0, step=0.1)

# 3. Zeitregler (Buttons + Umrechnung)
st.sidebar.subheader("⏱️ Zeitleiste (Vorhersage)")
berlin_tz = pytz.timezone('Europe/Berlin')
current_time = datetime.now(berlin_tz)

# Grid für Buttons aufbauen (immer 4 in einer Reihe für Platzersparnis am Handy)
cols = st.sidebar.columns(4)
for h in range(28): # 0 bis +27h
    col_idx = h % 4
    forecast_time = current_time + timedelta(hours=h)
    time_str = forecast_time.strftime("%H:%M") # Berechnete Zeit für die Orientierung
    
    if cols[col_idx].button(f"+{h}h\n{time_str}", key=f"btn_{h}"):
        st.session_state.lead_time = h

# 4. JSON / Farb-Einstellungen
st.sidebar.subheader("🎨 Karten-Einstellungen")
settings = load_settings()

if parameter in settings:
    new_cmap = st.sidebar.text_input("Colormap (Matplotlib)", settings[parameter]["cmap"])
    new_vmin = st.sidebar.number_input("Skala Minimum", value=float(settings[parameter]["vmin"]))
    new_vmax = st.sidebar.number_input("Skala Maximum", value=float(settings[parameter]["vmax"]))
    
    if st.sidebar.button("💾 Design in GitHub speichern"):
        settings[parameter]["cmap"] = new_cmap
        settings[parameter]["vmin"] = new_vmin
        settings[parameter]["vmax"] = new_vmax
        save_settings_to_github(settings)

# --- HAUPTBEREICH ---

st.write(f"**Aktuelle Vorhersagezeit:** +{st.session_state.lead_time} Stunden")
st.write(f"**Gültig für (Lokalzeit):** {(current_time + timedelta(hours=st.session_state.lead_time)).strftime('%d.%m.%Y - %H:%M Uhr')}")

# Daten laden und berechnen
data = get_hybrid_data(parameter, st.session_state.lead_time, correction)

# Karte plotten
st.pyplot(plot_static_map(data, settings, parameter))

st.info("💡 **Hinweis:** Dies ist die Basis-Struktur. Die Karte zeigt aktuell simulierte Hybrid-Daten. Das GitHub-Auto-Update für die JSON-Datei und das Menü sind voll funktionsfähig!")
