from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, Iterable, List

import akshare as ak
import pandas as pd

NEGATIVE_KEYWORDS: Dict[str, List[str]] = {
    "法律诉讼": ["诉讼", "仲裁", "立案", "涉案", "司法冻结", "被执行人", "失信"],
    "监管处罚": ["处罚", "罚款", "警示函", "监管函", "问询函", "纪律处分", "行政监管"],
    "财务造假": ["造假", "虚增", "虚减", "虚假记载", "信息披露违法", "财务舞弊", "重大会计差错"],
    "经营风险": ["亏损", "债务逾期", "违约", "退市风险", "资金占用", "商誉减值", "持续经营"],
    "负面舆情": ["暴雷", "爆雷", "踩雷", "业绩变脸", "欠薪", "停产", "事故", "下修"],
}
KEYWORD_WEIGHTS: Dict[str, int] = {"法律诉讼": 3, "监管处罚": 3, "财务造假": 5, "经营风险": 2, "负面舆情": 1}


def _find_hits(text: str) -> List[str]:
    text = str(text)
    return [category for category, keywords in NEGATIVE_KEYWORDS.items() if any(keyword in text for keyword in keywords)]


def _fetch_recent_announcements(symbols: Iterable[str], days: int = 20) -> pd.DataFrame:
    symbol_set = set(symbols)
    frames: List[pd.DataFrame] = []
    for day_offset in range(days):
        date_str = (datetime.now() - timedelta(days=day_offset)).strftime("%Y%m%d")
        for category in ("风险提示", "重大事项", "财务报告"):
            try:
                notice_df = ak.stock_notice_report(symbol=category, date=date_str)
            except Exception:
                continue
            if notice_df is None or notice_df.empty:
                continue
            notice_df = notice_df.copy()
            notice_df["代码"] = notice_df["代码"].astype(str).str.zfill(6)
            notice_df = notice_df[notice_df["代码"].isin(symbol_set)]
            if notice_df.empty:
                continue
            frames.append(notice_df[["代码", "名称", "公告标题", "公告日期"]])
    if not frames:
        return pd.DataFrame(columns=["代码", "名称", "公告标题", "公告日期"])
    return pd.concat(frames, ignore_index=True)


def _fetch_symbol_news(symbol: str) -> pd.DataFrame:
    try:
        news_df = ak.stock_news_em(symbol=symbol)
    except Exception:
        return pd.DataFrame(columns=["代码", "新闻标题", "新闻内容", "发布时间"])
    if news_df is None or news_df.empty:
        return pd.DataFrame(columns=["代码", "新闻标题", "新闻内容", "发布时间"])
    news_df = news_df.copy()
    news_df["代码"] = str(symbol).zfill(6)
    return news_df[["代码", "新闻标题", "新闻内容", "发布时间"]]


def _score_financial_risk(row: pd.Series) -> List[str]:
    flags = []
    if row.get("净利润-同比增长", 0) < -20:
        flags.append("利润下滑")
    if row.get("营业总收入-同比增长", 0) < -10:
        flags.append("营收下滑")
    if row.get("每股经营现金流量", 0) < 0:
        flags.append("现金流偏弱")
    if row.get("净资产收益率", 0) < 0:
        flags.append("ROE为负")
    if row.get("市盈率-动态", 0) <= 0:
        flags.append("估值异常")
    return flags


def _build_risk_result(row: pd.Series, news_map: Dict[str, pd.DataFrame], notice_map: Dict[str, pd.DataFrame]) -> Dict[str, object]:
    code = row["代码"]
    risk_score = 0
    categories: List[str] = []
    details: List[str] = []
    for _, notice_row in notice_map.get(code, pd.DataFrame()).iterrows():
        for category in _find_hits(notice_row.get("公告标题", "")):
            risk_score += KEYWORD_WEIGHTS[category]
            categories.append(category)
            details.append(f"公告:{notice_row.get('公告标题', '')}")
    for _, news_row in news_map.get(code, pd.DataFrame()).head(20).iterrows():
        text = f"{news_row.get('新闻标题', '')} {news_row.get('新闻内容', '')}"
        for category in _find_hits(text):
            risk_score += KEYWORD_WEIGHTS[category]
            categories.append(category)
            details.append(f"新闻:{news_row.get('新闻标题', '')}")
    financial_flags = _score_financial_risk(row)
    risk_score += len(financial_flags)
    details.extend(financial_flags)
    unique_categories = sorted(set(categories))
    unique_details: List[str] = []
    for item in details:
        if item not in unique_details:
            unique_details.append(item)
    return {
        "risk_score": int(risk_score),
        "risk_flags": ",".join(unique_categories),
        "risk_reason": "；".join(unique_details[:5]) if unique_details else "未发现明显风险",
        "risk_pass": risk_score <= 2 and "财务造假" not in unique_categories and "监管处罚" not in unique_categories,
    }


def enrich_with_risk(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    working = df.copy()
    working["代码"] = working["代码"].astype(str).str.zfill(6)
    symbols = working["代码"].tolist()
    announcements = _fetch_recent_announcements(symbols)
    notice_map = {symbol: group.reset_index(drop=True) for symbol, group in announcements.groupby("代码")} if not announcements.empty else {}
    news_frames: List[pd.DataFrame] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        future_map = {executor.submit(_fetch_symbol_news, symbol): symbol for symbol in symbols}
        for future in as_completed(future_map):
            result = future.result()
            if not result.empty:
                news_frames.append(result)
    news_all = pd.concat(news_frames, ignore_index=True) if news_frames else pd.DataFrame(columns=["代码", "新闻标题", "新闻内容", "发布时间"])
    news_map = {symbol: group.sort_values(by="发布时间", ascending=False).reset_index(drop=True) for symbol, group in news_all.groupby("代码")} if not news_all.empty else {}
    risk_rows = [_build_risk_result(row, news_map, notice_map) for _, row in working.iterrows()]
    return pd.concat([working.reset_index(drop=True), pd.DataFrame(risk_rows)], axis=1)
