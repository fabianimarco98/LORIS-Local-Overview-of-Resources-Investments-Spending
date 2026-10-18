# ============================================================
# NET WORTH TAB — storico del patrimonio (UI Streamlit)
# ============================================================
"""
Tab "Patrimonio nel tempo": voci (conti, broker, contanti...), aggiornamento periodico
dei valori e grafico/variazioni. La logica sta in banking.net_worth e loris_service;
qui solo widget. Funziona anche senza estratti conto.
"""

from datetime import date
from typing import Any, Dict, List

import plotly.graph_objects as go
import streamlit as st

import loris_service as svc
from banking import net_worth as nw
from banking.portfolio import ASSET_CLASS_COLORS, ASSET_CLASS_LABELS, get_asset_class_label
from i18n import t


def _statement_accounts(summary: Any) -> List[str]:
    acc = getattr(summary, "accounts_summary", None)
    if acc is None or acc.empty:
        return []
    if "is_tracker" in acc.columns:
        acc = acc[~acc["is_tracker"]]
    return [str(a) for a in acc["account_id"].tolist()]


def _render_due_banner(store: nw.NetWorthStore, lang: str) -> None:
    days = nw.days_since_last(store)
    if days is None:
        st.info(t("nw_due_never", lang))
    elif nw.is_update_due(store):
        st.warning(t("nw_due_days", lang, days=days))


def _render_holdings(store: nw.NetWorthStore, summary: Any, lang: str) -> nw.NetWorthStore:
    st.markdown(f"#### {t('nw_holdings', lang)}")
    active = [h for h in store.holdings if not h.archived]
    if not active:
        st.caption(t("nw_no_holdings", lang))
    for h in active:
        c1, c2 = st.columns([5, 1])
        c1.write(f"**{h.name}** · {get_asset_class_label(h.asset_class, lang)}")
        if c2.button(t("nw_archive", lang), key=f"nw_arch_{h.id}"):
            nw.archive_holding(store, h.id)
            nw.save(store)
            st.rerun()

    none_label = t("nw_holding_link_none", lang)
    with st.expander(t("nw_add_holding", lang), expanded=not active):
        with st.form("nw_add_holding_form", clear_on_submit=True):
            name = st.text_input(t("nw_holding_name", lang))
            asset_class = st.selectbox(
                t("nw_holding_class", lang), list(ASSET_CLASS_LABELS),
                format_func=lambda k: get_asset_class_label(k, lang),
            )
            link = st.selectbox(t("nw_holding_link", lang), [none_label] + _statement_accounts(summary))
            if st.form_submit_button(t("nw_add_holding", lang)):
                try:
                    nw.add_holding(store, nw.unique_holding_id(store, name), name, asset_class,
                                   linked_account_id=None if link == none_label else link)
                    nw.save(store)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    return store


def _render_update_form(store: nw.NetWorthStore, summary: Any, lang: str) -> bool:
    """Form del nuovo aggiornamento. Restituisce True se è stato salvato."""
    active = [h for h in store.holdings if not h.archived]
    if not active:
        return False
    st.markdown(f"#### {t('nw_new_update', lang)}")
    st.caption(t("nw_prefill_hint", lang))
    last_values: Dict[str, float] = store.snapshots[-1].values if store.snapshots else {}
    from_statements = nw.prefill_from_portfolio(store, summary)
    with st.form("nw_update_form"):
        snap_date = st.date_input(t("nw_date", lang), value=date.today())
        values: Dict[str, float] = {}
        for h in active:
            default = from_statements.get(h.id, last_values.get(h.id, 0.0))
            values[h.id] = st.number_input(
                t("nw_value_for", lang, name=h.name), value=float(default), step=100.0, format="%.2f",
                key=f"nw_val_{h.id}",
            )
        note = st.text_input(t("nw_note", lang))
        if st.form_submit_button(t("nw_save", lang)):
            try:
                svc.record_snapshot(snap_date, values, note)
                st.success(t("nw_saved", lang))
                return True
            except ValueError as exc:
                st.error(str(exc))
    return False


def _render_history(store: nw.NetWorthStore, lang: str) -> None:
    pivot = nw.totals_by_class(store)
    if pivot.empty:
        st.caption(t("nw_no_snapshots", lang))
        return
    st.markdown(f"#### {t('nw_chart_title', lang)}")
    fig = go.Figure()
    for ac in [c for c in pivot.columns if c != "total"]:
        fig.add_trace(go.Scatter(
            x=list(pivot.index), y=pivot[ac], name=get_asset_class_label(ac, lang),
            stackgroup="one", mode="lines+markers", line=dict(color=ASSET_CLASS_COLORS.get(ac)),
        ))
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), yaxis_title="€",
                      legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown(f"#### {t('nw_changes_title', lang)}")
    d = nw.deltas(store).iloc[::-1]
    st.dataframe(
        d.rename(columns={"date": t("nw_col_date", lang), "total": t("nw_col_total", lang),
                          "delta": t("nw_col_delta", lang), "delta_pct": t("nw_col_delta_pct", lang)}),
        hide_index=True, use_container_width=True,
        column_config={
            t("nw_col_total", lang): st.column_config.NumberColumn(format="%.2f"),
            t("nw_col_delta", lang): st.column_config.NumberColumn(format="%+.2f"),
            t("nw_col_delta_pct", lang): st.column_config.NumberColumn(format="%+.1f%%"),
        },
    )


def render_net_worth_tab(summary: Any, lang: str) -> None:
    st.subheader(t("tab_net_worth", lang))
    st.caption(t("nw_intro", lang))
    try:
        store = nw.load()
    except ValueError as exc:    # file corrotto: mostrarlo, mai sovrascriverlo in silenzio
        st.error(t("nw_file_error", lang, err=exc))
        return
    _render_due_banner(store, lang)
    store = _render_holdings(store, summary, lang)
    if _render_update_form(store, summary, lang):
        store = nw.load()
    _render_history(store, lang)
