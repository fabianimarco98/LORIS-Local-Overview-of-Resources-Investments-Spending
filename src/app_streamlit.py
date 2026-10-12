# ============================================================
# LORIS — Multi-Bank Financial Analytics & Monte Carlo Forecaster
# 100% Local, Private, Zero-Knowledge & Statement-Driven
# Bilingual: Italiano (IT) & English (EN)
# ============================================================
from pathlib import Path
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import banking
from banking.anonymizer import PIIScrubber
from banking.local_llm import LocalLLMClient, RECOMMENDED_MODELS
from banking.portfolio import PortfolioAggregator, PortfolioSummary, ASSET_CLASS_LABELS, ASSET_CLASS_COLORS, get_asset_class_label
import bank_data_manager as bdm
import simulation_engine as se
from i18n import t, get_category_translation, AVAILABLE_LANGUAGES

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent if (CURRENT_DIR.parent / "input").exists() else CURRENT_DIR
DATA_DIR = PROJECT_ROOT / "input"
STATEMENTS_DIR = DATA_DIR / "bank_statements"
INVESTMENTS_DIR = DATA_DIR / "investments"
WALLET_DIR = DATA_DIR / "wallet"
FAVICON_PATH = CURRENT_DIR / "assets" / "favicon.png"
if not FAVICON_PATH.exists() and (PROJECT_ROOT / "assets" / "favicon.png").exists():
    FAVICON_PATH = PROJECT_ROOT / "assets" / "favicon.png"

st.set_page_config(
    page_title="LORIS — Local Overview of Resources, Investments & Spending",
    page_icon=str(FAVICON_PATH) if FAVICON_PATH.exists() else "🐾",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main { background-color: #0b0f19; }
    .stMetric {
        background-color: #111827;
        padding: 14px 18px;
        border-radius: 12px;
        border: 1px solid #1f2937;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.25);
    }
    .status-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.82rem;
        font-weight: 600;
    }
    .badge-green { background-color: #064e3b; color: #34d399; border: 1px solid #059669; }
    .badge-blue { background-color: #0c4a6e; color: #38bdf8; border: 1px solid #0284c7; }
    .badge-amber { background-color: #78350f; color: #fbbf24; border: 1px solid #d97706; }
    .badge-red { background-color: #450a0a; color: #f87171; border: 1px solid #b91c1c; }
    .card-box {
        background-color: #131b2e;
        padding: 18px;
        border-radius: 12px;
        border: 1px solid #23314d;
        margin-bottom: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------
# SESSION STATE & INIZIALIZZAZIONE
# ------------------------------------------------------------
if "lang" not in st.session_state:
    st.session_state.lang = "it"

lang = st.session_state.lang

if "df_macro" not in st.session_state:
    m, r, s = bdm.load_configs(DATA_DIR)
    st.session_state.df_macro = m
    st.session_state.df_rec = r
    st.session_state.df_shocks = s

if "saved_file_signatures" not in st.session_state:
    st.session_state.saved_file_signatures = set()

import copy

if "llm_client" not in st.session_state:
    st.session_state.llm_client = LocalLLMClient()

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "user_overrides" not in st.session_state:
    st.session_state.user_overrides = bdm.load_user_overrides()

if "undo_stack" not in st.session_state:
    st.session_state.undo_stack = []

if "last_uploaded_files" not in st.session_state:
    st.session_state.last_uploaded_files = []


def push_undo_state():
    """Salva uno snapshot dello stato corrente delle modifiche nello stack di annullamento."""
    st.session_state.undo_stack.append(copy.deepcopy(st.session_state.user_overrides))
    if len(st.session_state.undo_stack) > 25:
        st.session_state.undo_stack.pop(0)


def pop_undo_state():
    """Ripristina lo stato precedente delle modifiche dallo stack di annullamento."""
    if st.session_state.undo_stack:
        st.session_state.user_overrides = st.session_state.undo_stack.pop()
        bdm.save_user_overrides(st.session_state.user_overrides)
        st.cache_data.clear()
        st.toast("↩️ Modifica annullata!")
        st.rerun()


def reset_all_overrides():
    """Azzera tutte le modifiche manuali e ripristina la lettura originale dagli estratti conto."""
    push_undo_state()
    st.session_state.user_overrides = {
        "balance_overrides": {},
        "category_overrides": {},
        "transfer_flags": {},
        "excluded_transactions": [],
        "manual_transactions": [],
    }
    bdm.save_user_overrides(st.session_state.user_overrides)
    st.cache_data.clear()
    st.toast("♻️ Dati ripristinati agli estratti conto originali!")
    st.rerun()


def undo_last_upload():
    """Annulla l'ultimo caricamento eliminando i file appena caricati da disco."""
    if st.session_state.last_uploaded_files:
        for fname in st.session_state.last_uploaded_files:
            bdm.delete_statement_file(fname)
        st.session_state.last_uploaded_files = []
        st.cache_data.clear()
        st.toast("↩️ Ultimo caricamento annullato!")
        st.rerun()


def delete_file_and_refresh(fname: str):
    """Elimina uno specifico file estratto conto da disco e ricarica i dati."""
    if bdm.delete_statement_file(fname):
        if fname in st.session_state.last_uploaded_files:
            st.session_state.last_uploaded_files.remove(fname)
        st.cache_data.clear()
        st.toast(f"🗑️ File {fname} eliminato!")
        st.rerun()


def save_uploaded_statements(files: List[Any]) -> bool:
    """
    Salva in modo permanente su disco i file caricati via drag & drop.
    Ritorna True se almeno un nuovo file è stato scritto, evitando rerun infiniti.
    Traccia i file salvati in st.session_state.last_uploaded_files per consentire l'Undo.
    """
    if not files:
        return False
    if "saved_file_signatures" not in st.session_state:
        st.session_state.saved_file_signatures = set()

    STATEMENTS_DIR.mkdir(parents=True, exist_ok=True)
    any_saved = False
    newly_saved_names = []

    for uf in files:
        sig = f"{uf.name}_{uf.size}"
        if sig in st.session_state.saved_file_signatures:
            continue

        clean_name = Path(uf.name).name
        dest_file = STATEMENTS_DIR / clean_name
        try:
            with open(dest_file, "wb") as f_out:
                f_out.write(uf.getbuffer())
            st.session_state.saved_file_signatures.add(sig)
            newly_saved_names.append(clean_name)
            any_saved = True
        except Exception as e:
            st.error(f"Errore salvataggio {clean_name}: {e}")

    if newly_saved_names:
        st.session_state.last_uploaded_files = newly_saved_names

    return any_saved


# ------------------------------------------------------------
# CARICAMENTO DATI BANCARI MULTI-CONTO (100% DA ESTRATTI CONTO)
# ------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_bank_summary_cached(dir_mtime: float, count_files: int):
    statements, summary = bdm.load_all_bank_statements(
        statements_dir=str(STATEMENTS_DIR)
    )
    return statements, summary


search_dirs = [STATEMENTS_DIR, INVESTMENTS_DIR, WALLET_DIR]
dir_mtime = 0.0
file_count = 0
for sd in search_dirs:
    if sd.exists():
        valid_files = [f for f in sd.iterdir() if f.is_file() and not f.name.startswith(".")]
        file_count += len(valid_files)
        if valid_files:
            dir_mtime = max(dir_mtime, max(f.stat().st_mtime for f in valid_files))

raw_statements, raw_summary = load_bank_summary_cached(dir_mtime, file_count)

# Copia profonda per evitare mutazioni indesiderate dell'oggetto in cache
statements = [copy.deepcopy(s) for s in raw_statements]
summary = copy.deepcopy(raw_summary)

# Applicazione delle personalizzazioni e modifiche manuali dell'utente
statements, summary = bdm.apply_user_overrides(
    statements, summary, st.session_state.user_overrides
)

# Categorizzazione ed arricchimento transazioni basata unicamente sui movimenti
df_tx_categorized = bdm.categorize_transactions(summary.all_transactions, summary.internal_transfers)
bank_stats = bdm.compute_bank_monthly_statistics(df_tx_categorized)


# ------------------------------------------------------------
# HELPER PER DOWNLOAD / INSTALLAZIONE MODELLI OLLAMA
# ------------------------------------------------------------
def handle_model_pull(client: LocalLLMClient, model_tag: str):
    progress_bar = st.progress(0, text=f"Download {model_tag}...")
    status_text = st.empty()

    try:
        for evt in client.pull_model_stream(model_tag):
            if evt.get("error"):
                st.error(f"Error: {evt.get('status')}")
                return False

            pct = int(evt.get("percent", 0.0))
            st_text = evt.get("status", "")
            completed_mb = round(evt.get("completed", 0) / (1024 * 1024), 1)
            total_mb = round(evt.get("total", 0) / (1024 * 1024), 1)

            if total_mb > 0:
                msg = f"{st_text} ({completed_mb:.0f} MB / {total_mb:.0f} MB - {pct}%)"
            else:
                msg = f"{st_text}..."

            progress_bar.progress(min(max(pct, 0), 100), text=msg)
            status_text.caption(f"Status: {st_text}")

            if evt.get("done"):
                progress_bar.progress(100, text=f"✅ {model_tag} ready!")
                st.success(f"Model **{model_tag}** successfully installed!")
                client.preferred_model = model_tag
                st.cache_data.clear()
                return True
    except Exception as ex:
        st.error(f"Error: {ex}")
        return False
    return True


# ------------------------------------------------------------
# SIDEBAR: SELETTORE LINGUA, ESTRATTI CONTO, MODELLO AI
# ------------------------------------------------------------
with st.sidebar:
    col_s1, col_s2 = st.columns([0.3, 0.7])
    with col_s1:
        loris_logo_path = CURRENT_DIR / "assets" / "loris_icon_128.png"
        if loris_logo_path.exists():
            st.image(str(loris_logo_path), width=64)
    with col_s2:
        st.title("LORIS")
        st.caption(
            "Local Overview of Resources, Investments & Spending",
            help="🐾 Ispirato al primate notturno Slow Loris (Nycticebus), celebre per i grandi occhi vigili che scrutano con calma e precisione nell'oscurità. LORIS garantisce custodia vigile, offline e riservata al 100%."
        )

    # Selettore Lingua / Language Switcher
    lang_options = list(AVAILABLE_LANGUAGES.keys())
    lang_labels = list(AVAILABLE_LANGUAGES.values())
    curr_idx = lang_options.index(lang) if lang in lang_options else 0
    selected_lang = st.selectbox(
        "🌐 " + t("language", lang),
        options=lang_options,
        format_func=lambda code: AVAILABLE_LANGUAGES.get(code, code),
        index=curr_idx,
        key="lang_selector"
    )
    if selected_lang != st.session_state.lang:
        st.session_state.lang = selected_lang
        st.rerun()

    lang = st.session_state.lang

    st.markdown("---")

    # 1. Box Ingestion Estratti Conto & Liste Investimenti
    with st.expander("📂 " + t("upload_title", lang), expanded=True):
        new_files = st.file_uploader(
            t("upload_drag_drop", lang),
            accept_multiple_files=True,
            type=["csv", "tsv", "xlsx", "xls", "pdf", "json"],
            key="bank_file_uploader",
            help=t("upload_help", lang)
        )
        if new_files and save_uploaded_statements(new_files):
            st.cache_data.clear()
            st.toast(f"✅ {t('upload_success', lang)}")
            st.rerun()

        # Pulsante Undo Ultimo Caricamento
        if st.session_state.last_uploaded_files:
            if st.button("↩️ " + t("undo_upload", lang), use_container_width=True, key="btn_undo_upload_sidebar"):
                undo_last_upload()

        st.markdown(f"**{t('loaded_accounts', lang)}:** {len(statements)}")
        for stmt in statements:
            if "invest" in stmt.asset_class.lower() or "broker" in stmt.account_type.lower():
                icon = "📊"
            elif stmt.asset_class == "EXPENSE_TRACKER" or stmt.account_type == "ExpenseTracker":
                icon = "📱"
            elif "revolut" in stmt.institution.lower():
                icon = "💳"
            elif "republic" in stmt.institution.lower():
                icon = "📈"
            else:
                icon = "🏦"

            if stmt.asset_class == "EXPENSE_TRACKER":
                tot_exp = stmt.metadata.get("total_expenses_tracked", 0.0) if stmt.metadata else 0.0
                st.caption(f"{icon} **{stmt.institution}**: {len(stmt.transactions)} spese (tracciate €{tot_exp:,.2f})")
            else:
                st.caption(f"{icon} **{stmt.institution}** ({stmt.account_id}): €{stmt.ending_balance:,.2f}")

        # Lista file fisici su disco con pulsante di eliminazione per ciascuno
        disk_files = []
        for sd in search_dirs:
            if sd.exists():
                for f in sorted(sd.iterdir()):
                    if f.is_file() and not f.name.startswith("."):
                        disk_files.append(f)

        if disk_files:
            st.markdown(f"<span style='font-size:0.85em; font-weight:600;'>{t('loaded_files_list', lang)}</span>", unsafe_allow_html=True)
            for df_file in disk_files:
                col_fn, col_del = st.columns([0.80, 0.20])
                with col_fn:
                    short_name = df_file.name if len(df_file.name) <= 20 else df_file.name[:18] + "..."
                    st.caption(f"📄 `{short_name}`")
                with col_del:
                    if st.button("🗑️", key=f"del_sidebar_{df_file.name}", help=f"{t('delete_file', lang)}: {df_file.name}"):
                        delete_file_and_refresh(df_file.name)

        col_act1, col_act2 = st.columns([0.5, 0.5])
        with col_act1:
            if st.button("🔄 " + ("Ricarica" if lang == "it" else "Reload"), use_container_width=True, key="btn_reload_sidebar"):
                st.cache_data.clear()
                st.rerun()
        with col_act2:
            if st.session_state.undo_stack and st.button("↩️ Undo", use_container_width=True, key="btn_undo_sidebar"):
                pop_undo_state()

        has_overrides = any(st.session_state.user_overrides.get(k) for k in ["balance_overrides", "category_overrides", "transfer_flags", "excluded_transactions", "manual_transactions"])
        if has_overrides:
            if st.button("♻️ " + t("reset_overrides", lang), use_container_width=True, key="btn_reset_overrides_sidebar"):
                reset_all_overrides()

    # Parametro Dinamico: Tasso Liquidità Remunerata (BCE / Trade Republic)
    cash_yield_val = st.slider(
        "🏦 " + ("Tasso BCE / Trade Republic (%):" if lang == "it" else "ECB / Trade Republic Rate (%):"),
        min_value=0.0,
        max_value=5.0,
        value=float(st.session_state.get("custom_cash_rate", 2.5)),
        step=0.1,
        help=("Tasso lordo annuo riconosciuto sulla liquidità libera (es. tasso di deposito BCE ~2.5% o promozioni referral)."
              if lang == "it" else
              "Gross annual interest rate paid on high-yield cash deposits.")
    )
    st.session_state.custom_cash_rate = cash_yield_val
    est_annual_int = summary.total_high_yield_cash * (cash_yield_val / 100.0)
    st.caption(
        f"💰 Rendimento stimato: **€ {est_annual_int:,.2f}/anno** (~€ {est_annual_int/12:,.2f}/m)"
        if lang == "it" else
        f"💰 Est. interest: **€ {est_annual_int:,.2f}/yr** (~€ {est_annual_int/12:,.2f}/mo)"
    )

    # 2. Box Modello AI Locale
    st.markdown("---")
    st.subheader("🤖 " + ("AI Locale" if lang == "it" else "Local AI"))
    client: LocalLLMClient = st.session_state.llm_client
    llm_status = client.check_health()

    if llm_status.is_available:
        st.markdown(f"<span class='status-badge badge-green'>🟢 Ollama (11434)</span>", unsafe_allow_html=True)
        if llm_status.available_models:
            active_model = client.preferred_model or llm_status.model_name
            idx = llm_status.available_models.index(active_model) if active_model in llm_status.available_models else 0
            selected_model = st.selectbox(
                t("model_selection", lang) + ":",
                llm_status.available_models,
                index=idx,
                key="sidebar_model_select"
            )
            if selected_model != client.preferred_model:
                client.preferred_model = selected_model
                st.session_state.llm_client.preferred_model = selected_model
    else:
        st.markdown("<span class='status-badge badge-amber'>🟡 " + ("Motore Offline" if lang == "it" else "Offline Engine") + "</span>", unsafe_allow_html=True)
        st.caption("Ollama offline. " + ("Risposte garantite dal motore offline." if lang == "it" else "Answers guaranteed by offline rule engine."))
        if llm_status.is_cli_installed:
            if st.button("▶️ " + ("Avvia Ollama" if lang == "it" else "Start Ollama"), use_container_width=True):
                with st.spinner("Starting Ollama..."):
                    ok, msg = client.start_ollama_daemon()
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
        else:
            st.info("💡 `brew install ollama`")


# ------------------------------------------------------------
# HEADER PRINCIPALE
# ------------------------------------------------------------
col_head_logo, col_head_title = st.columns([0.07, 0.93])
with col_head_logo:
    loris_logo_path = CURRENT_DIR / "assets" / "loris_icon_128.png"
    if loris_logo_path.exists():
        st.image(str(loris_logo_path), width=60)
with col_head_title:
    st.title("LORIS")
    st.caption(t("app_subtitle", lang))

if len(statements) == 0:
    st.info(
        ("👋 **Nessun estratto conto caricato al momento.**\n\n"
         "• Trascina i tuoi file bancari (PDF, CSV, Excel) nel riquadro nella barra laterale sinistra.\n"
         "• Oppure copiali nella cartella `input/bank_statements/`.\n\n"
         "LORIS leggerà i movimenti, neutralizzerà i giroconti tra conti propri e calcolerà statistiche e proiezioni con privacy totale.")
        if lang == "it" else
        ("👋 **No bank statements loaded yet.**\n\n"
         "• Drag and drop your bank statements (PDF, CSV, Excel) into the sidebar uploader.\n"
         "• Or copy them directly into the `input/bank_statements/` folder.\n\n"
         "LORIS will parse your transactions, reconcile internal transfers, and compute retrospective analytics and future forecasts with 100% local privacy.")
    )

# ------------------------------------------------------------
# CRUSCOTTO KPI PRINCIPALI (100% DA ESTRATTI CONTO)
# ------------------------------------------------------------
col_k1, col_k2, col_k3, col_k4, col_k5, col_k6 = st.columns(6)
with col_k1:
    st.metric(t("total_net_worth", lang), f"€ {summary.total_net_worth:,.2f}")
with col_k2:
    st.metric(t("liquid_cash", lang), f"€ {summary.total_liquid_cash:,.2f}")
with col_k3:
    st.metric(t("high_yield_cash", lang), f"€ {summary.total_high_yield_cash:,.2f}")
with col_k4:
    st.metric(t("investments", lang), f"€ {summary.total_investments:,.2f}")
with col_k5:
    st.metric(t("avg_monthly_spending", lang), f"€ {summary.monthly_burn_rate:,.2f}")
with col_k6:
    st.metric(t("liquidity_buffer", lang), f"{summary.liquidity_buffer_months:.1f} " + ("Mesi" if lang == "it" else "Months"))


# ------------------------------------------------------------
# TABS PRINCIPALI (BILINGUE & DEEP-DIVE STORICO)
# ------------------------------------------------------------
tab_overview, tab_analytics, tab_statements, tab_sim, tab_ai, tab_settings = st.tabs([
    t("tab_overview", lang),
    t("tab_analytics", lang),
    t("tab_transactions", lang),
    t("tab_forecasting", lang),
    t("tab_ai", lang),
    t("tab_settings", lang),
])


# ------------------------------------------------------------
# TAB 1: PATRIMONIO & SALDI (NET WORTH & ACCOUNTS)
# ------------------------------------------------------------
with tab_overview:
    st.subheader(t("balance_by_account", lang))

    col_ov1, col_ov2 = st.columns([1, 1])

    with col_ov1:
        # Donut Chart Asset Allocation
        alloc_data = []
        for k, v in summary.asset_allocation.items():
            if v > 0:
                label = get_asset_class_label(k, lang)
                alloc_data.append({"Asset Class": label, "Valore": v})

        if alloc_data:
            df_pie = pd.DataFrame(alloc_data)
            fig_pie = px.pie(
                df_pie,
                names="Asset Class",
                values="Valore",
                hole=0.45,
                color="Asset Class",
                title=t("asset_allocation", lang),
            )
            fig_pie.update_traces(textposition="inside", textinfo="percent+label")
            fig_pie.update_layout(showlegend=False, margin=dict(t=40, b=10, l=10, r=10))
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info(t("no_statements_found", lang))

    with col_ov2:
        st.markdown(f"### 🏦 {t('balance_by_account', lang)}")
        if not summary.accounts_summary.empty:
            df_acc_view = summary.accounts_summary.copy()
            df_acc_view["display_balance"] = df_acc_view.apply(
                lambda r: f"€ {r['balance']:,.2f}" if not r.get("is_tracker", False) else f"€ 0.00 (Registro)",
                axis=1
            )
            df_acc_view["display_expenses"] = df_acc_view["tracked_expenses"].apply(lambda v: f"€ {v:,.2f}" if v > 0 else "-")

            df_acc_view = df_acc_view[["institution", "account_id", "asset_class_label", "display_balance", "display_expenses", "tx_count"]]
            if lang == "it":
                df_acc_view.columns = ["Istituto", "Identificativo Conto", "Tipologia", "Saldo Patrimoniale", "Volume Spese", "Movimenti"]
            else:
                df_acc_view.columns = ["Institution", "Account ID", "Type", "Asset Balance", "Tracked Volume", "Transactions"]

            st.dataframe(
                df_acc_view,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.warning(t("no_statements_found", lang))

        st.info(
            f"💡 **{'Cassa totale disponibile:' if lang == 'it' else 'Total available cash:'}** `€ {summary.recommended_starting_cash:,.2f}`\n\n"
            f"{'Include la liquidità su c/c e i depositi remunerati.' if lang == 'it' else 'Includes liquid checking cash and high-yield cash deposits.'}"
        )

    # ------------------------------------------------------------
    # MODIFICA MANUALE SALDI DEI CONTI (OVERRIDE SALDI)
    # ------------------------------------------------------------
    with st.expander("✏️ " + t("manual_balances_title", lang), expanded=False):
        st.caption(t("manual_balances_desc", lang))

        bal_overrides = st.session_state.user_overrides.get("balance_overrides", {})
        temp_balances = {}
        has_user_bal_override = False

        for stmt in statements:
            if stmt.asset_class == "EXPENSE_TRACKER":
                continue
            col_b1, col_b2, col_b3 = st.columns([0.40, 0.30, 0.30])
            with col_b1:
                st.write(f"🏦 **{stmt.institution}** (`{stmt.account_id}`)")
            with col_b2:
                # Cerca saldo originale non modificato da raw_statements
                orig_s = next((rs for rs in raw_statements if rs.account_id == stmt.account_id), stmt)
                st.caption(f"{t('original_balance', lang)}: **€ {orig_s.ending_balance:,.2f}**")
            with col_b3:
                curr_val = float(bal_overrides.get(stmt.account_id, stmt.ending_balance))
                edited_val = st.number_input(
                    f"{t('custom_balance', lang)}",
                    value=curr_val,
                    step=50.0,
                    key=f"input_override_bal_{stmt.account_id}",
                    label_visibility="collapsed"
                )
                temp_balances[stmt.account_id] = edited_val
                if stmt.account_id in bal_overrides:
                    has_user_bal_override = True

        col_sb1, col_sb2 = st.columns([0.5, 0.5])
        with col_sb1:
            if st.button("💾 " + t("save_balances_btn", lang), use_container_width=True, key="btn_save_manual_balances"):
                push_undo_state()
                st.session_state.user_overrides["balance_overrides"] = temp_balances
                bdm.save_user_overrides(st.session_state.user_overrides)
                st.cache_data.clear()
                st.toast(f"✅ {t('balances_saved_success', lang)}")
                st.rerun()
        with col_sb2:
            if st.session_state.undo_stack and st.button("↩️ " + t("undo_edit", lang), use_container_width=True, key="btn_undo_balances"):
                pop_undo_state()

    # Sezione Portafoglio Investimenti & ETF (se presente)
    all_holdings = []
    for stmt in statements:
        if stmt.metadata and "holdings" in stmt.metadata:
            all_holdings.extend(stmt.metadata["holdings"])

    if all_holdings or summary.total_investments > 0:
        st.markdown("---")
        st.markdown(f"### 📈 {t('portfolio_etf_title', lang)}")
        if all_holdings:
            tot_mv = sum(h.get("market_value", 0.0) for h in all_holdings)
            tot_cb = sum(h.get("cost_basis", 0.0) for h in all_holdings)
            tot_pnl = tot_mv - tot_cb
            tot_pnl_pct = (tot_pnl / tot_cb * 100.0) if tot_cb > 0 else 0.0

            col_inv1, col_inv2, col_inv3, col_inv4 = st.columns(4)
            with col_inv1:
                st.metric("Valore Portafoglio" if lang == "it" else "Portfolio Value", f"€ {tot_mv:,.2f}")
            with col_inv2:
                st.metric("Costo di Carico" if lang == "it" else "Cost Basis", f"€ {tot_cb:,.2f}")
            with col_inv3:
                st.metric("Plusvalenza / P&L" if lang == "it" else "Gain/Loss (P&L)", f"€ {tot_pnl:,.2f}", delta=f"{tot_pnl_pct:+.2f}%")
            with col_inv4:
                st.metric("Posizioni / Titoli" if lang == "it" else "Holdings Count", f"{len(all_holdings)}")

            df_h_ui = pd.DataFrame(all_holdings)
            cols_show = [c for c in ["ticker", "name", "shares", "buy_price", "current_price", "market_value", "pnl", "pnl_pct", "asset_class"] if c in df_h_ui.columns]
            st.dataframe(
                df_h_ui[cols_show],
                column_config={
                    "ticker": st.column_config.TextColumn(label="Ticker / ISIN"),
                    "name": st.column_config.TextColumn(label="Nome Strumento" if lang == "it" else "Security Name"),
                    "shares": st.column_config.NumberColumn(format="%.2f", label="Quote / Pezzi" if lang == "it" else "Shares"),
                    "buy_price": st.column_config.NumberColumn(format="€ %.2f", label="Prezzo Carico" if lang == "it" else "Buy Price"),
                    "current_price": st.column_config.NumberColumn(format="€ %.2f", label="Prezzo Attuale" if lang == "it" else "Current Price"),
                    "market_value": st.column_config.NumberColumn(format="€ %.2f", label="Controvalore" if lang == "it" else "Market Value"),
                    "pnl": st.column_config.NumberColumn(format="€ %.2f", label="P&L (€)"),
                    "pnl_pct": st.column_config.NumberColumn(format="%.2f %%", label="P&L (%)"),
                    "asset_class": st.column_config.TextColumn(label="Classe Asset" if lang == "it" else "Asset Class"),
                },
                use_container_width=True,
                hide_index=True
            )
        else:
            st.metric("Valore Investimenti Totale" if lang == "it" else "Total Investments Value", f"€ {summary.total_investments:,.2f}")


# ------------------------------------------------------------
# TAB 2: ANALISI STORICA & STATISTICHE (HISTORICAL ANALYTICS)
# ------------------------------------------------------------
with tab_analytics:
    st.subheader(t("historical_title", lang))
    st.caption(t("historical_subtitle", lang))

    # Selettore della vista (Tutto Integrato vs Solo Banche vs Solo Wallet) se è presente un tracker
    active_view = "all"
    if summary.has_wallet_tracker:
        v_col1, v_col2 = st.columns([1, 2])
        with v_col1:
            st.markdown(f"**🔍 {t('data_view_mode', lang)}:**")
        with v_col2:
            active_view = st.radio(
                "Vista Dati",
                options=["all", "banks", "wallet"],
                format_func=lambda x: {
                    "all": t("view_all_combined", lang),
                    "banks": t("view_banks_only", lang),
                    "wallet": t("view_wallet_only", lang),
                }.get(x, x),
                horizontal=True,
                label_visibility="collapsed",
                key="analytics_view_mode_selector"
            )

    # Ricalcola le statistiche in base alla vista selezionata
    active_stats = bdm.compute_bank_monthly_statistics(df_tx_categorized, filter_source=active_view)

    # KPI Retrospettivi
    col_h1, col_h2, col_h3, col_h4 = st.columns(4)
    with col_h1:
        st.metric(t("total_inflows", lang), f"€ {active_stats.get('total_inflow', 0.0):,.2f}")
    with col_h2:
        st.metric(t("total_outflows", lang), f"€ {active_stats.get('total_outflow', 0.0):,.2f}")
    with col_h3:
        st.metric(t("net_savings", lang), f"€ {active_stats.get('net_savings', 0.0):,.2f}")
    with col_h4:
        st.metric(t("avg_savings_rate", lang), f"{active_stats.get('average_savings_rate', 0.0):.1f}%")

    col_h5, col_h6, col_h7, col_h8 = st.columns(4)
    with col_h5:
        st.metric(t("tracked_period", lang), f"{active_stats.get('total_tracked_months', 0)} " + ("Mesi" if lang == "it" else "Months"))
    with col_h6:
        st.metric(t("avg_monthly_spending", lang), f"€ {active_stats.get('monthly_expenses_mean', 0.0):,.2f}")
    with col_h7:
        st.metric(t("spending_std", lang), f"± € {active_stats.get('monthly_expenses_std', 0.0):,.2f}")
    with col_h8:
        disc = active_stats.get("discretionary_split", {})
        st.metric("Spese Discrezionali" if lang == "it" else "Discretionary Ratio", f"{disc.get('ratio', 0.0):.1f}%")

    st.markdown("---")

    # Approfondimento dedicato a Wallet se presente nei dati caricati
    if summary.has_wallet_tracker and summary.wallet_summary:
        w_sum = summary.wallet_summary
        st.markdown(f"### 📱 {t('wallet_deepdive_title', lang)}")
        st.caption(t("wallet_deepdive_subtitle", lang))

        col_w1, col_w2, col_w3, col_w4 = st.columns(4)
        with col_w1:
            st.metric(t("wallet_total_tracked", lang), f"€ {w_sum.get('total_expenses', 0.0):,.2f}")
        with col_w2:
            st.metric(t("wallet_cash_spent", lang), f"€ {w_sum.get('cash_expenses', 0.0):,.2f}", help=f"{w_sum.get('cash_tx_count', 0)} movimenti registrati come Contanti")
        with col_w3:
            st.metric(t("wallet_electronic_spent", lang), f"€ {w_sum.get('electronic_expenses', 0.0):,.2f}")
        with col_w4:
            st.metric(t("wallet_cash_pct", lang), f"{w_sum.get('cash_ratio_pct', 0.0):.1f}%")

        col_wg1, col_wg2 = st.columns(2)
        with col_wg1:
            top_w_cats = w_sum.get("top_categories", {})
            if top_w_cats:
                df_w_plot = pd.DataFrame(list(top_w_cats.items()), columns=["Categoria", "Totale Speso"])
                fig_w_pie = px.pie(
                    df_w_plot.head(10),
                    names="Categoria",
                    values="Totale Speso",
                    hole=0.40,
                    title="Top Categorie Tracciate su Wallet" if lang == "it" else "Top Tracked Categories in Wallet",
                )
                fig_w_pie.update_traces(textposition="inside", textinfo="percent+label")
                fig_w_pie.update_layout(margin=dict(t=40, b=10, l=10, r=10))
                st.plotly_chart(fig_w_pie, use_container_width=True)
        with col_wg2:
            df_pay_meth = pd.DataFrame([
                {"Metodo": "Contanti (CASH)" if lang == "it" else "Cash (CASH)", "Importo": w_sum.get("cash_expenses", 0.0)},
                {"Metodo": "Bonifico / Carta" if lang == "it" else "Transfer / Card", "Importo": w_sum.get("electronic_expenses", 0.0)},
            ])
            fig_pm = px.bar(
                df_pay_meth,
                x="Metodo",
                y="Importo",
                color="Metodo",
                color_discrete_map={
                    "Contanti (CASH)": "#10b981", "Cash (CASH)": "#10b981",
                    "Bonifico / Carta": "#38bdf8", "Transfer / Card": "#38bdf8"
                },
                text_auto=".2f",
                title="Ripartizione Metodo di Pagamento Wallet" if lang == "it" else "Wallet Payment Method Split",
            )
            fig_pm.update_layout(margin=dict(t=40, b=10, l=10, r=10), showlegend=False)
            st.plotly_chart(fig_pm, use_container_width=True)

        st.markdown("---")

    # 1. Grafico Cash Flow Mensile: Entrate vs Uscite e Risparmio Netto
    m_flow = active_stats.get("monthly_cashflow", pd.DataFrame())
    if not m_flow.empty:
        fig_cf = go.Figure()
        periods = [str(p) for p in m_flow.index]
        fig_cf.add_trace(go.Bar(
            x=periods, y=m_flow["entrate"],
            name="Entrate" if lang == "it" else "Inflows",
            marker_color="#10b981"
        ))
        fig_cf.add_trace(go.Bar(
            x=periods, y=m_flow["uscite"],
            name="Uscite" if lang == "it" else "Outflows",
            marker_color="#ef4444"
        ))
        fig_cf.add_trace(go.Scatter(
            x=periods, y=m_flow["netto"],
            name="Risparmio Netto" if lang == "it" else "Net Savings",
            mode="lines+markers",
            line=dict(color="#38bdf8", width=3)
        ))
        fig_cf.update_layout(
            barmode="group",
            title=t("cashflow_trend", lang),
            yaxis_title="Euro (€)",
            hovermode="x unified",
            margin=dict(t=40, b=10, l=10, r=10),
        )
        st.plotly_chart(fig_cf, use_container_width=True)
    else:
        st.info("Nessun dato temporale sufficiente per il grafico di cashflow." if lang == "it" else "Not enough historical data for cashflow chart.")

    st.markdown("---")

    col_ch1, col_ch2 = st.columns(2)

    with col_ch1:
        # Donut Chart Categorie di Spesa
        cat_df = active_stats.get("category_summary", pd.DataFrame())
        if not cat_df.empty:
            df_cat_plot = cat_df.copy()
            df_cat_plot["cat_label"] = df_cat_plot["category"].apply(lambda c: get_category_translation(c, lang))
            fig_cat_pie = px.pie(
                df_cat_plot,
                names="cat_label",
                values="totale_uscito",
                hole=0.40,
                title=t("spending_by_category", lang),
            )
            fig_cat_pie.update_traces(textposition="inside", textinfo="percent+label")
            fig_cat_pie.update_layout(margin=dict(t=40, b=10, l=10, r=10))
            st.plotly_chart(fig_cat_pie, use_container_width=True)
        else:
            st.info("Nessuna categoria di spesa rilevata." if lang == "it" else "No spending categories detected.")

    with col_ch2:
        # Top 10 Payees / Destinatari
        top_p = active_stats.get("top_payees", pd.DataFrame())
        st.markdown(f"#### 🏷️ {t('top_payees', lang)}")
        if not top_p.empty:
            top_p_view = top_p.copy()
            if lang == "en":
                top_p_view.columns = ["Merchant / Payee", "Total Spent", "Transactions"]
            else:
                top_p_view.columns = ["Beneficiario / Negozio", "Totale Speso", "Transazioni"]

            amt_col_name = "Totale Speso" if lang == "it" else "Total Spent"
            st.dataframe(
                top_p_view,
                column_config={amt_col_name: st.column_config.NumberColumn(format="€ %.2f")},
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("Nessun beneficiario individuato." if lang == "it" else "No counterparties detected.")

    # Spese Fisse & Ricorrenti Rilevate
    st.markdown("---")
    st.markdown(f"### 🔄 {t('detected_recurring', lang)}")
    st.caption(t("recurring_explanation", lang))
    df_rec_detected = bdm.detect_recurring_from_statements(df_tx_categorized)
    if not df_rec_detected.empty:
        df_rec_view = df_rec_detected.copy()
        if lang == "it":
            df_rec_view.columns = ["Voce / Categoria", "Costo Minimo (€)", "Costo Massimo (€)", "Probabilità", "Inflazione"]
        else:
            df_rec_view.columns = ["Expense Item", "Min Cost (€)", "Max Cost (€)", "Probability", "Inflation Model"]
        st.dataframe(df_rec_view, use_container_width=True, hide_index=True)
    else:
        st.info("Nessuna spesa ricorrente isolata dai movimenti." if lang == "it" else "No recurring expenses detected yet.")


# ------------------------------------------------------------
# TAB 3: ESTRATTI CONTO & TRANSAZIONI (STATEMENTS & TRANSACTIONS)
# ------------------------------------------------------------
with tab_statements:
    st.subheader(t("tab_transactions", lang))

    with st.expander("📤 " + ("Carica Estratti Conto (PDF, CSV, Excel)" if lang == "it" else "Upload Bank Statements (PDF, CSV, Excel)"), expanded=(len(statements) == 0)):
        tab_files = st.file_uploader(
            t("upload_drag_drop", lang),
            accept_multiple_files=True,
            type=["csv", "tsv", "xlsx", "xls", "pdf"],
            key="bank_file_uploader_tab3",
            help=t("upload_help", lang)
        )
        if tab_files and save_uploaded_statements(tab_files):
            st.cache_data.clear()
            st.toast(f"✅ {t('upload_success', lang)}")
            st.rerun()

        if st.session_state.last_uploaded_files:
            if st.button("↩️ " + t("undo_upload", lang), use_container_width=True, key="btn_undo_upload_tab3"):
                undo_last_upload()

    if not df_tx_categorized.empty:
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            institutions = [("Tutti" if lang == "it" else "All")] + sorted(list(df_tx_categorized["institution"].unique()))
            sel_inst = st.selectbox(t("filter_account", lang) + ":", institutions)
        with col_f2:
            raw_cats = sorted(list(df_tx_categorized["category"].unique()))
            categories = [("Tutte" if lang == "it" else "All")] + raw_cats
            sel_cat = st.selectbox(t("filter_category", lang) + ":", categories)
        with col_f3:
            search_query = st.text_input(t("filter_search", lang) + ":", "")

        df_filtered = df_tx_categorized.copy()
        if sel_inst not in ["Tutti", "All"]:
            df_filtered = df_filtered[df_filtered["institution"] == sel_inst]
        if sel_cat not in ["Tutte", "All"]:
            df_filtered = df_filtered[df_filtered["category"] == sel_cat]
        if search_query:
            df_filtered = df_filtered[df_filtered["description"].astype(str).str.contains(search_query, case=False, na=False)]

        st.caption(f"{'Trovate' if lang == 'it' else 'Found'} **{len(df_filtered)}** {'transazioni.' if lang == 'it' else 'transactions.'}")

        df_display = df_filtered.copy()
        df_display["date"] = pd.to_datetime(df_display["date"]).dt.strftime("%d/%m/%Y")
        cols_to_show = ["date", "institution", "account_id", "category", "amount", "description"]
        if "balance_after" in df_display.columns:
            cols_to_show.append("balance_after")
        df_display = df_display[cols_to_show]

        if lang == "it":
            df_display.columns = ["Data", "Istituto", "Conto", "Categoria", "Importo (€)", "Causale"] + (["Saldo (€)"] if "balance_after" in cols_to_show else [])
            amt_col = "Importo (€)"
            bal_col = "Saldo (€)"
        else:
            df_display.columns = ["Date", "Institution", "Account", "Category", "Amount (€)", "Description"] + (["Balance (€)"] if "balance_after" in cols_to_show else [])
            amt_col = "Amount (€)"
            bal_col = "Balance (€)"

        st.dataframe(
            df_display,
            column_config={
                amt_col: st.column_config.NumberColumn(format="€ %.2f"),
                bal_col: st.column_config.NumberColumn(format="€ %.2f") if "balance_after" in cols_to_show else None,
            },
            use_container_width=True,
            hide_index=True,
        )

        # ------------------------------------------------------------
        # SEZIONE MODIFICA MANUALE TRANSAZIONI & AGGIUNTA MOVIMENTI
        # ------------------------------------------------------------
        std_cats = [
            "Spesa & Alimentari", "Ristoranti & Svago", "Affitto", "Bollette & Utenze",
            "Trasporti & Viaggi", "Investimenti & PAC", "Investimento ETF / Azioni",
            "Salute & Farmacia", "Abbonamenti & IT", "Palestra & Sport",
            "Svago & Scommesse", "Stipendio & Compensi", "Interessi & Rendite",
            "Giroconto", "Altre Spese", "Entrate Varie"
        ]

        col_t_btn1, col_t_btn2 = st.columns(2)
        with col_t_btn1:
            with st.expander("➕ " + t("manual_tx_title", lang), expanded=False):
                with st.form("form_add_manual_tx", clear_on_submit=True):
                    man_date = st.date_input("Data" if lang == "it" else "Date", value=pd.Timestamp.now())
                    acc_opts = [s.account_id for s in statements] if statements else ["Manuale"]
                    man_acc = st.selectbox("Conto" if lang == "it" else "Account", options=acc_opts)
                    man_amt = st.number_input(
                        "Importo (€) [negativo = spesa, positivo = entrata]" if lang == "it" else "Amount (€) [negative = expense, positive = income]",
                        value=-20.0,
                        step=5.0
                    )
                    man_cat = st.selectbox("Categoria" if lang == "it" else "Category", options=std_cats)
                    man_desc = st.text_input("Descrizione / Causale" if lang == "it" else "Description / Payee", value="Movimento Manuale")
                    man_is_tr = st.checkbox("Giroconto / Trasferimento Interno" if lang == "it" else "Internal Transfer", value=(man_cat == "Giroconto"))

                    submit_man_tx = st.form_submit_button("➕ " + t("add_tx_btn", lang), use_container_width=True)
                    if submit_man_tx:
                        push_undo_state()
                        new_entry = {
                            "date": str(man_date),
                            "account_id": man_acc,
                            "institution": man_acc.split("_")[0],
                            "amount": float(man_amt),
                            "currency": "EUR",
                            "description": str(man_desc),
                            "counterparty": str(man_desc),
                            "category": man_cat,
                            "is_internal_transfer": man_is_tr,
                            "balance_after": None,
                        }
                        st.session_state.user_overrides["manual_transactions"].append(new_entry)
                        bdm.save_user_overrides(st.session_state.user_overrides)
                        st.cache_data.clear()
                        st.toast(f"✅ {t('tx_added_success', lang)}")
                        st.rerun()

        with col_t_btn2:
            with st.expander("✏️ " + t("edit_tx_title", lang), expanded=False):
                st.caption(t("edit_tx_help", lang))

                if not df_filtered.empty:
                    tx_choices = df_filtered.apply(
                        lambda r: f"[{pd.to_datetime(r['date']).strftime('%d/%m/%Y')}] €{r['amount']:+,.2f} — {str(r['description'])[:35]} ({r['category']})",
                        axis=1
                    ).tolist()
                    tx_keys = df_filtered["tx_key"].tolist() if "tx_key" in df_filtered.columns else [
                        bdm.make_tx_key(r["date"], r.get("account_id", ""), r["amount"], r["description"])
                        for _, r in df_filtered.iterrows()
                    ]

                    sel_tx_idx = st.selectbox(
                        "Seleziona Transazione da Modificare:" if lang == "it" else "Select Transaction to Edit:",
                        options=range(len(tx_choices)),
                        format_func=lambda i: tx_choices[i],
                        key="sb_select_tx_to_edit"
                    )

                    chosen_key = tx_keys[sel_tx_idx]
                    chosen_row = df_filtered.iloc[sel_tx_idx]

                    curr_cat = chosen_row.get("category", "Altre Spese")
                    cat_idx = std_cats.index(curr_cat) if curr_cat in std_cats else 0
                    new_cat = st.selectbox(
                        "Nuova Categoria:" if lang == "it" else "New Category:",
                        options=std_cats,
                        index=cat_idx,
                        key="sb_edit_cat_choice"
                    )

                    new_is_tr = st.checkbox(
                        "Giroconto Interno" if lang == "it" else "Internal Transfer",
                        value=bool(chosen_row.get("is_internal_transfer", False)),
                        key="cb_edit_is_tr"
                    )
                    exclude_tx = st.checkbox(
                        "Escludi Transazione" if lang == "it" else "Exclude Transaction",
                        value=(chosen_key in st.session_state.user_overrides.get("excluded_transactions", [])),
                        key="cb_edit_exclude"
                    )

                    col_save_t1, col_save_t2 = st.columns(2)
                    with col_save_t1:
                        if st.button("💾 " + t("save_tx_changes", lang), use_container_width=True, key="btn_save_tx_edit"):
                            push_undo_state()
                            if exclude_tx:
                                if chosen_key not in st.session_state.user_overrides["excluded_transactions"]:
                                    st.session_state.user_overrides["excluded_transactions"].append(chosen_key)
                            else:
                                if chosen_key in st.session_state.user_overrides["excluded_transactions"]:
                                    st.session_state.user_overrides["excluded_transactions"].remove(chosen_key)
                                st.session_state.user_overrides["category_overrides"][chosen_key] = new_cat
                                st.session_state.user_overrides["transfer_flags"][chosen_key] = new_is_tr

                            bdm.save_user_overrides(st.session_state.user_overrides)
                            st.cache_data.clear()
                            st.toast(f"✅ {t('tx_saved_success', lang)}")
                            st.rerun()

                    with col_save_t2:
                        if st.session_state.undo_stack and st.button("↩️ Undo", use_container_width=True, key="btn_undo_tx_edit"):
                            pop_undo_state()

        # Tabella Giroconti Interni Riconciliati
        if not summary.internal_transfers.empty:
            st.markdown("---")
            st.markdown(f"### 🔄 {t('internal_transfers_table', lang)}")
            st.caption(t("internal_transfers_desc", lang))
            df_tr_view = summary.internal_transfers.copy()
            df_tr_view["date"] = pd.to_datetime(df_tr_view["date"]).dt.strftime("%d/%m/%Y")
            if lang == "it":
                df_tr_view.columns = ["Data", "Conto Origine", "Conto Destinazione", "Importo (€)", "Causale Uscita", "Causale Entrata"]
            else:
                df_tr_view.columns = ["Date", "From Account", "To Account", "Amount (€)", "Outflow Memo", "Inflow Memo"]
            st.dataframe(
                df_tr_view,
                column_config={("Importo (€)" if lang == "it" else "Amount (€)"): st.column_config.NumberColumn(format="€ %.2f")},
                use_container_width=True,
                hide_index=True,
            )
    else:
        st.info(t("no_statements_found", lang))


# ------------------------------------------------------------
# TAB 4: PREVISIONI FUTURE (MONTE CARLO FORECASTING)
# ------------------------------------------------------------
with tab_sim:
    st.subheader(t("forecast_title", lang))
    st.markdown(t("forecast_subtitle", lang))

    # Parametri configurabili alimentati empiricamente dai dati degli estratti conto
    with st.expander(f"⚙️ {t('sim_parameters', lang)}", expanded=True):
        col_p1, col_p2, col_p3 = st.columns(3)

        with col_p1:
            horizon_sel = st.selectbox(
                t("horizon_months", lang) + ":",
                options=[12, 24, 36, 48, 60, 120],
                index=2,  # Default 36 mesi (3 anni)
                format_func=lambda m: f"{m} {'mesi' if lang == 'it' else 'months'} ({m//12} {'anni' if lang == 'it' else 'years'})"
            )
            sim_paths = st.slider(
                t("num_simulations", lang) + ":",
                min_value=1000,
                max_value=10000,
                value=5000,
                step=1000
            )
            starting_cash_val = st.number_input(
                t("starting_cash", lang) + ":",
                value=float(summary.recommended_starting_cash if summary.recommended_starting_cash > 0 else 3000.0),
                step=500.0
            )

        with col_p2:
            default_income = float(bank_stats.get("detected_salary", 2000.0))
            user_income = st.number_input(
                t("expected_monthly_income", lang) + ":",
                value=default_income if default_income > 0 else 2000.0,
                step=100.0
            )
            default_burn = float(bank_stats.get("monthly_expenses_mean", 1300.0))
            user_burn = st.number_input(
                t("monthly_burn_rate", lang) + ":",
                value=default_burn if default_burn > 0 else 1300.0,
                step=50.0
            )
            default_vol = float(bank_stats.get("monthly_expenses_std", 200.0))
            user_vol = st.number_input(
                t("spending_volatility", lang) + ":",
                value=default_vol if default_vol > 0 else 200.0,
                step=25.0
            )

        with col_p3:
            starting_inv_val = st.number_input(
                t("starting_investments", lang) + ":",
                value=float(summary.total_investments if summary.total_investments > 0 else 1000.0),
                step=250.0
            )
            user_pac = st.number_input(
                t("monthly_pac", lang) + ":",
                value=100.0,
                step=25.0
            )
            user_mkt_return = st.slider(
                t("annual_market_return", lang) + ":",
                min_value=0.0,
                max_value=15.0,
                value=6.0,
                step=0.5
            ) / 100.0
            user_inflation = st.slider(
                t("annual_inflation", lang) + ":",
                min_value=0.0,
                max_value=8.0,
                value=2.5,
                step=0.5
            ) / 100.0

    # Esecuzione simulazione Monte Carlo generalizzata
    current_cash_rate = float(st.session_state.get("custom_cash_rate", 2.5)) / 100.0
    sim_res = se.run_simulation(
        start="2026-10-01",
        horizon_months=horizon_sel,
        n_sims=sim_paths,
        seed=42,
        pac=user_pac,
        strategy="dynamic",
        cash_threshold=5000.0,
        monthly_income=user_income,
        starting_cash=starting_cash_val,
        starting_inv=starting_inv_val,
        cash_rate=current_cash_rate,
        mkt_mean=user_mkt_return,
        infl_mean=user_inflation,
        monthly_expenses_mean=user_burn,
        monthly_expenses_std=user_vol,
        tax_rate=0.26,
    )

    # Indicatori Risultati
    st.markdown(f"### 📈 {t('projection_results', lang)}")
    col_r1, col_r2, col_r3, col_r4, col_r5 = st.columns(5)
    with col_r1:
        st.metric(t("pessimistic_p5", lang), f"€ {sim_res['p5']:,.0f}")
    with col_r2:
        st.metric(t("median_p50", lang), f"€ {sim_res['p50']:,.0f}")
    with col_r3:
        st.metric(t("optimistic_p95", lang), f"€ {sim_res['p95']:,.0f}")
    with col_r4:
        st.metric(t("ruin_probability", lang), f"{sim_res['prob_ruin']:.1f}%")
    with col_r5:
        st.metric(t("real_vs_nominal", lang), f"€ {sim_res['p50_real']:,.0f}")

    # Fan Chart Patrimonio Netto
    months_axis = [d.strftime("%b %Y") for d in sim_res["dates"]]
    total_wealth_history = sim_res["cash_history"] + sim_res["invest_history"]

    p05 = np.percentile(total_wealth_history, 5, axis=0)
    p25 = np.percentile(total_wealth_history, 25, axis=0)
    p50 = np.percentile(total_wealth_history, 50, axis=0)
    p75 = np.percentile(total_wealth_history, 75, axis=0)
    p95 = np.percentile(total_wealth_history, 95, axis=0)

    fig_fan = go.Figure()
    fig_fan.add_trace(go.Scatter(x=months_axis, y=p95, mode="lines", line=dict(width=0), showlegend=False))
    fig_fan.add_trace(go.Scatter(
        x=months_axis, y=p05, mode="lines", line=dict(width=0), fill="tonexty",
        fillcolor="rgba(56, 189, 248, 0.15)", name="90% Confidence Interval (P5-P95)"
    ))
    fig_fan.add_trace(go.Scatter(x=months_axis, y=p75, mode="lines", line=dict(width=0), showlegend=False))
    fig_fan.add_trace(go.Scatter(
        x=months_axis, y=p25, mode="lines", line=dict(width=0), fill="tonexty",
        fillcolor="rgba(56, 189, 248, 0.35)", name="50% Confidence Interval (P25-P75)"
    ))
    fig_fan.add_trace(go.Scatter(
        x=months_axis, y=p50, mode="lines+markers", line=dict(color="#38bdf8", width=3), name="Median Total Wealth"
    ))

    fig_fan.update_layout(
        title=f"{t('fan_chart_title', lang)} ({horizon_sel} {'mesi' if lang == 'it' else 'months'})",
        xaxis_title="Timeline",
        yaxis_title="Net Worth (€)",
        hovermode="x unified",
        margin=dict(t=40, b=10, l=10, r=10),
    )
    st.plotly_chart(fig_fan, use_container_width=True)

    # Traiettoria Liquidità vs Portafoglio ETF
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        cash_med = np.median(sim_res["cash_history"], axis=0)
        fig_c = go.Figure()
        fig_c.add_trace(go.Scatter(x=months_axis, y=cash_med, mode="lines", line=dict(color="#10b981", width=2), name="Cash"))
        fig_c.update_layout(title="Traiettoria Cassa Liquida" if lang == "it" else "Liquid Cash Trajectory", yaxis_title="€", margin=dict(t=40, b=10, l=10, r=10))
        st.plotly_chart(fig_c, use_container_width=True)

    with col_t2:
        inv_med = np.median(sim_res["invest_history"], axis=0)
        fig_i = go.Figure()
        fig_i.add_trace(go.Scatter(x=months_axis, y=inv_med, mode="lines", line=dict(color="#f59e0b", width=2), name="Investments"))
        fig_i.update_layout(title="Crescita Portafoglio Investito" if lang == "it" else "Invested Portfolio Growth", yaxis_title="€", margin=dict(t=40, b=10, l=10, r=10))
        st.plotly_chart(fig_i, use_container_width=True)


# ------------------------------------------------------------
# TAB 5: ASSISTENTE AI LOCALE (LOCAL AI ASSISTANT)
# ------------------------------------------------------------
with tab_ai:
    st.subheader(t("ai_title", lang))
    st.markdown(t("ai_subtitle", lang))

    # Box Gestione Modelli
    with st.expander(f"⚙️ {t('install_model', lang)}", expanded=(not llm_status.is_available or not llm_status.available_models)):
        col_m1, col_m2 = st.columns([1, 1])
        with col_m1:
            st.markdown("#### 📦 " + ("Modelli Installati" if lang == "it" else "Installed Models"))
            detailed_models = client.get_detailed_models()
            if detailed_models:
                df_models = pd.DataFrame(detailed_models)
                df_models.columns = ["Name", "Size (GB)", "Digest", "Modified"] if lang == "en" else ["Nome Modello", "Dimensione (GB)", "Digest", "Ultima Modifica"]
                st.dataframe(df_models, use_container_width=True, hide_index=True)
            else:
                st.info("Nessun modello Ollama disponibile." if lang == "it" else "No models downloaded yet in Ollama.")

        with col_m2:
            st.markdown("#### 📥 " + ("Installa Nuovo Modello" if lang == "it" else "Download & Install Model"))
            rec_options = [f"{m['display_name']} [{m['tag']}]" for m in RECOMMENDED_MODELS] + [("Altro personalizzato..." if lang == "it" else "Custom model...")]
            sel_rec = st.selectbox("Catalogo / Catalog:", rec_options, key="select_rec_model_ai")

            chosen_tag = ""
            if "Altro" in sel_rec or "Custom" in sel_rec:
                chosen_tag = st.text_input("Tag Ollama (e.g. 'llama3.2:3b', 'qwen2.5:3b'):", value="llama3.2:3b")
            else:
                for m in RECOMMENDED_MODELS:
                    if m["tag"] in sel_rec:
                        chosen_tag = m["tag"]
                        st.caption(f"ℹ️ {m['description']} ({m['size_est']})")
                        break

            installed_names = [m.get("name") for m in detailed_models]
            is_already_installed = chosen_tag in installed_names or any(chosen_tag in name for name in installed_names)

            if is_already_installed:
                st.success(f"✅ {chosen_tag} " + ("è già installato!" if lang == "it" else "is already installed!"))
            else:
                if st.button(f"📥 {t('install_model', lang)} '{chosen_tag}'", use_container_width=True, type="primary"):
                    if not llm_status.is_available:
                        st.error("Avvia Ollama prima di procedere." if lang == "it" else "Start Ollama daemon first.")
                    else:
                        handle_model_pull(client, chosen_tag)
                        st.rerun()

    # Chat Interattiva
    st.markdown("---")
    curr_model_name = client.preferred_model or llm_status.model_name
    badge = f"<span class='status-badge badge-green'>Active: {curr_model_name}</span>" if llm_status.is_available else "<span class='status-badge badge-amber'>Deterministic Offline Engine</span>"
    st.markdown(f"**{t('model_selection', lang)}:** {badge}", unsafe_allow_html=True)

    # Pulsanti di Analisi Rapida (bilingue)
    col_q1, col_q2, col_q3, col_q4 = st.columns(4)
    quick_query = None
    with col_q1:
        if st.button("📋 " + ("Audit Patrimonio" if lang == "it" else "Portfolio Audit"), use_container_width=True):
            quick_query = "Esegui un audit del mio patrimonio e valuta liquidità e investimenti." if lang == "it" else "Perform an audit of my net worth, liquidity buffer, and investments."
    with col_q2:
        if st.button("🔍 " + ("Analisi Spese & Flussi" if lang == "it" else "Spending & Cashflows"), use_container_width=True):
            quick_query = "Quali sono le mie categorie di spesa principali ed eventuali flussi o spese anomale?" if lang == "it" else "What are my main spending categories and any detected expense anomalies?"
    with col_q3:
        if st.button("📈 " + ("Tasso BCE & Depositi" if lang == "it" else "ECB Rate & Yield"), use_container_width=True):
            quick_query = "Spiegami quanto rende la mia liquidità remunerata con il tasso BCE attuale e come ottimizzarla." if lang == "it" else "Explain my high-yield cash return based on current ECB rate and how to optimize it."
    with col_q4:
        if st.button("💡 " + ("Consigli PAC & ETF" if lang == "it" else "Savings & ETF Advice"), use_container_width=True):
            quick_query = "Posso aumentare il mio investimento mensile in base al mio tasso di risparmio e buffer attuale?" if lang == "it" else "Can I increase my monthly investment plan based on my current savings rate and cash buffer?"

    # Visualizzazione Cronologia Chat
    if not st.session_state.chat_history:
        with st.chat_message("assistant"):
            wallet_extra_it = ""
            wallet_extra_en = ""
            if summary.has_wallet_tracker and summary.wallet_summary:
                w_tot = summary.wallet_summary.get("total_expenses", 0.0)
                w_cash = summary.wallet_summary.get("cash_expenses", 0.0)
                wallet_extra_it = f"\n\n📱 *Ho integrato anche la tua app **Wallet**: hai registrato **€ {w_tot:,.2f}** di spese, di cui **€ {w_cash:,.2f}** pagati in contanti (CASH)!*"
                wallet_extra_en = f"\n\n📱 *I also integrated your **Wallet** app: you logged **€ {w_tot:,.2f}** in expenses, with **€ {w_cash:,.2f}** paid in CASH!*"

            st.markdown(
                ("👋 **Ciao! Sono LORIS, il tuo analista finanziario personale offline e riservato al 100%.**\n\n"
                 f"Ho analizzato i tuoi estratti conto: il tuo patrimonio netto attuale è di **€ {summary.total_net_worth:,.2f}** "
                 f"(di cui **€ {summary.total_high_yield_cash:,.2f}** su Trade Republic / liquidità remunerata con rendimento stimato di **€ {summary.total_high_yield_cash * float(st.session_state.get('custom_cash_rate', 2.5))/100:,.2f}/anno**)."
                 f"{wallet_extra_it}\n\n"
                 "Cosa vorresti approfondire oggi? Puoi chiedermi un'analisi delle tue spese, consigli sulla riserva di emergenza o strategie per i tuoi investimenti.")
                if lang == "it" else
                ("👋 **Hello! I am LORIS, your 100% offline and confidential financial assistant.**\n\n"
                 f"I reviewed your statements: your current net worth is **€ {summary.total_net_worth:,.2f}** "
                 f"(including **€ {summary.total_high_yield_cash:,.2f}** in high-yield cash at ECB deposit rate)."
                 f"{wallet_extra_en}\n\n"
                 "What would you like to explore today? Ask me about your spending breakdown, cash buffer, or investment plans.")
            )

    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Chat Input
    user_input = st.chat_input(t("chat_placeholder", lang))
    prompt_to_execute = quick_query or user_input

    if prompt_to_execute:
        st.session_state.chat_history.append({"role": "user", "content": prompt_to_execute})
        with st.chat_message("user"):
            st.markdown(prompt_to_execute)

        with st.chat_message("assistant"):
            scrubber = PIIScrubber()
            anon_df = scrubber.anonymize_dataframe(df_tx_categorized.head(30), ["description"]) if not df_tx_categorized.empty else pd.DataFrame()
            cash_yield_val = float(st.session_state.get("custom_cash_rate", 2.5))

            with st.spinner("LORIS analyzing locally..."):
                stream_res = client.chat_with_llm(
                    messages=st.session_state.chat_history,
                    portfolio_summary=summary,
                    anonymized_transactions=anon_df,
                    cash_yield_pct=cash_yield_val,
                    stream=True,
                )

                if hasattr(stream_res, "__iter__") and not isinstance(stream_res, (str, bytes, dict, list)):
                    final_text = st.write_stream(stream_res)
                else:
                    final_text = str(stream_res)
                    st.markdown(final_text)

                st.session_state.chat_history.append({"role": "assistant", "content": final_text})

    if st.session_state.chat_history:
        if st.button("🗑️ " + ("Cancella Cronologia" if lang == "it" else "Clear Chat History")):
            st.session_state.chat_history = []
            st.rerun()


# ------------------------------------------------------------
# TAB 6: IMPOSTAZIONI & PRIVACY (SETTINGS & PRIVACY)
# ------------------------------------------------------------
with tab_settings:
    st.subheader(t("settings_title", lang))

    # Lingua
    st.markdown(f"### 🌐 {t('language', lang)}")
    sel_lang_settings = st.radio(
        t("language", lang) + ":",
        options=list(AVAILABLE_LANGUAGES.keys()),
        format_func=lambda code: AVAILABLE_LANGUAGES.get(code, code),
        index=0 if lang == "it" else 1,
        horizontal=True
    )
    if sel_lang_settings != lang:
        st.session_state.lang = sel_lang_settings
        st.rerun()

    st.markdown("---")

    # Scudo Privacy PII
    st.markdown(f"### 🛡️ {t('privacy_shield', lang)}")
    st.caption(t("privacy_desc", lang))
    scrubber = PIIScrubber()
    sample_text = ("Bonifico a Mario Rossi IBAN AT123456789012345678 per affitto. Carta 5167 1234 5678 9010; CF: RSSMRA85M01H501Z."
                   if lang == "it" else
                   "Transfer to John Doe IBAN GB29XDEF80200112345678 for rent. Card 4111 2222 3333 4444; SSN 123-45-6789.")
    test_text = st.text_area(
        "Verifica live del filtro PII:" if lang == "it" else "Live PII filter test:",
        value=sample_text,
        height=80,
    )
    if test_text:
        anon_txt = scrubber.anonymize_text(test_text)
        is_clean, leaks = scrubber.audit_cleanliness(anon_txt)
        col_pv1, col_pv2 = st.columns(2)
        with col_pv1:
            st.markdown("**" + ("Testo Anonimizzato:" if lang == "it" else "Anonymized Output:") + "**")
            st.code(anon_txt, language="text")
        with col_pv2:
            st.markdown("**Audit:**")
            if is_clean:
                st.success("✅ " + ("100% Pulito: Nessun dato sensibile rilevato" if lang == "it" else "100% Clean: No sensitive data detected"))
            else:
                st.error(f"⚠️ Leaks: {leaks}")

    st.markdown("---")

    # Placeholder Google Sheets (opzionale)
    st.markdown(f"### 📊 {t('optional_google_sheet', lang)}")
    st.caption(t("google_sheet_help", lang))
    gs_url = st.text_input(
        "Google Sheet URL:",
        value="",
        placeholder="https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit?usp=sharing"
    )
    if st.button("🔗 " + ("Salva Placeholder" if lang == "it" else "Save Placeholder"), key="btn_save_gs"):
        if gs_url.strip():
            st.success("Placeholder configurato con successo!" if lang == "it" else "Placeholder configured successfully!")
        else:
            st.info("Campo lasciato vuoto. LORIS opera al 100% da estratti conto locali." if lang == "it" else "Field left empty. LORIS operates 100% from local bank statements.")
