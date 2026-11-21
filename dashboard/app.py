"""Dashboard Streamlit — suivi de flotte en quasi temps réel (D1 à D7).

  streamlit run dashboard/app.py
  (Docker) docker compose -f infra/docker-compose.rs.yml --profile app up -d dashboard
           puis http://localhost:8501

Rafraîchissement par requêtes périodiques (st.fragment(run_every=...)), sans
connexion push. Si le cluster ne répond pas (bascule du primaire, nœuds
arrêtés), la page reste affichée avec les dernières données reçues et un
message « reconnexion », puis repart seule.
"""

import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import pydeck as pdk
import streamlit as st
from pymongo.errors import PyMongoError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard import data  # noqa: E402
from generator.routes import CITIES  # noqa: E402  (12 villes, sans dépendance)

st.set_page_config(page_title="Fleet Tracking", page_icon="🚚", layout="wide")


# ------------------------------------------------------------------ connexion
@st.cache_resource
def get_client():
    return data.make_client()


def get_db():
    return get_client()[data.DB_NAME]


@st.cache_data
def route_paths():
    return data.load_route_paths()


def safe(key, fn, *args):
    """Exécute une requête ; en cas de panne, renvoie la dernière valeur connue + l'erreur."""
    try:
        value = fn(*args)
        st.session_state[key] = value
        st.session_state["last_ok"] = time.time()
        return value, None
    except PyMongoError as exc:
        return st.session_state.get(key), exc


def outage_banner(errors, retry_s):
    """D7 : message de reconnexion au lieu d'une page d'erreur."""
    errors = [e for e in errors if e is not None]
    if not errors:
        return
    last = st.session_state.get("last_ok")
    since = (f" — dernières données reçues à {datetime.fromtimestamp(last):%H:%M:%S}"
             if last else "")
    st.warning(f"⚠️ Cluster injoignable ou bascule du primaire en cours : reconnexion…"
               f"{since}. Nouvelle tentative dans {retry_s} s.  \n"
               f"`{type(errors[0]).__name__}`", icon="🔄")


# ------------------------------------------------------------------ barre latérale
st.sidebar.title("🚚 Fleet Tracking")
refresh_s = st.sidebar.select_slider("Rafraîchissement de la carte (s)", [5, 10, 15, 30], value=10)
window_h = st.sidebar.select_slider("Fenêtre des statistiques (h)", [1, 2, 3, 6, 24], value=1)
st.sidebar.caption(f"Base `{data.DB_NAME}` · lecture `primaryPreferred`")
st.sidebar.markdown("**Légende**  \n🟢 en route · ⚪ à l'arrêt · 🔴 surchauffe > 105 °C")


# ------------------------------------------------------------------ D1, D2, D7 : temps réel
def cached(key):
    return st.session_state.get(key)


def live_section():
    db = get_db()
    # 1) Sonde : état du Replica Set. Si le cluster est injoignable, on n'attend pas le délai
    #    de chaque requête suivante : on affiche tout de suite les dernières données connues.
    cluster, error = safe("cluster", data.fetch_cluster_status, get_client())
    outage = error is not None
    st.session_state["outage"] = outage
    ref = state = fuel = alerts = None
    if not outage:
        ref, error = safe("ref", data.fetch_reference_time, db)
    if error is None:
        state, error = safe("state", data.fetch_state, db)
    if error is None:
        fuel, error = safe("fuel", data.fetch_avg_fuel, db, ref)
    if error is None:
        alerts, error = safe("alerts_count", lambda: len(data.fetch_alerts(db, ref)))
    if error is not None:   # panne pendant la séquence : dernières valeurs connues
        ref, state, fuel, alerts = (cached("ref"), cached("state"), cached("fuel"),
                                    cached("alerts_count"))
    outage_banner([error], refresh_s)

    # État du Replica Set
    if cluster:
        cols = st.columns(len(cluster) + 1)
        icons = {"PRIMARY": "🟢", "SECONDARY": "🔵"}
        for col, m in zip(cols, cluster):
            if outage:
                col.markdown(f"⚫ **{m['nœud']}** · état inconnu")
            else:
                col.markdown(f"{icons.get(m['état'], '🔴')} **{m['nœud']}** · {m['état']}")
        if outage:
            cols[-1].markdown("❌ **Aucun nœud ne répond**")
        elif not any(m["état"] == "PRIMARY" for m in cluster):
            cols[-1].markdown("⏳ **Élection en cours** — lectures servies par un secondaire")
        else:
            cols[-1].markdown(f"🕒 données à **{ref:%H:%M:%S}** UTC" if ref else "")

    if state is None or ref is None:
        st.info("En attente des premières données…")
        return

    # Données figées : aucun message récent (générateur arrêté ou base de référence statique)
    age_s = (datetime.now(timezone.utc) - ref).total_seconds()
    if not outage and age_s > data.STALE_SECONDS:
        st.info(f"⏸️ Aucun nouveau message depuis **{data.format_age(age_s)}** : les camions "
                f"affichent leur dernière position connue ({ref:%d/%m %H:%M:%S} UTC). "
                "Lancez le générateur en mode temps réel pour les voir rouler "
                "(voir `dashboard/README.md`).", icon="🚚")

    k = data.kpis(state, ref, fuel, alerts)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Camions actifs", k["active"], f"{k['moving']} en route", delta_color="off",
              help=f"Message reçu il y a moins de {data.ACTIVE_MINUTES} min, sur {k['trucks']} camions")
    c2.metric("Vitesse moy.", f"{k['avg_speed']:.0f} km/h" if k["avg_speed"] else "—",
              help="Moyenne des camions en route (vehicle_state)")
    c3.metric("Conso. moy.", f"{k['avg_fuel_lph']:.0f} L/h" if k["avg_fuel_lph"] else "—",
              help="Consommation moyenne de la flotte sur les 5 dernières minutes (telemetry)")
    c4.metric("Surchauffe", k["overheating_now"], help="Camions au-dessus de 105 °C en ce moment")
    c5.metric("Alertes 24 h", k["alerts_24h"] if k["alerts_24h"] is not None else "—",
              help="Camions ayant dépassé 105 °C sur 24 h (pipeline d)")

    layers = [pdk.Layer("PathLayer", route_paths(), get_path="path", get_color=[150, 150, 150, 90],
                        width_min_pixels=2, pickable=False)]
    layers.append(pdk.Layer("ScatterplotLayer", state, get_position=["lon", "lat"],
                            get_fill_color="color", get_radius=900, radius_min_pixels=3,
                            radius_max_pixels=9, pickable=True))
    st.pydeck_chart(pdk.Deck(
        layers=layers, map_style="light",
        initial_view_state=pdk.ViewState(latitude=35.4, longitude=9.9, zoom=6.2),
        tooltip={"html": "<b>{vehicle_id}</b> · {status}<br/>{region} · {route_id}<br/>"
                         "{speed_kmh} km/h · {engine_temp_c} °C · carburant {fuel_level_pct} %"},
    ), height=520)
    st.caption(f"{len(state)} camions · carte rafraîchie toutes les {refresh_s} s · "
               f"source : collection `vehicle_state`")


# ------------------------------------------------------------------ D3, D4, D5 : analyses
def analytics_section():
    db = get_db()
    ref = st.session_state.get("ref")
    if ref is None:
        return
    if st.session_state.get("outage"):
        # Cluster injoignable (détecté par la section temps réel) : pas de nouvelle attente
        regions, hist, alerts = cached("regions"), cached("hist"), cached("alerts")
        st.caption("⏸️ Analyses figées : cluster injoignable, dernières valeurs affichées.")
    else:
        regions, e1 = safe("regions", data.fetch_speed_by_region, db, ref, window_h)
        hist, e2 = safe("hist", data.fetch_speed_histogram, db, ref, window_h)
        alerts, e3 = safe("alerts", data.fetch_alerts, db, ref)
        outage_banner([e1, e2, e3], 30)

    left, right = st.columns(2)
    with left:
        st.subheader(f"Vitesse moyenne par région ({window_h} h)")
        if regions is not None and not regions.empty:
            fig = px.bar(regions.sort_values("vitesse moyenne (km/h)"),
                         x="vitesse moyenne (km/h)", y="région", orientation="h",
                         hover_data=["messages"], color="vitesse moyenne (km/h)",
                         color_continuous_scale="Viridis")
            fig.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=0),
                              coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader(f"Distribution des vitesses ({window_h} h)")
        if hist is not None and not hist.empty:
            fig = px.bar(hist, x="tranche", y="messages", labels={"tranche": "km/h"})
            fig.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Camions en alerte de surchauffe (24 h)")
    if alerts is not None:
        if alerts.empty:
            st.success("Aucune alerte sur les dernières 24 h.")
        else:
            st.dataframe(alerts, use_container_width=True, hide_index=True, height=300)


# ------------------------------------------------------------------ D6 : recherche géographique
def geo_section():
    st.subheader("Recherche géographique")
    c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
    city = c1.selectbox("Centre", ["Point personnalisé"] + list(CITIES), index=1)
    lon0, lat0 = CITIES.get(city, (10.1815, 36.8065))
    lat = c2.number_input("Latitude", value=float(lat0), format="%.4f", disabled=city != "Point personnalisé")
    lon = c3.number_input("Longitude", value=float(lon0), format="%.4f", disabled=city != "Point personnalisé")
    radius = c4.slider("Rayon (km)", 1, 50, 10)
    if city != "Point personnalisé":
        lon, lat = lon0, lat0

    found, err = safe("nearby", data.fetch_nearby, get_db(), lon, lat, radius)
    outage_banner([err], 0)
    if found is None:
        return
    st.markdown(f"**{len(found)} camion(s)** à moins de {radius} km de "
                f"{city if city != 'Point personnalisé' else f'({lat:.4f}, {lon:.4f})'} "
                f"— `$geoNear` sur l'index 2dsphere de `vehicle_state`")
    center = pd.DataFrame([{"lon": lon, "lat": lat}])
    m, t = st.columns([3, 2])
    with m:
        st.pydeck_chart(pdk.Deck(
            layers=[
                pdk.Layer("ScatterplotLayer", center, get_position=["lon", "lat"],
                          get_radius=radius * 1000, get_fill_color=[37, 99, 235, 40],
                          stroked=True, get_line_color=[37, 99, 235, 160], line_width_min_pixels=1),
                pdk.Layer("ScatterplotLayer", found, get_position=["lon", "lat"],
                          get_fill_color="color", get_radius=120, radius_min_pixels=4,
                          pickable=True),
            ],
            map_style="light",
            initial_view_state=pdk.ViewState(latitude=lat, longitude=lon,
                                             zoom=max(7.5, 12 - radius / 6)),
            tooltip={"html": "<b>{vehicle_id}</b> · {status}<br/>{distance_km} km · {speed_kmh} km/h"},
        ), height=420)
    with t:
        st.dataframe(found[["vehicle_id", "distance_km", "status", "speed_kmh", "region"]],
                     use_container_width=True, hide_index=True, height=420)


# ------------------------------------------------------------------ page
st.title("Suivi de flotte en temps réel")
st.fragment(run_every=refresh_s)(live_section)()
st.divider()
st.fragment(run_every=30)(analytics_section)()
st.divider()
st.fragment(geo_section)()
st.caption(f"Page générée à {datetime.now(timezone.utc):%H:%M:%S} UTC · Projet NoSQL — "
           "MongoDB Replica Set rs0")
