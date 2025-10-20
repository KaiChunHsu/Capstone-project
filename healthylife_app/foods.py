from typing import Dict, List, Tuple
import re
import pandas as pd
import numpy as np

# Loading & Normalization
# If the list match one of the correct columns it will run smoothly when uploading the files
STANDARD_COLS = {
    "food": ["food", "name", "item", "食品", "食物"],
    "kcal": ["kcal", "calories", "calorie", "熱量", "卡路里", "calories (kcal)", "kcal/serving"],
    "protein_g": ["protein", "protein_g", "蛋白質", "蛋白(g)", "蛋白質(g)", "protein (g)", "prot(g)"],
    "carbs_g": ["carb", "carbs", "carbohydrate", "carbohydrates", "碳水", "碳水化合物", "碳水(g)", "carbs (g)"],
    "fat_g": ["fat", "fat_g", "脂肪", "脂肪(g)", "fat (g)"],
}

# During original cloumns, we will find out whether candidates is as same as cols
def _find_col(cols: List[str], candidates: List[str]) -> str | None:
    # convert to lower case
    lc = [c.strip().lower() for c in cols]
    for cand in candidates:
        if cand.lower() in lc:
            return cols[lc.index(cand.lower())]
    return None


# https://www.numeric-gmbh.ch/posts/python-regex-numbers-and-units.html
def _to_number(x) -> float:
    # Messy strings like '120 kcal', '1,234', '80g' to float; NaN if not possible.
    
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    s = str(x).strip()
    if not s:
        return np.nan
    # replace the comma to empty based on convert easily
    s = s.replace(",", "")
    # pick first number (int/float) in the string
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return np.nan
    try:
        return float(m.group(0))
    except Exception:
        return np.nan


# load the food data
def load_foods(csv_path_or_buf) -> pd.DataFrame:
    df = pd.read_csv(csv_path_or_buf)
    # get all the column names
    cols = list(df.columns)

    mapping = {} # record standard columns name
    # using the dict that I created before
    for std, cands in STANDARD_COLS.items():
        col = _find_col(cols, cands)
        if col is None:
            # if cannot find it return nan
            df[std] = np.nan
            mapping[std] = std
        else:
            mapping[std] = col

    # retain the five main columns after mapping the dict
    # _to_number is the fucntion that we created for convert the string to float
    out = pd.DataFrame({
        "food": df[mapping["food"]] if mapping["food"] in df else df.index.astype(str),
        "kcal": df[mapping["kcal"]].apply(_to_number),
        "protein_g": df[mapping["protein_g"]].apply(_to_number),
        "carbs_g": df[mapping["carbs_g"]].apply(_to_number),
        "fat_g": df[mapping["fat_g"]].apply(_to_number),
    })

    # record initial number of columns
    before = len(out)
    # delete the columns without kcal
    out = out.dropna(subset=["kcal"]).copy()
    # record the number of columns after deleting
    after_kcal = len(out)

    # Fill NaNs in each row with 0 
    for c in ["protein_g", "carbs_g", "fat_g"]:
        out[c] = out[c].fillna(0.0)

    # Add helpful densities per 100 kcal
    # ignore the divide 0 or Nan
    with np.errstate(divide='ignore', invalid='ignore'):
        # calculate protein, carb, and fat per 100kcal
        out["protein_per_100kcal"] = (out["protein_g"] / out["kcal"].replace(0, np.nan)) * 100.0
        out["carbs_per_100kcal"] = (out["carbs_g"] / out["kcal"].replace(0, np.nan)) * 100.0
        out["fat_per_100kcal"] = (out["fat_g"] / out["kcal"].replace(0, np.nan)) * 100.0
    # fill nan if infinity
    out = out.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    # unified string format
    out["food"] = out["food"].astype(str).str.strip()

    # return to Dataframe after adjusting the columns
    # or add extra reources
    out.attrs["rows_in"] = before
    out.attrs["rows_after_kcal"] = after_kcal
    out.attrs["columns_mapped"] = mapping
    return out

# Scoring

def _goal_ratios(goals: Dict[str, int]) -> Tuple[float, float, float]:
    kcal = float(goals.get("kcal") or 2000)
    p = float(goals.get("protein_g") or 120)
    c = float(goals.get("carbs_g") or 200)
    f = float(goals.get("fat_g") or 60)
    # Convert grams to kcal to compute macro ratio targets
    p_k = p * 4.0
    c_k = c * 4.0
    f_k = f * 9.0

    # avoid denominator as 0
    total = max(p_k + c_k + f_k, 1.0)
    return p_k / total, c_k / total, f_k / total


def suggest_meals(
    foods: pd.DataFrame,
    goals: Dict[str, int],
    meal_kcal: int = 600,
    strategy: str = "balanced",
    topn: int = 12, # return the best food as deafult 12
) -> pd.DataFrame:
    """Rank single-food suggestions for a target meal_kcal.

    strategy:
      - "balanced": match macro ratio (P/C/F) close to goal ratios
      - "high_protein": prioritize protein density
      - "low_carb": prioritize lower carbs per kcal

    Returns a dataframe with score ascending (lower is better).
    """
    df = foods.copy()
    if df.empty:
        return df

    # return the ratios of protein, carbs, and fat
    gp, gc, gf = _goal_ratios(goals)

    # Predicted macros at target meal_kcal by scaling each food to the target kcal
    # https://numpy.org/doc/stable/reference/generated/numpy.errstate.html
    with np.errstate(divide='ignore', invalid='ignore'):
        scale = meal_kcal / df["kcal"].replace(0, np.nan)
        p_kcal = (df["protein_g"] * 4.0) * scale
        c_kcal = (df["carbs_g"] * 4.0) * scale
        f_kcal = (df["fat_g"] * 9.0) * scale
        total_k = (p_kcal + c_kcal + f_kcal).replace(0, np.nan)
        # the ratio under that food claories
        rp = (p_kcal / total_k).fillna(0.0)
        rc = (c_kcal / total_k).fillna(0.0)
        rf = (f_kcal / total_k).fillna(0.0)

    # Ratio distance to goal
    ratio_mse = (rp - gp) ** 2 + (rc - gc) ** 2 + (rf - gf) ** 2

    # Calorie mismatch penalty (prefer foods whose 1 serving kcal is near meal_kcal)
    kcal_pen = ((df["kcal"] - meal_kcal).abs() / max(meal_kcal, 1))

    if strategy == "high_protein":
        score = -df["protein_per_100kcal"] + 0.2 * kcal_pen
    elif strategy == "low_carb":
        score = df["carbs_per_100kcal"] + 0.2 * kcal_pen
    else:  # balanced
        score = ratio_mse + 0.2 * kcal_pen

    # https://pandas.pydata.org/pandas-docs/version/2.2.2/reference/api/pandas.DataFrame.assign.html
    out = df.assign(
        meal_kcal_target=meal_kcal,
        # fill nan with 0 round the number to 0.0
        est_protein_g=(df["protein_g"] * (meal_kcal / df["kcal"].replace(0, np.nan))).fillna(0.0).round(1),
        est_carbs_g=(df["carbs_g"] * (meal_kcal / df["kcal"].replace(0, np.nan))).fillna(0.0).round(1),
        est_fat_g=(df["fat_g"] * (meal_kcal / df["kcal"].replace(0, np.nan))).fillna(0.0).round(1),
        score=score,
    ).sort_values("score", ascending=True)

    keep_cols = [
        "food", "kcal", "protein_g", "carbs_g", "fat_g",
        "protein_per_100kcal", "carbs_per_100kcal", "fat_per_100kcal",
        "score",
    ]
    keep = [c for c in keep_cols if c in out.columns]
    # top 5 best food 
    return out[keep].head(topn).reset_index(drop=True)
