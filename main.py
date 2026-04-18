from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from data_fetcher import build_stock_dataset, build_top_summary, fetch_index_snapshot, format_fundamental_analysis, format_technical_analysis
from risk_check import enrich_with_risk
from strategy import PAGE_STRATEGY_MODES, select_stocks

OUTPUT_DIR = Path('outputs')
DATA_DIR = Path('data')
HISTORY_FILE = OUTPUT_DIR / 'strategy_history.json'
DASHBOARD_FILE = DATA_DIR / 'dashboard_data.json'


def ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_history() -> Dict[str, Any]:
    if not HISTORY_FILE.exists():
        return {'strategies': {}, 'updated_at': None}
    try:
        return json.loads(HISTORY_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {'strategies': {}, 'updated_at': None}


def save_history(history: Dict[str, Any]) -> None:
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding='utf-8')


def cutoff_date_str(days: int = 60) -> str:
    return (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')


def prune_history(history: Dict[str, Any], keep_days: int = 60) -> Dict[str, Any]:
    cutoff = cutoff_date_str(keep_days)
    for mode_name, by_date in list(history.setdefault('strategies', {}).items()):
        history['strategies'][mode_name] = {date_str: items for date_str, items in by_date.items() if date_str >= cutoff}
    return history


def collect_recent_history_codes(history: Dict[str, Any], keep_days: int = 60) -> List[str]:
    cutoff = cutoff_date_str(keep_days)
    codes = set()
    for by_date in history.get('strategies', {}).values():
        for date_str, items in by_date.items():
            if date_str < cutoff:
                continue
            for item in items:
                code = str(item.get('code', '')).zfill(6)
                if code:
                    codes.add(code)
    return sorted(codes)


def store_current_strategy_history(history: Dict[str, Any], run_date: str, strategy_results: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    strategies = history.setdefault('strategies', {})
    for mode_name, df in strategy_results.items():
        if mode_name not in PAGE_STRATEGY_MODES:
            continue
        records = []
        for _, row in df.iterrows():
            records.append({
                'code': str(row['代码']).zfill(6),
                'name': row['名称'],
                'strategy_tags': row.get('strategy_tags', ''),
                'selected_reason': row.get('选股理由', ''),
                'selected_score': float(row.get('strategy_score', 0) or 0),
                'selected_mode': row.get('strategy_mode', mode_name),
                'selected_rank': int(row.get('rank', 0) or 0),
            })
        strategies.setdefault(mode_name, {})[run_date] = records
    history['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return prune_history(history)


def build_latest_strategy_tag_map(strategy_results: Dict[str, pd.DataFrame]) -> Dict[str, List[str]]:
    tag_map: Dict[str, set[str]] = defaultdict(set)
    for df in strategy_results.values():
        if df.empty:
            continue
        for _, row in df.iterrows():
            code = str(row['代码']).zfill(6)
            for tag in str(row.get('strategy_tags', '')).split('|'):
                tag = tag.strip()
                if tag:
                    tag_map[code].add(tag)
            mode_tag = str(row.get('strategy_mode', '')).strip()
            if mode_tag:
                tag_map[code].add(mode_tag)
    return {code: sorted(tags) for code, tags in tag_map.items()}


def build_stock_detail_map(risk_df: pd.DataFrame, strategy_tag_map: Dict[str, List[str]]) -> Dict[str, Dict[str, Any]]:
    detail_map: Dict[str, Dict[str, Any]] = {}
    for _, row in risk_df.iterrows():
        code = str(row['代码']).zfill(6)
        risk_reason = str(row.get('risk_reason', '未发现明显风险')).strip() or '未发现明显风险'
        risk_items = [item.strip() for item in risk_reason.split('；') if item.strip()] or ['未发现明显风险']
        detail_map[code] = {
            'code': code,
            'name': row['名称'],
            'industry': row.get('所处行业', '') or row.get('行业', ''),
            'price': round(float(row.get('最新价', 0) or 0), 2),
            'pct_change': round(float(row.get('涨跌幅', 0) or 0), 2),
            'prev_pct_change': round(float(row.get('昨日涨跌幅', 0) or 0), 2),
            'prev2_pct_change': round(float(row.get('前日涨跌幅', 0) or 0), 2),
            'amount': round(float(row.get('成交额', 0) or 0), 2),
            'turnover_rate': round(float(row.get('换手率', 0) or 0), 2),
            'fundamental_analysis': format_fundamental_analysis(row),
            'technical_analysis': format_technical_analysis(row),
            'risk_score': int(row.get('risk_score', 0) or 0),
            'risk_summary': risk_reason,
            'risk_items': risk_items,
            'latest_strategy_tags': strategy_tag_map.get(code, []),
        }
    return detail_map


def _merge_item_with_latest(item: Dict[str, Any], latest_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    code = str(item.get('code', '')).zfill(6)
    latest = latest_map.get(code, {})
    latest_tags = latest.get('latest_strategy_tags') or []
    original_tags = [tag for tag in str(item.get('strategy_tags', '')).split('|') if tag]
    return {
        'code': code,
        'name': latest.get('name') or item.get('name', ''),
        'price': latest.get('price', 0),
        'pct_change': latest.get('pct_change', 0),
        'industry': latest.get('industry', ''),
        'prev_pct_change': latest.get('prev_pct_change', 0),
        'prev2_pct_change': latest.get('prev2_pct_change', 0),
        'fundamental_analysis': latest.get('fundamental_analysis', ''),
        'technical_analysis': latest.get('technical_analysis', ''),
        'strategy_tags': latest_tags if latest_tags else original_tags,
        'risk_score': latest.get('risk_score', 0),
        'risk_summary': latest.get('risk_summary', '未发现明显风险'),
        'risk_items': latest.get('risk_items', ['未发现明显风险']),
        'selected_reason': item.get('selected_reason', ''),
        'selected_rank': item.get('selected_rank', 0),
        'selected_mode': item.get('selected_mode', ''),
    }


def build_strategy_sections(history: Dict[str, Any], latest_map: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    sections: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for mode_name in PAGE_STRATEGY_MODES:
        sections[mode_name] = {}
        for date_str, items in sorted(history.get('strategies', {}).get(mode_name, {}).items(), reverse=True):
            sections[mode_name][date_str] = [_merge_item_with_latest(item, latest_map) for item in items]
    return sections


def build_recommendation_section(history_sections: Dict[str, Dict[str, List[Dict[str, Any]]]]) -> Dict[str, List[Dict[str, Any]]]:
    recommendations: Dict[str, List[Dict[str, Any]]] = {}
    all_dates = sorted({date_str for section in history_sections.values() for date_str in section.keys()}, reverse=True)
    for date_str in all_dates:
        by_code: Dict[str, Dict[str, Any]] = {}
        for section in history_sections.values():
            for item in section.get(date_str, []):
                code = item['code']
                if code not in by_code:
                    by_code[code] = {**item, 'strategy_tags': list(item.get('strategy_tags', []))}
                else:
                    by_code[code]['strategy_tags'] = sorted(set(by_code[code]['strategy_tags']) | set(item.get('strategy_tags', [])))
        picked = [item for item in by_code.values() if item.get('pct_change', 0) < 0 and item.get('prev_pct_change', 0) < 0 and item.get('prev2_pct_change', 0) < 0]
        picked.sort(key=lambda row: (row.get('pct_change', 0), row.get('prev_pct_change', 0), row.get('prev2_pct_change', 0)))
        recommendations[date_str] = picked[:30]
    return recommendations


def build_hotspot_section(risk_df: pd.DataFrame) -> List[Dict[str, Any]]:
    if risk_df.empty or '所处行业' not in risk_df.columns:
        return []
    grouped = risk_df.fillna({'所处行业': '未知行业'}).groupby('所处行业', dropna=False).agg(stock_count=('代码', 'count'), avg_pct=('涨跌幅', 'mean'), total_amount=('成交额', 'sum')).reset_index()
    grouped['heat_score'] = grouped['stock_count'] * 2 + grouped['avg_pct'] * 3 + grouped['total_amount'] / 100000000 * 0.08
    grouped = grouped.sort_values(by=['heat_score', 'total_amount'], ascending=[False, False]).head(10)
    return [{'name': row['所处行业'], 'heat_score': round(float(row['heat_score']), 2), 'avg_pct': round(float(row['avg_pct']), 2), 'total_amount': round(float(row['total_amount']) / 100000000, 2), 'stock_count': int(row['stock_count'])} for _, row in grouped.iterrows()]


def build_markdown_report(run_date: str, strategy_results: Dict[str, pd.DataFrame]) -> str:
    lines = [f'# 每日股票池 - {run_date}', '']
    for mode_name in PAGE_STRATEGY_MODES:
        lines.append(f'## {mode_name}')
        df = strategy_results.get(mode_name, pd.DataFrame())
        if df.empty:
            lines.extend(['', '今日无结果。', ''])
            continue
        preview = df[['代码', '名称', '最新价', 'strategy_tags', 'strategy_score', '选股理由']].head(10)
        lines.extend(['', preview.to_markdown(index=False), ''])
    return '\n'.join(lines)


def main() -> None:
    ensure_dirs()
    history = prune_history(load_history())
    dataset, spot_df = build_stock_dataset(extra_codes=collect_recent_history_codes(history))
    if dataset.empty:
        raise RuntimeError('未获取到可用股票数据，请检查免费数据源和接口是否可访问。')
    analysis_universe = dataset.sort_values(by=['coarse_score', '成交额', '换手率'], ascending=[False, False, False]).head(450)
    risk_df = enrich_with_risk(analysis_universe)
    strategy_results: Dict[str, pd.DataFrame] = {mode_name: select_stocks(risk_df, mode=mode_name) for mode_name in PAGE_STRATEGY_MODES + ['quality_growth']}
    run_date = datetime.now().strftime('%Y-%m-%d')
    history = store_current_strategy_history(history, run_date, strategy_results)
    save_history(history)
    strategy_tag_map = build_latest_strategy_tag_map(strategy_results)
    latest_map = build_stock_detail_map(risk_df, strategy_tag_map)
    history_sections = build_strategy_sections(history, latest_map)
    dashboard_data = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'calendar_date': datetime.now().strftime('%Y年%m月%d日'),
        'indices': fetch_index_snapshot(),
        'market_summary': build_top_summary(spot_df),
        'available_dates': sorted({date_str for section in history_sections.values() for date_str in section.keys()}, reverse=True),
        'sections': {
            'limit_up_pullback': history_sections.get('limit_up_pullback', {}),
            'low_absorption': history_sections.get('low_absorption', {}),
            'graphic_pattern': history_sections.get('graphic_pattern', {}),
            'recommendations': build_recommendation_section(history_sections),
            'hotspots': build_hotspot_section(risk_df),
        },
    }
    DASHBOARD_FILE.write_text(json.dumps(dashboard_data, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUTPUT_DIR / 'latest_stock_pool.md').write_text(build_markdown_report(run_date, strategy_results), encoding='utf-8')
    print(f'页面数据生成完成: {DASHBOARD_FILE.as_posix()}')


if __name__ == '__main__':
    main()
