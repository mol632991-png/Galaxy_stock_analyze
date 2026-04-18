from __future__ import annotations

from typing import Callable, Dict, List, Set

import pandas as pd

PAGE_STRATEGY_MODES = ['limit_up_pullback', 'low_absorption', 'graphic_pattern']
MODE_ALIASES = {'base': 'quality_growth', 'original': 'quality_growth', 'limit_up': 'limit_up_pullback', 'low_absorb': 'low_absorption', 'graphic': 'graphic_pattern'}
BASE_CONFIG: Dict[str, float] = {'min_price': 5.0, 'min_turnover_rate': 0.8, 'min_amount': 80_000_000, 'max_risk_score': 3.0, 'top_n': 40}


def _normalize_modes(mode: str) -> List[str]:
    raw = [item.strip() for item in mode.split(',') if item.strip()]
    if not raw:
        return ['quality_growth']
    normalized: List[str] = []
    for item in raw:
        item = MODE_ALIASES.get(item, item)
        if item == 'all':
            return ['quality_growth', 'limit_up_pullback', 'low_absorption', 'graphic_pattern']
        normalized.append(item)
    result: List[str] = []
    seen: Set[str] = set()
    for item in normalized:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _is_main_board(code: str) -> bool:
    code = str(code)
    return code.startswith(('600', '601', '603', '605', '000', '001', '002', '003', '004', '005'))


def _is_not_st(name: str) -> bool:
    upper_name = str(name).upper()
    return ('ST' not in upper_name) and ('*ST' not in upper_name) and (not upper_name.startswith('S'))


def _base_filter(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    working['代码'] = working['代码'].astype(str).str.zfill(6)
    working['非ST'] = working['名称'].apply(_is_not_st)
    working['主板'] = working['代码'].apply(_is_main_board)
    return working[(working['risk_pass'] == True) & working['非ST'] & (working['最新价'] >= BASE_CONFIG['min_price']) & (working['换手率'] >= BASE_CONFIG['min_turnover_rate']) & (working['成交额'] >= BASE_CONFIG['min_amount']) & (working['risk_score'] <= BASE_CONFIG['max_risk_score'])].copy()


def _finalize(df: pd.DataFrame, mode_name: str, tag_builder: Callable[[pd.Series], str], reason_builder: Callable[[pd.Series], str]) -> pd.DataFrame:
    if df.empty:
        return df
    working = df.copy()
    working['strategy_mode'] = mode_name
    working['strategy_tags'] = working.apply(tag_builder, axis=1)
    working['选股理由'] = working.apply(reason_builder, axis=1)
    working['风险摘要'] = working['risk_reason'].fillna('未发现明显风险')
    return working


def _select_quality_growth(df: pd.DataFrame) -> pd.DataFrame:
    working = _base_filter(df)
    working = working[working['主板'] & (working['市盈率-动态'] > 0) & (working['市盈率-动态'] <= 45) & (working['市净率'] > 0) & (working['市净率'] <= 6) & (working['销售毛利率'] >= 15) & (working['最新价'] > working['ma20']) & (working['ma20'] > working['ma60']) & (working['rsi14'].between(50, 75)) & (working['成交额均线比'] >= 1.0)].copy()
    if working.empty:
        return working
    working['strategy_score'] = (((working['最新价'] / working['ma20'] - 1.0) * 100) * 0.30 + ((working['ma20'] / working['ma60'] - 1.0) * 100) * 0.20 + working['净资产收益率'] * 0.40 + working['营业总收入-同比增长'] * 0.20 + working['净利润-同比增长'] * 0.25 + working['成交额均线比'] * 8 - working['risk_score'] * 12).round(2)
    return _finalize(working, 'quality_growth', lambda _: '基本面趋势', lambda _: '均线多头、盈利能力和成长性较好，量能配合且风险较低。')


def _select_limit_up_pullback(df: pd.DataFrame) -> pd.DataFrame:
    working = _base_filter(df)
    working['支撑线80'] = working['low_120'] + (working['high_120'] - working['low_120']) * 0.8
    working = working[working['主板'] & (working['上市天数'] > 250) & (working['最新价'] > 5) & (working['涨跌幅'] > 9) & (working['最新价'] < working['支撑线80'])].copy()
    if working.empty:
        return working
    working['strategy_score'] = (((working['涨跌幅'] - 9) * 12) + (working['支撑线80'] - working['最新价']).clip(lower=0) * 2.5 + working['换手率'] * 0.60 + working['成交额'] / 100_000_000 * 0.50 - working['risk_score'] * 10).round(2)
    return _finalize(working, 'limit_up_pullback', lambda _: '涨停选股', lambda _: '涨停强势、主板、上市满一年，且价格位于120日区间80%压制线下方。')


def _low_absorption_tag(row: pd.Series) -> str:
    tags: List[str] = ['低吸潜伏']
    if row['signal_fund_flow']:
        tags.append('资金流')
    if row['signal_upward_10d']:
        tags.append('近10日上扬')
    if row['signal_short_buy_20d']:
        tags.append('20日短买')
    if row['signal_hourly_60_3pct']:
        tags.append('60分钟3%')
    return '|'.join(tags)


def _select_low_absorption(df: pd.DataFrame) -> pd.DataFrame:
    working = _base_filter(df)
    working['黄金强势分割线'] = working['hour_low_120'] + (working['hour_high_120'] - working['hour_low_120']) * 0.26
    working['公式命中数'] = working['signal_fund_flow'].astype(int) + working['signal_upward_10d'].astype(int) + working['signal_short_buy_20d'].astype(int) + working['signal_hourly_60_3pct'].astype(int)
    working = working[working['主板'] & (working['最新价'] > 27) & (working['最新价'] < working['黄金强势分割线']) & (working['公式命中数'] >= 1)].copy()
    if working.empty:
        return working
    working['strategy_score'] = (working['公式命中数'] * 28 + working['fund_flow_ratio'].fillna(0) * 5 + (working['黄金强势分割线'] - working['最新价']).clip(lower=0) * 2 + working['换手率'] * 0.50 + working['成交额'] / 100_000_000 * 0.30 - working['risk_score'] * 10).round(2)
    return _finalize(working, 'low_absorption', _low_absorption_tag, lambda _: '多套低吸信号共振，主板、股价大于27元，且位于60分钟黄金强势分割线下方。')


def _graphic_pattern_tag(row: pd.Series) -> str:
    tags: List[str] = ['图形选股']
    if row['main_buy_signal']:
        tags.append('主图买点')
    if row['main_trial_signal']:
        tags.append('试盘试买')
    if row['short_buy_signal']:
        tags.append('短买')
    if row['build_position_signal']:
        tags.append('建仓')
    if row['shape_similarity']:
        tags.append('走势相似')
    return '|'.join(tags)


def _select_graphic_pattern(df: pd.DataFrame) -> pd.DataFrame:
    working = _base_filter(df)
    working = working[working['非ST'] & working['主板'] & (working['最新价'] > 27) & working['shape_similarity'] & (working['main_buy_signal'] | working['main_trial_signal']) & (working['short_buy_signal'] | working['build_position_signal'])].copy()
    if working.empty:
        return working
    zone_score = pd.Series(0.0, index=working.index)
    zone_score += working['close_to_low_zone'].astype(int) * 15
    zone_score += (((working['最新价'] >= working['fib_618'] * 0.97) & (working['最新价'] <= working['fib_809'] * 1.03)).astype(int) * 15)
    working['strategy_score'] = (working['main_buy_signal'].astype(int) * 22 + working['main_trial_signal'].astype(int) * 10 + working['short_buy_signal'].astype(int) * 20 + working['build_position_signal'].astype(int) * 15 + working['shape_similarity'].astype(int) * 20 + zone_score + working['drawdown_ratio'].clip(lower=10, upper=60) * 0.60 + working['换手率'] * 0.40 + working['成交额'] / 100_000_000 * 0.40 - working['risk_score'] * 10).round(2)
    return _finalize(working, 'graphic_pattern', _graphic_pattern_tag, lambda _: '主图买点与副图短买/建仓共振，同时走势接近下跌后低位筑底修复形态。')


STRATEGY_HANDLERS = {'quality_growth': _select_quality_growth, 'limit_up_pullback': _select_limit_up_pullback, 'low_absorption': _select_low_absorption, 'graphic_pattern': _select_graphic_pattern}


def select_stocks(df: pd.DataFrame, mode: str = 'quality_growth') -> pd.DataFrame:
    outputs: List[pd.DataFrame] = []
    for mode_name in _normalize_modes(mode):
        result = STRATEGY_HANDLERS[mode_name](df)
        if not result.empty:
            outputs.append(result)
    if not outputs:
        return pd.DataFrame(columns=list(df.columns) + ['rank', 'strategy_mode', 'strategy_tags', 'strategy_score', '选股理由', '风险摘要'])
    merged = pd.concat(outputs, ignore_index=True)
    merged = merged.sort_values(by=['strategy_score', '成交额', '换手率'], ascending=[False, False, False]).head(int(BASE_CONFIG['top_n']))
    merged = merged.reset_index(drop=True)
    merged.insert(0, 'rank', range(1, len(merged) + 1))
    return merged
