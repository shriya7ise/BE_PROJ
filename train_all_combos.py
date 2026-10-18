"""
train_all_combos.py
-----------------------
Trains classification (target_class) and regression (target_reg) models
across combinations of the 4 modalities:
    financials, esg, news, geo (geographical_dataset.csv)

DESIGN DECISIONS (research paper)
---------------------------------
1. Classification (incidence) is run on ALL 11 combos
   (4 singles + 6 pairs + 1 four-way).

2. Regression (severity) is run ONLY on combos that contain
   financial or geo signals (Option 2).
   Pure text modalities (esg, news, esg+news) are classification-only.
   Rationale: continuous penalty size is more plausibly related to
   firm size / financial structure / location than to pure text volume
   or keyword density.

3. target_class and target_reg are two operationalizations of the SAME
   OSHA violation records (see scripts/05_build_osha_targets.py):
       target_class = (n_violations > 0)
       target_reg   = total_current_penalty
   Both are predicted from the same input features after stripping
   n_inspections / n_violations / total_current_penalty (LEAKAGE GUARD).

4. Regression target transform: models are fit on log1p(target_reg)
   and predictions are back-transformed with expm1 before evaluation.
   Reported R² / RMSE / MAE are in dollar terms.

5. Capacity settings are deliberately moderated for n ≈ 289 companies
   to reduce overfitting risk while remaining competitive with the
   literature (gradient-boosted trees + stacking).

Models
------
Classification:
    LogisticRegression, RandomForest, XGBoost,
    Stacking (LogReg + SVC + XGB → LogisticRegression meta-learner)

Regression (only on eligible combos):
    ElasticNet, RandomForest, XGBoost,
    Stacking (ElasticNet + SVR + XGB → Ridge meta-learner)

Usage
-----
    python3 train_all_combos.py \\
        --financials output/financials_dataset.csv \\
        --esg        output/esg_dataset.csv \\
        --news       output/news_dataset.csv \\
        --geo        output/geographical_dataset.csv \\
        --splits     output/company_splits.csv \\
        --outdir     output/model_results \\
        --models-dir models/saved
"""

import argparse
import itertools
import json
import re
import warnings
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import joblib

from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.linear_model import LogisticRegression, ElasticNet, Ridge
from sklearn.ensemble import (
    RandomForestClassifier, RandomForestRegressor,
    StackingClassifier, StackingRegressor,
)
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score, roc_auc_score,
    mean_squared_error, mean_absolute_error, r2_score, confusion_matrix,
)
from sklearn.svm import SVC, SVR
from xgboost import XGBClassifier, XGBRegressor

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Constants & leakage guards
# ---------------------------------------------------------------------------

LEAKY_BASE_NAMES = {"n_inspections", "n_violations", "total_current_penalty"}
TARGET_COLS = {"target_class", "target_reg"}
LEAK_CORR_THRESHOLD = 0.9

GROUP_NAMES = ("singles", "pairs", "fourway")

MODALITY_CONFIG = {
    "financial": {
        "exclude": {"security_name", "long_business_summary"},
        "categorical": {"sector_yf", "industry_yf", "currency"},
        "rename": {},
    },
    "esg": {
        "exclude": set(),
        "categorical": {"data_quality_flag"},
        "rename": {},
    },
    "news": {
        "exclude": set(),
        "categorical": set(),
        "rename": {},
    },
    "geo": {
        "exclude": {"company_name", "matched_address"},
        "categorical": set(),
        "rename": {"ticker": "symbol"},
    },
}


def is_known_leaky_name(col: str) -> bool:
    """Catches n_inspections, n_inspections_x, n_inspections_y, etc."""
    base = re.sub(r"_(x|y)(_\d+)?$", "", col)
    return col in LEAKY_BASE_NAMES or base in LEAKY_BASE_NAMES


def should_run_regression(modalities: list) -> bool:
    """
    Option 2: only run severity regression when the combo contains
    financial or geo signals. Pure text modalities are classification-only.
    """
    return "financial" in modalities or "geo" in modalities


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_modality(name: str, path: str) -> tuple[pd.DataFrame, list, list]:
    """Returns (df with symbol + prefixed feature cols + targets,
    numeric_cols, categorical_cols)"""
    cfg = MODALITY_CONFIG[name]
    df = pd.read_csv(path)

    if cfg["rename"]:
        df = df.rename(columns=cfg["rename"])

    if "symbol" not in df.columns:
        raise SystemExit(
            f"[{name}] '{path}' has no 'symbol' column after rename. "
            f"Columns: {df.columns.tolist()}"
        )
    if "target_class" not in df.columns:
        raise SystemExit(
            f"[{name}] '{path}' has no target_class -- run the clean merge first."
        )

    drop = cfg["exclude"] | TARGET_COLS
    candidate_cols = [c for c in df.columns if c not in drop and c != "symbol"]

    # Explicit leakage drop
    known_leaky = [c for c in candidate_cols if is_known_leaky_name(c)]
    if known_leaky:
        print(f"  [{name}] Dropping known leaky column(s): {known_leaky}")
    feature_cols = [c for c in candidate_cols if c not in known_leaky]

    # Correlation-based leakage drop
    corr_leaky = []
    for c in feature_cols:
        if pd.api.types.is_numeric_dtype(df[c]) and df[c].nunique(dropna=True) > 1:
            r_class = df[c].corr(df["target_class"].astype(float))
            r_reg = df[c].corr(df["target_reg"].astype(float))
            worst = max(
                abs(r_class) if pd.notna(r_class) else 0.0,
                abs(r_reg) if pd.notna(r_reg) else 0.0,
            )
            if worst >= LEAK_CORR_THRESHOLD:
                corr_leaky.append((c, round(worst, 4)))
    if corr_leaky:
        print(
            f"  [{name}] Dropping auto-flagged leaky column(s) "
            f"(|corr| >= {LEAK_CORR_THRESHOLD}): {corr_leaky}"
        )
        corr_leaky_names = {c for c, _ in corr_leaky}
        feature_cols = [c for c in feature_cols if c not in corr_leaky_names]

    categorical_cols = [c for c in feature_cols if c in cfg["categorical"]]
    numeric_cols = [c for c in feature_cols if c not in categorical_cols]

    leftover_object = [c for c in numeric_cols if df[c].dtype == object]
    if leftover_object:
        print(f"  [{name}] WARNING: dropping undeclared object columns: {leftover_object}")
        numeric_cols = [c for c in numeric_cols if c not in leftover_object]

    prefixed = {c: f"{name}__{c}" for c in numeric_cols + categorical_cols}
    keep = ["symbol", "target_class", "target_reg"] + numeric_cols + categorical_cols
    out = df[keep].rename(columns=prefixed)
    numeric_cols = [prefixed[c] for c in numeric_cols]
    categorical_cols = [prefixed[c] for c in categorical_cols]
    return out, numeric_cols, categorical_cols


def build_combo_dataset(modalities: list, loaded: dict, splits: pd.DataFrame):
    dfs = [loaded[m][0] for m in modalities]
    numeric_cols, categorical_cols = [], []

    merged = dfs[0]
    numeric_cols += loaded[modalities[0]][1]
    categorical_cols += loaded[modalities[0]][2]

    for m, df in zip(modalities[1:], dfs[1:]):
        merged = merged.merge(
            df.drop(columns=["target_class", "target_reg"]),
            on="symbol",
            how="inner",
        )
        numeric_cols += loaded[m][1]
        categorical_cols += loaded[m][2]

    merged = merged.merge(splits, on="symbol", how="inner")
    return merged, numeric_cols, categorical_cols


# ---------------------------------------------------------------------------
# Preprocessing & models (capacity moderated for n ≈ 289)
# ---------------------------------------------------------------------------

def make_preprocessor(numeric_cols, categorical_cols):
    transformers = []
    if numeric_cols:
        transformers.append((
            "num",
            Pipeline([
                ("impute", SimpleImputer(strategy="median")),
                ("scale", StandardScaler()),
            ]),
            numeric_cols,
        ))
    if categorical_cols:
        transformers.append((
            "cat",
            Pipeline([
                ("impute", SimpleImputer(strategy="most_frequent")),
                ("onehot", OneHotEncoder(handle_unknown="ignore")),
            ]),
            categorical_cols,
        ))
    return ColumnTransformer(transformers)


def classification_models():
    """
    Capacity settings moderated for n ≈ 289.
    Stack mixes linear / kernel / tree learners for diversity.
    """
    base = [
        ("logreg", LogisticRegression(max_iter=2000, class_weight="balanced")),
        ("svc", SVC(kernel="rbf", probability=True, class_weight="balanced", random_state=42)),
        ("xgb", XGBClassifier(
            n_estimators=100, max_depth=3, learning_rate=0.05,
            eval_metric="logloss", use_label_encoder=False, random_state=42,
        )),
    ]
    return {
        "LogisticRegression": LogisticRegression(
            max_iter=2000, class_weight="balanced"
        ),
        "RandomForest": RandomForestClassifier(
            n_estimators=200, max_depth=8, class_weight="balanced", random_state=42
        ),
        "XGBoost": XGBClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            eval_metric="logloss", use_label_encoder=False, random_state=42,
        ),
        "Stacking": StackingClassifier(
            estimators=base,
            final_estimator=LogisticRegression(max_iter=2000, class_weight="balanced"),
            cv=5,
            passthrough=True,
        ),
    }


def regression_models():
    """
    Capacity settings moderated for n ≈ 289.
    Only called for combos that contain financial or geo (Option 2).
    """
    base = [
        ("enet", ElasticNet(alpha=0.1, l1_ratio=0.5, max_iter=5000)),
        ("svr", SVR(kernel="rbf")),
        ("xgb", XGBRegressor(
            n_estimators=100, max_depth=3, learning_rate=0.05, random_state=42
        )),
    ]
    return {
        "ElasticNet": ElasticNet(alpha=0.1, l1_ratio=0.5, max_iter=5000),
        "RandomForest": RandomForestRegressor(
            n_estimators=200, max_depth=8, random_state=42
        ),
        "XGBoost": XGBRegressor(
            n_estimators=200, max_depth=4, learning_rate=0.05, random_state=42
        ),
        "Stacking": StackingRegressor(
            estimators=base,
            final_estimator=Ridge(alpha=1.0),
            cv=5,
            passthrough=True,
        ),
    }


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def eval_classification(y_true, y_pred, y_proba):
    out = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
    }
    if y_proba is not None and len(set(y_true)) > 1:
        out["roc_auc"] = float(roc_auc_score(y_true, y_proba))
    else:
        out["roc_auc"] = None
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    out["confusion_matrix"] = cm.tolist()
    return out


def eval_regression(y_true, y_pred):
    """y_true and y_pred are in original dollar scale (already expm1'd)."""
    return {
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "r2": float(r2_score(y_true, y_pred)),
        "target_transform": "log1p",
    }


# ---------------------------------------------------------------------------
# Model persistence
# ---------------------------------------------------------------------------

def save_fitted_model(
    models_dir, combo_name, task, model_name, pipe,
    numeric_cols, categorical_cols, n_companies, target_transform=None,
):
    models_dir.mkdir(parents=True, exist_ok=True)
    safe_combo = combo_name.replace("+", "_")
    stem = f"{safe_combo}__{task}__{model_name}"
    joblib.dump(pipe, models_dir / f"{stem}.joblib")
    meta = {
        "combo_name": safe_combo,
        "task": task,
        "model_name": model_name,
        "n_companies_trained_on": n_companies,
        "numeric_cols": numeric_cols,
        "categorical_cols": categorical_cols,
        "target_transform": target_transform,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(models_dir / f"{stem}.meta.json", "w") as f:
        json.dump(meta, f, indent=2)


# ---------------------------------------------------------------------------
# Core training loop
# ---------------------------------------------------------------------------

def run_combo(combo_name, modalities, loaded, splits, outdir, models_dir=None):
    merged, numeric_cols, categorical_cols = build_combo_dataset(
        modalities, loaded, splits
    )
    n_companies = merged["symbol"].nunique()
    if n_companies < 20:
        print(f"  SKIP {combo_name}: only {n_companies} companies after join.")
        return None

    train = merged[merged["split"] == "train"]
    test = merged[merged["split"] != "train"]
    if len(train) < 10 or len(test) < 5:
        print(f"  SKIP {combo_name}: train={len(train)} test={len(test)}.")
        return None

    X_train_raw = train[numeric_cols + categorical_cols]
    X_test_raw = test[numeric_cols + categorical_cols]

    results = {
        "n_companies": int(n_companies),
        "n_train": int(len(train)),
        "n_test": int(len(test)),
        "n_features": len(numeric_cols) + len(categorical_cols),
        "classification": {},
        "regression": {},
    }

    # ----- Classification (always run) -----
    y_train_c = train["target_class"]
    y_test_c = test["target_class"]

    for model_name, model in classification_models().items():
        pre = make_preprocessor(numeric_cols, categorical_cols)
        pipe = Pipeline([("pre", pre), ("clf", model)])
        try:
            pipe.fit(X_train_raw, y_train_c)
            y_pred = pipe.predict(X_test_raw)
            y_proba = (
                pipe.predict_proba(X_test_raw)[:, 1]
                if hasattr(pipe, "predict_proba") else None
            )
            results["classification"][model_name] = eval_classification(
                y_test_c, y_pred, y_proba
            )
            if models_dir is not None:
                save_fitted_model(
                    models_dir, combo_name, "classification", model_name, pipe,
                    numeric_cols, categorical_cols, n_companies,
                    target_transform=None,
                )
        except Exception as e:
            results["classification"][model_name] = {"error": str(e)}

    # ----- Regression (Option 2: only when financial or geo present) -----
    if should_run_regression(modalities):
        y_train_r_log = np.log1p(train["target_reg"])
        y_test_r_raw = test["target_reg"]

        for model_name, model in regression_models().items():
            pre = make_preprocessor(numeric_cols, categorical_cols)
            pipe = Pipeline([("pre", pre), ("reg", model)])
            try:
                pipe.fit(X_train_raw, y_train_r_log)
                y_pred_log = pipe.predict(X_test_raw)
                y_pred_raw = np.clip(np.expm1(y_pred_log), a_min=0, a_max=None)
                results["regression"][model_name] = eval_regression(
                    y_test_r_raw, y_pred_raw
                )
                if models_dir is not None:
                    save_fitted_model(
                        models_dir, combo_name, "regression", model_name, pipe,
                        numeric_cols, categorical_cols, n_companies,
                        target_transform="log1p",
                    )
            except Exception as e:
                results["regression"][model_name] = {"error": str(e)}
        reg_status = "reg-run"
    else:
        results["regression"] = {
            "skipped": "no financial/geo in combo (Option 2 – classification only)"
        }
        reg_status = "reg-skipped"

    best_f1 = max(
        (v.get("f1", 0) for v in results["classification"].values() if isinstance(v, dict)),
        default=0,
    )
    best_r2 = max(
        (v.get("r2", -999) for v in results["regression"].values() if isinstance(v, dict)),
        default=-999,
    )
    print(
        f"  {combo_name}: {n_companies} cos, {results['n_features']} feats "
        f"[{reg_status}]  best F1={best_f1:.3f}  best R2={best_r2:.3f}"
    )
    return results


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_confusion_matrices(combo_name: str, results: dict, group_dir: Path, model_names: list):
    if not results or not results.get("classification"):
        return
    clf_results = results["classification"]
    available = [
        m for m in model_names
        if isinstance(clf_results.get(m), dict) and "confusion_matrix" in clf_results[m]
    ]
    if not available:
        return

    fig, axes = plt.subplots(1, len(available), figsize=(4.5 * len(available), 4))
    if len(available) == 1:
        axes = [axes]

    for ax, model_name in zip(axes, available):
        cm = np.array(clf_results[model_name]["confusion_matrix"])
        ax.imshow(cm, cmap="Blues")
        ax.set_title(f"{model_name}\nF1={clf_results[model_name].get('f1', 0):.3f}", fontsize=10)
        ax.set_xlabel("Predicted")
        ax.set_ylabel("True")
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["0", "1"])
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["0", "1"])
        thresh = cm.max() / 2 if cm.max() > 0 else 0.5
        for i in range(2):
            for j in range(2):
                ax.text(
                    j, i, str(cm[i, j]),
                    ha="center", va="center",
                    color="white" if cm[i, j] > thresh else "black",
                    fontsize=12,
                )

    fig.suptitle(f"Confusion matrices — {combo_name}", fontsize=12)
    plt.tight_layout()
    safe_name = combo_name.replace("+", "_")
    plt.savefig(group_dir / f"{safe_name}_confusion_matrices.png", dpi=150)
    plt.close()


def plot_group(group_results: dict, group_dir: Path, group_label: str, model_names: list):
    combos = list(group_results.keys())
    if not combos:
        return

    x = np.arange(len(combos))
    width = 0.8 / len(model_names)

    # Classification F1
    fig, ax = plt.subplots(figsize=(max(6, 2.5 * len(combos)), 6))
    for i, m in enumerate(model_names):
        vals = [
            group_results[c]["classification"].get(m, {}).get("f1", 0)
            if group_results[c] else 0
            for c in combos
        ]
        ax.bar(x + i * width, vals, width, label=m)
    ax.set_xticks(x + width * (len(model_names) - 1) / 2)
    ax.set_xticklabels(combos, rotation=45, ha="right")
    ax.set_ylabel("F1 score")
    ax.set_title(f"Classification F1 — {group_label}")
    ax.legend()
    plt.tight_layout()
    plt.savefig(group_dir / f"{group_label}_classification_f1_comparison.png", dpi=150)
    plt.close()

    # Regression R² (only combos that actually ran regression)
    reg_combos = [
        c for c in combos
        if group_results[c]
        and isinstance(group_results[c].get("regression"), dict)
        and "skipped" not in group_results[c]["regression"]
    ]
    if reg_combos:
        x_reg = np.arange(len(reg_combos))
        fig, ax = plt.subplots(figsize=(max(6, 2.5 * len(reg_combos)), 6))
        for i, m in enumerate(model_names):
            vals = [
                group_results[c]["regression"].get(m, {}).get("r2", 0)
                for c in reg_combos
            ]
            ax.bar(x_reg + i * width, vals, width, label=m)
        ax.set_xticks(x_reg + width * (len(model_names) - 1) / 2)
        ax.set_xticklabels(reg_combos, rotation=45, ha="right")
        ax.set_ylabel("R² score")
        ax.set_title(f"Regression R² — {group_label} (log1p-fit, dollar-scale eval)")
        ax.axhline(0, color="black", linewidth=0.8)
        ax.legend()
        plt.tight_layout()
        plt.savefig(group_dir / f"{group_label}_regression_r2_comparison.png", dpi=150)
        plt.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--financials", default="output/financials_dataset.csv")
    ap.add_argument("--esg", default="output/esg_dataset.csv")
    ap.add_argument("--news", default="output/news_dataset.csv")
    ap.add_argument("--geo", default="output/geographical_dataset.csv")
    ap.add_argument("--splits", default="output/company_splits.csv")
    ap.add_argument("--outdir", default="output/model_results")
    ap.add_argument(
        "--models-dir", default="models/saved",
        help="Where to save fitted pipelines (empty string to skip)",
    )
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    models_dir = Path(args.models_dir) if args.models_dir else None
    group_dirs = {g: outdir / g for g in GROUP_NAMES}
    for d in group_dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    print("Loading modalities...")
    loaded = {
        "financial": load_modality("financial", args.financials),
        "esg": load_modality("esg", args.esg),
        "news": load_modality("news", args.news),
        "geo": load_modality("geo", args.geo),
    }
    splits = pd.read_csv(args.splits)
    splits["split"] = splits["split"].apply(
        lambda s: "train" if s == "train" else "test"
    )

    names = list(loaded.keys())
    singles = [(n,) for n in names]
    pairs = list(itertools.combinations(names, 2))
    fourway = [tuple(names)]
    grouped_combos = {
        "singles": singles,
        "pairs": pairs,
        "fourway": fourway,
    }
    model_names_clf = ["LogisticRegression", "RandomForest", "XGBoost", "Stacking"]

    all_group_results = {}
    for group_label, combo_list in grouped_combos.items():
        print(f"\n=== Running {len(combo_list)} {group_label} combo(s) ===")
        group_results = {}
        for combo in combo_list:
            combo_name = "+".join(combo)
            print(f"[{combo_name}]")
            result = run_combo(
                combo_name, list(combo), loaded, splits, outdir, models_dir
            )
            group_results[combo_name] = result
            plot_confusion_matrices(
                combo_name, result, group_dirs[group_label], model_names_clf
            )

        out_path = group_dirs[group_label] / f"{group_label}_results.json"
        with open(out_path, "w") as f:
            json.dump(group_results, f, indent=2, default=str)
        print(f"Wrote {out_path}")

        plot_group(group_results, group_dirs[group_label], group_label, model_names_clf)
        print(f"Wrote plots to {group_dirs[group_label]}/")
        all_group_results[group_label] = group_results

    index = {
        g: {
            "results_json": str(group_dirs[g] / f"{g}_results.json"),
            "classification_plot": str(
                group_dirs[g] / f"{g}_classification_f1_comparison.png"
            ),
            "regression_plot": str(
                group_dirs[g] / f"{g}_regression_r2_comparison.png"
            ),
            "confusion_matrix_dir": str(group_dirs[g]),
            "combos": list(all_group_results[g].keys()),
        }
        for g in GROUP_NAMES
    }
    with open(outdir / "index.json", "w") as f:
        json.dump(index, f, indent=2)
    print(f"\nWrote {outdir / 'index.json'}")

    if models_dir:
        n_saved = len(list(models_dir.glob("*.joblib")))
        print(f"Saved {n_saved} fitted model pipelines to {models_dir}/")


if __name__ == "__main__":
    main()