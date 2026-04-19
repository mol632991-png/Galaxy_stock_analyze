from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Sequence, Tuple

import akshare as ak
import numpy as np
import pandas as pd


def _quarter_candidates() -> List[str]:
    today = datetime.now()
    quarter_ends = ["1231", "0930", "0630", "0331"]
    return [f"{year}{quarter}" for year in range(today.year, today.year - 3, -1) for quarter in quarter_ends]


def _clean_numeric(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    working = df.copy()
    for column in columns:
        if column in working.columns:
            working[column] = pd.to_numeric(working[column], errors="coerce")
    return working


def _ema(series: pd.Series, span: float) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _sma_tdx(series: pd.Series, n: float, m: float) -> pd.Series:
    values = []
    prev = None
    for item in series.fillna(0):
        if prev is None:
            prev = item
        else:
            prev = (m * item + (n - m) * prev) / n
        values.append(prev)
    return pd.Series(values, index=series.index)


def _cross(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift(1) <= b.shift(1))


def _compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def _compute_cci(tp: pd.Series, n: int = 14) -> pd.Series:
    ma = tp.rolling(n).mean()
    md = (tp - ma).abs().rolling(n).mean()
    return (tp - ma) / (0.015 * md.replace(0, np.nan))


def _to_tx_symbol(code: str) -> str:
    if code.startswith(("600", "601", "603", "605", "688", "689")):
        return f"sh{code}"
    if code.startswith(("430", "431", "832", "833", "834", "835", "836", "837", "838", "839", "870", "871", "872", "873", "874", "875", "876", "877", "878", "879", "920")):
        return f"bj{code}"
    return f"sz{code}"


def fetch_spot_data() -> pd.DataFrame:
    spot_df = ak.stock_zh_a_spot_em()
    if spot_df is None or spot_df.empty:
        raise RuntimeError("A股实时行情接口返回为空。")
    spot_df = spot_df.copy()
    spot_df["代码"] = spot_df["代码"].astype(str).str.zfill(6)
    spot_df = _clean_numeric(spot_df, ["最新价", "涨跌幅", "涨跌额", "成交量", "成交额", "振幅", "最高", "最低", "今开", "昨收", "量比", "换手率", "市盈率-动态", "市净率", "总市值", "流通市值", "涨速", "5分钟涨跌", "60日涨跌幅", "年初至今涨跌幅"])
    return spot_df


def _latest_financial_report() -> pd.DataFrame:
    last_error: Optional[Exception] = None
    for report_date in _quarter_candidates():
        try:
            df = ak.stock_yjbb_em(date=report_date)
        except Exception as exc:
            last_error = exc
            continue
        if df is not None and not df.empty:
            df = df.copy()
            df["报告期"] = report_date
            return df
    raise RuntimeError(f"无法获取最近财报数据: {last_error}")


def fetch_financial_data() -> pd.DataFrame:
    financial_df = _latest_financial_report()
    financial_df = financial_df.copy()
    financial_df["股票代码"] = financial_df["股票代码"].astype(str).str.zfill(6)
    financial_df = _clean_numeric(financial_df, ["每股收益", "营业总收入-营业总收入", "营业总收入-同比增长", "营业总收入-季度环比增长", "净利润-净利润", "净利润-同比增长", "净利润-季度环比增长", "每股净资产", "净资产收益率", "每股经营现金流量", "销售毛利率"])
    financial_df = financial_df.rename(columns={"股票代码": "代码", "股票简称": "名称"})
    columns = ["代码", "名称", "每股收益", "营业总收入-营业总收入", "营业总收入-同比增长", "营业总收入-季度环比增长", "净利润-净利润", "净利润-同比增长", "净利润-季度环比增长", "每股净资产", "净资产收益率", "每股经营现金流量", "销售毛利率", "所处行业", "最新公告日期", "报告期"]
    return financial_df[columns]


def fetch_index_snapshot() -> List[dict]:
    targets = {"000001": "上证指数", "399001": "深证成指", "399006": "创业板指"}
    frames: List[pd.DataFrame] = []
    for symbol in ("沪深重要指数", "上证系列指数", "深证系列指数"):
        try:
            df = ak.stock_zh_index_spot_em(symbol=symbol)
        except Exception:
            continue
        if df is not None and not df.empty:
            frames.append(df)
    if not frames:
        return []
    all_df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["代码"])
    all_df = _clean_numeric(all_df, ["最新价", "涨跌幅", "涨跌额"])
    rows = []
    for code, name in targets.items():
        matched = all_df[all_df["代码"] == code]
        if matched.empty:
            continue
        row = matched.iloc[0]
        rows.append({"code": code, "name": name, "price": round(float(row.get("最新价", 0) or 0), 2), "pct_change": round(float(row.get("涨跌幅", 0) or 0), 2), "change": round(float(row.get("涨跌额", 0) or 0), 2)})
    return rows


def fetch_sector_fund_flow() -> pd.DataFrame:
    try:
        df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
        if df is not None and not df.empty:
            df = _clean_numeric(df, ["今日涨跌幅", "主力净流入-净额", "主力净流入-占比"])
            return df
    except Exception:
        pass
    return pd.DataFrame()


def fetch_individual_fund_flow_rank() -> pd.DataFrame:
    try:
        df = ak.stock_individual_fund_flow_rank(indicator="今日")
        if df is not None and not df.empty:
            df["代码"] = df["代码"].astype(str).str.zfill(6)
            df = _clean_numeric(df, ["最新价", "今日涨跌幅", "今日主力净流入-净额", "今日主力净流入-占比"])
            return df
    except Exception:
        pass
    return pd.DataFrame()


def build_top_summary(spot_df: pd.DataFrame) -> dict:
    return {"limit_up_count": int((spot_df["涨跌幅"] >= 9.8).sum()), "gt_7_count": int((spot_df["涨跌幅"] > 7).sum()), "limit_down_count": int((spot_df["涨跌幅"] <= -9.8).sum())}


def _fetch_fund_flow_ratio(code: str) -> float:
    market = _to_tx_symbol(code)[:2]
    try:
        fund_df = ak.stock_individual_fund_flow(stock=code, market=market)
    except Exception:
        return 0.0
    if fund_df is None or fund_df.empty:
        return 0.0
    latest = fund_df.iloc[-1]
    inflow = 0.0
    for col in fund_df.columns:
        if "主力净流入-净额" in col or "主力净流入净额" in col:
            value = pd.to_numeric(latest[col], errors="coerce")
            if pd.notna(value):
                inflow = float(value)
                break
    amount = None
    for col in fund_df.columns:
        if "成交额" in col:
            value = pd.to_numeric(latest[col], errors="coerce")
            if pd.notna(value) and value != 0:
                amount = float(value)
                break
    return round(inflow / amount * 100, 4) if amount else 0.0


def _fetch_hourly_signals(code: str) -> dict:
    try:
        hour_df = ak.stock_zh_a_hist_min_em(symbol=code, period="60", adjust="qfq")
    except Exception:
        return {"hour_up_tri_10d": False, "hour_high_120": np.nan, "hour_low_120": np.nan}
    if hour_df is None or hour_df.empty:
        return {"hour_up_tri_10d": False, "hour_high_120": np.nan, "hour_low_120": np.nan}
    hour_df = hour_df.copy()
    rename_map = {}
    for col in hour_df.columns:
        if "时间" in col or "日期" in col:
            rename_map[col] = "datetime"
        elif col in ("开盘", "open"):
            rename_map[col] = "open"
        elif col in ("收盘", "close"):
            rename_map[col] = "close"
        elif col in ("最高", "high"):
            rename_map[col] = "high"
        elif col in ("最低", "low"):
            rename_map[col] = "low"
    hour_df = hour_df.rename(columns=rename_map)
    if not {"close", "high", "low"}.issubset(hour_df.columns):
        return {"hour_up_tri_10d": False, "hour_high_120": np.nan, "hour_low_120": np.nan}
    hour_df = _clean_numeric(hour_df, ["open", "close", "high", "low"])
    hour_df = hour_df.dropna(subset=["close", "high", "low"]).tail(180)
    if len(hour_df) < 60:
        return {"hour_up_tri_10d": False, "hour_high_120": np.nan, "hour_low_120": np.nan}
    close = hour_df["close"]
    high = hour_df["high"]
    low = hour_df["low"]
    var1 = (2 * close + high + low) / 4
    var2 = low.rolling(34).min()
    var3 = high.rolling(34).max()
    xx = _ema((var1 - var2) / (var3 - var2).replace(0, np.nan) * 100, 13)
    yy = _ema(0.667 * xx.shift(1) + 0.333 * xx, 2)
    up_tri = _cross(xx, pd.Series(20.0, index=hour_df.index)) & (yy < xx)
    return {"hour_up_tri_10d": bool(up_tri.tail(10).fillna(False).sum() >= 1), "hour_high_120": round(float(high.tail(120).max()), 4), "hour_low_120": round(float(low.tail(120).min()), 4)}


def _compute_pattern_signals(hist_df: pd.DataFrame) -> dict:
    close = hist_df["close"]
    high = hist_df["high"]
    low = hist_df["low"]
    tr1 = _ema(_ema(_ema(close, 12), 12), 12)
    trix = (tr1 - tr1.shift(1)) / tr1.shift(1) * 100
    trma1 = trix.rolling(20).mean()
    trix_cross_buy = _cross(trix, trma1)
    zvar3 = (2 * close + high + low) / 4
    zvar4 = low.rolling(34).min()
    zvar5 = high.rolling(34).max()
    main_line = _ema((zvar3 - zvar4) / (zvar5 - zvar4).replace(0, np.nan) * 100, 13)
    retail_line = _ema(0.667 * main_line.shift(1) + 0.333 * main_line, 2)
    upward_signal = _cross(main_line, pd.Series(30.0, index=hist_df.index)) & (retail_line < main_line)
    wash_a = (close - low.rolling(32).min()) / (high.rolling(32).max() - low.rolling(32).min()).replace(0, np.nan) * 1.2 * close
    vol1 = _ema(wash_a, 3)
    vol2 = _ema(wash_a, 5)
    vol3 = _ema(wash_a, 7)
    t2 = (vol2 < vol3) & (vol1 > vol1.shift(1))
    a014 = (2 * close + high + low) / 4
    a013 = high.rolling(34).max()
    a015 = low.rolling(34).min()
    a016 = _ema((a014 - a015) / (a013 - a015).replace(0, np.nan) * 100, 13)
    a017 = _ema(0.667 * a016.shift(1) + 0.333 * a016, 2)
    kkmd = (a016 - a017 > 1) & (a016 < 30) & (a017 < 30)
    trough_break = (low == low.rolling(16).min()) & ((high - low) > 0.04)
    zig6 = close.rolling(6).mean()
    zig22 = close.rolling(22).mean()
    zig51 = close.rolling(51).mean()
    zig72 = close.rolling(72).mean()
    combo_trial = (((zig6 > zig6.shift(1)) & (zig6.shift(1) <= zig6.shift(2)) & (zig6.shift(2) <= zig6.shift(3))) | ((zig22 > zig22.shift(1)) & (zig22.shift(1) <= zig22.shift(2)) & (zig22.shift(2) <= zig22.shift(3))) | ((zig51 > zig51.shift(1)) & (zig51.shift(1) <= zig51.shift(2)) & (zig51.shift(2) <= zig51.shift(3))) | ((zig72 > zig72.shift(1)) & (zig72.shift(1) <= zig72.shift(2)) & (zig72.shift(2) <= zig72.shift(3))))
    a7 = close - close.shift(1)
    a8 = 100 * _ema(_ema(a7, 6), 6) / _ema(_ema(a7.abs(), 6), 6).replace(0, np.nan)
    buy = (a8.rolling(2).min() == a8.rolling(7).min()) & ((a8 < 0).rolling(2).sum() >= 1) & _cross(a8, a8.rolling(2).mean())
    tp = (high + low + close) / 3
    cci = _compute_cci(tp, 14)
    acci = (cci.shift(1) <= -100) | _cross(cci, pd.Series(-100.0, index=cci.index))
    amtm0 = _cross(close - close.shift(9), pd.Series(0.0, index=close.index))
    axt = close >= close.shift(9)
    rsi_build = _sma_tdx((close - close.shift(1)).clip(lower=0), 4.1, 1) / _sma_tdx((close - close.shift(1)).abs(), 4.1, 1).replace(0, np.nan) * 100
    return {
        "signal_upward_10d": bool((trix_cross_buy.tail(10).fillna(False).sum() >= 1) or (upward_signal.tail(10).fillna(False).sum() >= 1)),
        "signal_short_buy_20d": bool((t2.tail(20).fillna(False).sum() >= 1) and (kkmd.tail(20).fillna(False).sum() >= 1)),
        "main_buy_signal": bool(((buy & acci) | (buy & (~acci) & amtm0) | (buy & (~acci) & (~amtm0) & axt)).tail(5).fillna(False).any()),
        "main_trial_signal": bool((combo_trial | trough_break).tail(5).fillna(False).any()),
        "short_buy_signal": bool(kkmd.tail(30).fillna(False).any()),
        "build_position_signal": bool(_cross(rsi_build, pd.Series(11.0, index=rsi_build.index)).tail(10).fillna(False).any()),
    }


def _compute_shape_features(hist_df: pd.DataFrame) -> dict:
    close = hist_df["close"]
    high = hist_df["high"]
    low = hist_df["low"]
    recent = hist_df.tail(min(len(hist_df), 300))
    swing_high = float(recent["high"].max())
    swing_low = float(recent["low"].min())
    price_range = max(swing_high - swing_low, 1e-6)
    fib_500 = swing_high - price_range * 0.5
    fib_618 = swing_high - price_range * 0.618
    fib_809 = swing_high - price_range * 0.809
    ma5 = float(close.rolling(5).mean().iloc[-1])
    ma10 = float(close.rolling(10).mean().iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma60 = float(close.rolling(60).mean().iloc[-1])
    slope_ma10 = float(close.rolling(10).mean().diff(3).iloc[-1])
    last_close = float(close.iloc[-1])
    drawdown_ratio = float((swing_high - last_close) / swing_high * 100) if swing_high > 0 else 0
    close_to_low_zone = bool(last_close <= fib_618 and last_close >= fib_809 * 0.95)
    return {
        "ma5": round(ma5, 4),
        "ma10": round(ma10, 4),
        "ma20": round(ma20, 4),
        "ma60": round(ma60, 4),
        "rsi14": round(float(_compute_rsi(close, 14).iloc[-1]), 2),
        "high_120": round(float(high.tail(120).max()), 4),
        "low_120": round(float(low.tail(120).min()), 4),
        "昨日涨跌幅": round(float(hist_df["pct_change"].iloc[-2]) if len(hist_df) >= 2 else 0, 2),
        "前日涨跌幅": round(float(hist_df["pct_change"].iloc[-3]) if len(hist_df) >= 3 else 0, 2),
        "fib_618": round(fib_618, 4),
        "fib_809": round(fib_809, 4),
        "drawdown_ratio": round(drawdown_ratio, 2),
        "close_to_low_zone": close_to_low_zone,
        "shape_similarity": bool((drawdown_ratio >= 18) and (last_close < fib_500) and (last_close <= fib_618 or close_to_low_zone) and (ma5 >= ma10 * 0.97) and (ma10 >= ma20 * 0.90) and (slope_ma10 > -1.2)),
        "slope_ma10": round(slope_ma10, 4),
        "成交额均线比": round(float(hist_df["amount"].rolling(5).mean().iloc[-1] / hist_df["amount"].rolling(20).mean().iloc[-1]), 4) if hist_df["amount"].rolling(20).mean().iloc[-1] else np.nan,
    }


def _fetch_history_indicator(code: str, lookback_days: int = 420) -> Optional[dict]:
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y%m%d")
    end_date = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")
    try:
        hist_df = ak.stock_zh_a_hist_tx(symbol=_to_tx_symbol(code), start_date=start_date, end_date=end_date, adjust="qfq")
    except Exception:
        return None
    if hist_df is None or hist_df.empty:
        return None
    hist_df = hist_df.copy()
    hist_df = _clean_numeric(hist_df, ["open", "close", "high", "low", "amount", "pct_change"])
    hist_df = hist_df.dropna(subset=["close", "high", "low", "amount"])
    if len(hist_df) < 120:
        return None
    if "pct_change" not in hist_df.columns:
        hist_df["pct_change"] = hist_df["close"].pct_change().fillna(0) * 100
    else:
        hist_df["pct_change"] = hist_df["pct_change"].fillna(hist_df["close"].pct_change().fillna(0) * 100)
    latest = hist_df.iloc[-1]
    pattern_signals = _compute_pattern_signals(hist_df)
    shape_features = _compute_shape_features(hist_df)
    hourly = _fetch_hourly_signals(code)
    fund_flow_ratio = _fetch_fund_flow_ratio(code)
    
    # 增加：检测近5日内是否出现过涨停 (含今日)
    # 中国主板涨停一般 >= 9.8%
    recent_hist = hist_df.tail(6)
    had_limit_up = bool((recent_hist['pct_change'] >= 9.8).any())
    
    return {
        "代码": code,
        "上市天数": int(len(hist_df)),
        "close_hist": round(float(latest["close"]), 4),
        "fund_flow_ratio": fund_flow_ratio,
        "had_recent_limit_up": had_limit_up,
        "signal_fund_flow": bool((fund_flow_ratio > 0.15) and (float(latest.get("pct_change", 0) or 0) < 6)),
        "signal_hourly_60_3pct": bool(hourly["hour_up_tri_10d"] and float(latest["close"]) > 10),
        **pattern_signals,
        **shape_features,
        **hourly,
    }


def fetch_technical_indicators(codes: Sequence[str], max_workers: int = 8) -> pd.DataFrame:
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_fetch_history_indicator, code): code for code in codes}
        for future in as_completed(future_map):
            result = future.result()
            if result:
                results.append(result)
    return pd.DataFrame(results)


def _pick_analysis_seed(merged: pd.DataFrame, extra_codes: Sequence[str]) -> pd.DataFrame:
    top_seed = merged.sort_values(by=["coarse_score", "成交额"], ascending=[False, False]).head(520)
    if not extra_codes:
        return top_seed
    extra_df = merged[merged["代码"].isin(set(extra_codes))]
    return pd.concat([top_seed, extra_df], ignore_index=True).drop_duplicates(subset=["代码"])


def build_stock_dataset(extra_codes: Optional[Sequence[str]] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    spot_df = fetch_spot_data()
    financial_df = fetch_financial_data()
    merged = spot_df.merge(financial_df, on=["代码", "名称"], how="left")
    merged = merged[(~merged["名称"].str.contains("ST", na=False)) & (~merged["名称"].str.contains("退", na=False)) & (merged["最新价"] > 0) & (merged["成交额"] >= 30_000_000)].copy()
    merged["营业总收入-同比增长"] = merged["营业总收入-同比增长"].fillna(0)
    merged["净利润-同比增长"] = merged["净利润-同比增长"].fillna(0)
    merged["净资产收益率"] = merged["净资产收益率"].fillna(0)
    merged["销售毛利率"] = merged["销售毛利率"].fillna(0)
    merged["每股经营现金流量"] = merged["每股经营现金流量"].fillna(0)
    merged["市盈率-动态"] = merged["市盈率-动态"].replace([np.inf, -np.inf], np.nan).fillna(-1)
    merged["市净率"] = merged["市净率"].replace([np.inf, -np.inf], np.nan).fillna(-1)
    
    # 构建热度评分
    merged["coarse_score"] = merged["成交额"] / 100_000_000 * 0.20 + merged["换手率"].fillna(0) * 0.15 + merged["60日涨跌幅"].fillna(0) * 0.10 + merged["营业总收入-同比增长"] * 0.15 + merged["净利润-同比增长"] * 0.20 + merged["净资产收益率"] * 0.20
    
    # 强制将今日所有涨停股加入分析种子
    limit_ups = merged[merged["涨跌幅"] >= 9.8]["代码"].tolist()
    extra_codes = list(set((extra_codes or []) + limit_ups))
    
    # 整合：个股资金流排名
    ff_rank_df = fetch_individual_fund_flow_rank()
    if not ff_rank_df.empty:
        # 将 top 100 资金流个股加入 seed
        top_ff_codes = ff_rank_df["代码"].head(100).tolist()
        extra_codes = list(set((extra_codes or []) + top_ff_codes))
        merged = merged.merge(ff_rank_df[['代码', '今日主力净流入-净额', '今日主力净流入-占比']], on="代码", how="left")
    
    seed = _pick_analysis_seed(merged, extra_codes or [])
    technical_df = fetch_technical_indicators(seed["代码"].tolist())
    if technical_df.empty:
        return pd.DataFrame(), spot_df
    dataset = seed.merge(technical_df, on="代码", how="inner")
    dataset = dataset.replace([np.inf, -np.inf], np.nan).dropna(subset=["ma20", "ma60", "rsi14"])
    dataset = dataset.sort_values(by=["coarse_score", "成交额"], ascending=[False, False]).reset_index(drop=True)
    return dataset, spot_df


def format_fundamental_analysis(row: pd.Series) -> str:
    return f"ROE {float(row.get('净资产收益率', 0) or 0):.2f}%，营收同比 {float(row.get('营业总收入-同比增长', 0) or 0):.2f}%，净利同比 {float(row.get('净利润-同比增长', 0) or 0):.2f}%，PE {float(row.get('市盈率-动态', 0) or 0):.2f}，PB {float(row.get('市净率', 0) or 0):.2f}。"


def format_technical_analysis(row: pd.Series) -> str:
    return f"现价 {float(row.get('最新价', 0) or 0):.2f}，MA20 {float(row.get('ma20', 0) or 0):.2f}，MA60 {float(row.get('ma60', 0) or 0):.2f}，RSI14 {float(row.get('rsi14', 0) or 0):.2f}，昨日涨跌幅 {float(row.get('昨日涨跌幅', 0) or 0):.2f}%，前日涨跌幅 {float(row.get('前日涨跌幅', 0) or 0):.2f}%。"
