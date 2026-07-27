import streamlit as st

# Titel und Layout der Seite
st.set_page_config(
    page_title="Regionale Wetter-KI",
    page_icon="🌦️",
    layout="wide"
)

# Überschrift
st.title("🌦️ Mein regionales KI-Wettermodell")
st.write("Willkommen in meiner Wetter-Zentrale! Hier entsteht Schritt für Schritt das eigene Downscaling-Modell.")

# Eine kleine Sidebar für Einstellungen
st.sidebar.header("⚙️ Einstellungen")
region = st.sidebar.selectbox(
    "Wähle deine Region:",
    ["Deutschland (Gesamt)", "Mitteldeutschland", "Brandenburg / Region Elbe-Elster"]
)

st.sidebar.write(f"Aktuell ausgewählt: **{region}**")

# Hauptbereich
st.info("Das Repository ist bereit. Als Nächstes bringen wir die Datenquelle (GRIB2 & DWD) an den Start!")

if st.button("System-Check starten"):
    st.success("App läuft stabil auf Streamlit! Bereit für den nächsten Baustein.")
