# ============================================================
# ML FORECAST — Modelli predittivi, walk-forward e proiezioni future
# ============================================================
import pandas as pd
import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error

EXTRA_MONTHS = (3, 6, 9, 12)


def build_ml_dataset(monthly_series, extra_months=EXTRA_MONTHS):
    df = pd.DataFrame({"uscite": monthly_series})
    df["lag1"] = df["uscite"].shift(1)
    df["lag2"] = df["uscite"].shift(2)
    df["lag3"] = df["uscite"].shift(3)
    df["roll3"] = df["uscite"].shift(1).rolling(3).mean()
    df["roll6"] = df["uscite"].shift(1).rolling(6).mean()
    df["roll12"] = df["uscite"].shift(1).rolling(12).mean()
    df["mese"] = [p.month for p in df.index]
    df["mese_extra"] = df["mese"].isin(extra_months).astype(int)
    df["mese_sin"] = np.sin(2 * np.pi * df["mese"] / 12)
    df["mese_cos"] = np.cos(2 * np.pi * df["mese"] / 12)
    features = ["lag1", "lag2", "lag3", "roll3", "roll6", "roll12",
                "mese_extra", "mese_sin", "mese_cos"]
    clean_df = df.dropna(subset=features + ["uscite"])
    return clean_df, features


def walk_forward_evaluation(clean_df, features, n_test=24):
    if clean_df.empty or len(clean_df) < 4:
        return pd.DataFrame(), pd.DataFrame(), 0.0

    n_test = min(n_test, len(clean_df) // 3)
    if n_test <= 0:
        return pd.DataFrame(), pd.DataFrame(), 0.0

    train_end_positions = range(len(clean_df) - n_test, len(clean_df))

    pred_gbr, pred_ridge, pred_naive, pred_roll12, actual, test_idx = [], [], [], [], [], []
    residuals_gbr = []

    for t in train_end_positions:
        train = clean_df.iloc[:t]
        test_row = clean_df.iloc[t]
        Xtr, ytr = train[features], train["uscite"]

        # Gradient Boosting
        gbr = GradientBoostingRegressor(n_estimators=150, max_depth=2,
                                        learning_rate=0.05, subsample=0.8, random_state=0)
        gbr.fit(Xtr, ytr)
        p_gbr = float(gbr.predict(test_row[features].to_frame().T)[0])
        pred_gbr.append(p_gbr)
        residuals_gbr.append(float(test_row["uscite"] - p_gbr))

        # Ridge
        ridge = Ridge(alpha=1.0)
        ridge.fit(Xtr, ytr)
        pred_ridge.append(float(ridge.predict(test_row[features].to_frame().T)[0]))

        # Baselines
        pred_naive.append(float(test_row["lag1"]))
        pred_roll12.append(float(test_row["roll12"]))
        actual.append(float(test_row["uscite"]))
        test_idx.append(clean_df.index[t])

    res_df = pd.DataFrame({
        "actual": actual,
        "ML (Gradient Boosting)": pred_gbr,
        "ML (Ridge)": pred_ridge,
        "Naive (mese scorso)": pred_naive,
        "Media mobile 12m": pred_roll12,
    }, index=[p.to_timestamp() for p in test_idx])

    metrics = []
    for col in ["ML (Gradient Boosting)", "ML (Ridge)", "Naive (mese scorso)", "Media mobile 12m"]:
        mae = mean_absolute_error(res_df["actual"], res_df[col])
        rmse = mean_squared_error(res_df["actual"], res_df[col]) ** 0.5
        mape = (np.abs((res_df["actual"] - res_df[col]) / res_df["actual"])).mean() * 100
        metrics.append({"Modello": col, "MAE": mae, "RMSE": rmse, "MAPE": mape})

    metrics_df = pd.DataFrame(metrics).sort_values("MAE")
    residual_std = float(np.std(residuals_gbr))

    return res_df, metrics_df, residual_std


def forecast_future_expenses(clean_df, features, start_period, periods=39,
                             extra_months=EXTRA_MONTHS, residual_std=None):
    if clean_df.empty or len(clean_df) < 4:
        return pd.DataFrame(), pd.Series(dtype=float), 0.0

    # Allena modello full
    gbr_full = GradientBoostingRegressor(n_estimators=150, max_depth=2,
                                         learning_rate=0.05, subsample=0.8, random_state=0)
    gbr_full.fit(clean_df[features], clean_df["uscite"])

    feature_importances = pd.Series(gbr_full.feature_importances_, index=features).sort_values(ascending=False)

    if residual_std is None:
        preds_tr = gbr_full.predict(clean_df[features])
        residual_std = float(np.std(clean_df["uscite"] - preds_tr))

    future_periods = pd.period_range(start=start_period, periods=periods, freq="M")
    hist_uscite = clean_df["uscite"].copy()

    records = []
    for p in future_periods:
        row = {
            "lag1": float(hist_uscite.iloc[-1]),
            "lag2": float(hist_uscite.iloc[-2]),
            "lag3": float(hist_uscite.iloc[-3]),
            "roll3": float(hist_uscite.iloc[-3:].mean()),
            "roll6": float(hist_uscite.iloc[-6:].mean()),
            "roll12": float(hist_uscite.iloc[-12:].mean()),
            "mese": p.month,
            "mese_extra": int(p.month in extra_months),
            "mese_sin": float(np.sin(2 * np.pi * p.month / 12)),
            "mese_cos": float(np.cos(2 * np.pi * p.month / 12)),
        }
        pred_p50 = float(gbr_full.predict(pd.DataFrame([row])[features])[0])
        # Intervalli di confidenza basati sui residui (approssimazione normale con incertezza crescente)
        step = len(records) + 1
        unc_factor = np.sqrt(1 + 0.05 * step)
        pred_p10 = max(0.0, pred_p50 - 1.645 * residual_std * unc_factor)
        pred_p90 = pred_p50 + 1.645 * residual_std * unc_factor

        records.append({
            "period": p,
            "date": p.to_timestamp(),
            "pred_p50": pred_p50,
            "pred_p10": pred_p10,
            "pred_p90": pred_p90,
        })
        hist_uscite.loc[p] = pred_p50  # la previsione diventa lag

    forecast_df = pd.DataFrame(records).set_index("period")
    return forecast_df, feature_importances, gbr_full


def forecast_category_breakdown(panel, valid_cats, periods=39, start_period="2026-09"):
    future_periods = pd.period_range(start=start_period, periods=periods, freq="M")
    cat_forecasts = {}

    for cat in valid_cats:
        s = panel[cat].copy()
        mean_val = float(s.iloc[-12:].mean())
        # stagionalità mensile
        monthly_pattern = s.groupby(s.index.month).mean()
        overall_mean = s.mean()
        mult = (monthly_pattern / overall_mean) if overall_mean > 0 else 1.0

        preds = []
        for p in future_periods:
            m = p.month
            m_factor = float(mult.get(m, 1.0))
            pred = max(0.0, mean_val * (0.5 + 0.5 * m_factor))
            preds.append(pred)

        cat_forecasts[cat] = preds

    df_cats = pd.DataFrame(cat_forecasts, index=future_periods)
    return df_cats
