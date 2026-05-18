#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文京区 一棟アパート モニター v1.0
実行するとHTMLレポートを自動生成してブラウザで開きます

使い方:
  python3 monitor.py
"""

import requests
from lxml import html as lxml_html
import json, os, re, time, hashlib, subprocess
from datetime import date, datetime

# ===========================================================
# 設定
# ===========================================================

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'ja,en-US;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

SITES = {
    'rakumachi': {
        'name': '楽待',
        'url': 'https://www.rakumachi.jp/syuuekibukken/area/prefecture/dimAll/?area%5B%5D=13105&dim%5B%5D=1002&kakaku_max=30000',
        'base_url': 'https://www.rakumachi.jp',
    },
    'kenbiya': {
        'name': '健美家',
        'url': 'https://www.kenbiya.com/pp2/s/tokyo/bunkyo-ku/',
        'base_url': 'https://www.kenbiya.com',
    },
    'athome': {
        'name': 'アットホーム',
        'url': 'https://www.athome.co.jp/buy_other/tokyo/bunkyo-city/list/',
        'base_url': 'https://www.athome.co.jp',
    },
}

TARGET_STATIONS = ['千石', '白山', '本駒込', '東大前', '茗荷谷', '新大塚', '巣鴨']
MAX_PRICE_MAN = 30000  # 3億円 = 30000万円

BASE_DIR  = os.path.expanduser('~/Downloads/property_monitor')
DATA_DIR  = os.path.join(BASE_DIR, 'data')
REPORT_DIR = os.path.join(BASE_DIR, 'reports')
HISTORY_FILE = os.path.join(DATA_DIR, 'history.json')

os.makedirs(DATA_DIR,   exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

# ===========================================================
# ユーティリティ
# ===========================================================

def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        r.encoding = r.apparent_encoding
        return r.text
    except Exception as e:
        print(f'  ⚠️  取得エラー ({url[:60]}…): {e}')
        return None

def to_man(text):
    """「X億Y,ZZZ万円」「X億Y千万円」「X,XXX万円」→ 万円の整数"""
    if not text:
        return None
    t = text.replace(' ', '').replace('\n', '')
    # 「X億Y,ZZZ万」or「X億YZZZ万」例: 1億8600万, 2億5,000万
    m = re.search(r'(\d+)億(\d[\d,]+)万', t)
    if m:
        return int(m.group(1)) * 10000 + int(m.group(2).replace(',', ''))
    # 「X億Y千万」例: 1億8千万 → 18000万
    m = re.search(r'(\d+)億(\d+)千万', t)
    if m:
        return int(m.group(1)) * 10000 + int(m.group(2)) * 1000
    # 「X億円」のみ
    m = re.search(r'(\d+)億', t)
    if m:
        return int(m.group(1)) * 10000
    # 「X,XXX万円」例: 9,900万
    m = re.search(r'(\d{1,3}),(\d{3})万', t)
    if m:
        return int(m.group(1)) * 1000 + int(m.group(2))
    # 「XXXX万円」
    m = re.search(r'(\d+)万', t)
    if m:
        return int(m.group(1))
    return None

def to_yield(text):
    if not text:
        return None
    m = re.search(r'(\d+\.\d+)\s*%', text)
    return float(m.group(1)) if m else None

def to_walk(text):
    if not text:
        return None
    m = re.search(r'徒歩\s*(\d+)\s*分', text)
    return int(m.group(1)) if m else None

def to_year(text):
    if not text:
        return None
    m = re.search(r'(\d{4})\s*年', text)
    if m:
        return int(m.group(1))
    m = re.search(r'築\s*(\d+)\s*年', text)
    if m:
        return datetime.now().year - int(m.group(1))
    return None

def to_area(text):
    if not text:
        return None
    m = re.search(r'([\d,]+\.?\d*)\s*[㎡m²]', text)
    return float(m.group(1).replace(',', '')) if m else None

def normalize(text):
    """全角数字・英字を半角に正規化"""
    if not text:
        return text
    result = ''
    for c in text:
        code = ord(c)
        if 0xFF01 <= code <= 0xFF5E:   # 全角英数記号 → 半角
            result += chr(code - 0xFEE0)
        elif c == '　':            # 全角スペース → 半角
            result += ' '
        else:
            result += c
    return result

def prop_id(location, price):
    key = f'{normalize(location)}_{price}'
    return hashlib.md5(key.encode()).hexdigest()[:8]

def extract_from_container(container_el, link_url, site_name):
    """lxml要素からテキストを取得し物件データを抽出"""
    text = ' '.join(container_el.text_content().split())

    price = to_man(text)
    if not price or price > MAX_PRICE_MAN:
        return None

    yield_rate = to_yield(text)
    walk_min   = to_walk(text)
    built_year = to_year(text)
    new_quake  = (built_year >= 1981) if built_year else None

    sm = re.search(r'([^\s　、。（(]+?駅)', text)
    station = sm.group(1) if sm else None

    areas = re.findall(r'([\d,]+\.?\d*)\s*[㎡m²]', text)
    land_area     = float(areas[0].replace(',','')) if len(areas) > 0 else None
    building_area = float(areas[1].replace(',','')) if len(areas) > 1 else None

    um = re.search(r'(\d+)\s*戸', text)
    units = int(um.group(1)) if um else None

    # 「東京都文京区XX丁目」の形式を優先、次に「文京区XX丁目」
    lm = re.search(r'東京都文京区([^\s　　、。（(]+)', text)
    if not lm:
        lm = re.search(r'文京区([一-龥ぁ-ん\d]+[丁目町番][\d\-]*)', text)
    location = ('文京区' + lm.group(1)) if lm else '文京区（詳細不明）'

    structure = None
    for s in ['RC造', '鉄骨造', '木造', '軽量鉄骨', '鉄筋コンクリート']:
        if s in text:
            structure = s
            break

    return {
        'id':            prop_id(location, price),
        'location':      location,
        'station':       station,
        'walk_min':      walk_min,
        'price':         price,
        'yield_rate':    yield_rate,
        'built_year':    built_year,
        'new_quake':     new_quake,
        'units':         units,
        'land_area':     land_area,
        'building_area': building_area,
        'structure':     structure,
        'sources':       {site_name: link_url},
    }

# ===========================================================
# 各サイトのスクレイパー
# ===========================================================

def scrape_rakumachi():
    """楽待: div.propertyBlock を物件カード単位で処理"""
    print('  📡 楽待を巡回中...')
    page = fetch(SITES['rakumachi']['url'])
    if not page:
        return []
    tree = lxml_html.fromstring(page)
    results = []
    # 文京区の物件ブロックのみ（dim1002リンクを含むもの）
    for block in tree.xpath('//div[@class="propertyBlock"]'):
        hrefs = block.xpath('.//a[contains(@href,"/dim1002/")]/@href')
        if not hrefs:
            continue
        href = hrefs[0]
        url = SITES['rakumachi']['base_url'] + href if href.startswith('/') else href
        prop = extract_from_container(block, url, '楽待')
        if prop:
            results.append(prop)
            print(f'    ✓ {prop["location"]}  {_fmt_price(prop["price"])}')
    return results

def scrape_kenbiya():
    """健美家: re_リンクの直近の親要素を物件カードとして処理"""
    print('  📡 健美家を巡回中...')
    page = fetch(SITES['kenbiya']['url'])
    if not page:
        return []
    tree = lxml_html.fromstring(page)
    results, seen = [], set()
    for a in tree.xpath('//a[contains(@href,"/re_")]'):
        href = a.get('href', '')
        if not href or href in seen:
            continue
        seen.add(href)
        url = SITES['kenbiya']['base_url'] + href if href.startswith('/') else href
        # 親要素を辿って価格テキストを含む最小コンテナを取得
        parent = a.getparent()
        el = parent if parent is not None else a
        prop = extract_from_container(el, url, '健美家')
        if prop:
            results.append(prop)
            print(f'    ✓ {prop["location"]}  {_fmt_price(prop["price"])}')
    return results

def scrape_athome():
    """アットホーム: ボット保護のため自動取得不可 → 既知データをそのまま返す"""
    print('  📡 アットホーム: ボット保護のため自動巡回をスキップ（手動確認推奨）')
    print(f'     手動確認URL: {SITES["athome"]["url"]}')
    return []  # JavaScript保護のため自動スクレイピング不可

# ===========================================================
# データ処理
# ===========================================================

def merge(props):
    """重複除去・統合（同一物件は複数サイトのURLをまとめる）"""
    merged = {}
    for p in props:
        pid = p['id']
        if pid in merged:
            merged[pid]['sources'].update(p['sources'])
        else:
            merged[pid] = p
    return list(merged.values())

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, encoding='utf-8') as f:
            return json.load(f)
    return {'snapshots': []}

def save_history(h):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(h, f, ensure_ascii=False, indent=2)

def evaluate(prop):
    """物件評価 A / B+ / B / C / D"""
    if prop.get('new_quake') is False:
        return 'D', ['旧耐震（融資困難）']
    score, notes = 0, []
    yr = prop.get('yield_rate')
    if yr:
        if yr >= 4.5:   score += 3
        elif yr >= 4.0: score += 2
        elif yr >= 3.5: score += 1
        else: notes.append(f'利回り低め({yr}%)')
    else:
        score += 1; notes.append('利回り不明')
    wm = prop.get('walk_min')
    if wm:
        if wm <= 5:    score += 3
        elif wm <= 7:  score += 2
        elif wm <= 10: score += 1
        else: notes.append(f'駅から遠め({wm}分)')
    u = prop.get('units')
    if u:
        if u >= 8:   score += 2
        elif u >= 4: score += 1
        else: notes.append(f'戸数少なめ({u}戸)')
    if any(s in (prop.get('station') or '') for s in TARGET_STATIONS):
        score += 1
    grade = 'A' if score >= 8 else 'B+' if score >= 6 else 'B' if score >= 4 else 'C' if score >= 2 else 'D'
    return grade, notes

# ===========================================================
# HTMLレポート生成
# ===========================================================

def _fmt_price(p):
    if not p:
        return '―'
    if p >= 10000:
        o, m = divmod(p, 10000)
        return f'{o}億{m:,}万円' if m else f'{o}億円'
    return f'{p:,}万円'

def _grade_class(g):
    return {'A':'#27ae60','B+':'#2980b9','B':'#3498db','C':'#e67e22','D':'#e74c3c'}.get(g,'#999')

# エリア定義（駅名 → エリアラベル）
AREA_MAP = {
    '千石': '千石エリア', '巣鴨': '千石エリア',
    '白山': '白山エリア', '本駒込': '白山エリア',
    '新大塚': '大塚エリア',
    '茗荷谷': '小石川エリア', '東大前': '小石川エリア',
}
AREA_COLORS = {
    '千石エリア':  '#2980b9',
    '白山エリア':  '#27ae60',
    '大塚エリア':  '#e67e22',
    '小石川エリア':'#8e44ad',
    'その他':     '#95a5a6',
}

def get_area(prop):
    st = prop.get('station') or ''
    for key, label in AREA_MAP.items():
        if key in st:
            return label
    return 'その他'

def generate_report(properties, prev_snap, history, today_str):
    snaps = history.get('snapshots', [])

    # 前回との差分（prev_snapは保存前の最終スナップショット）
    prev_ids  = set(prev_snap['property_ids']) if prev_snap else set()
    curr_ids  = {p['id'] for p in properties}
    new_ids   = curr_ids - prev_ids
    gone_ids  = prev_ids - curr_ids

    # 評価・エリア付与
    for p in properties:
        p['grade'], p['grade_notes'] = evaluate(p)
        p['area'] = get_area(p)
    properties.sort(key=lambda x: x.get('price') or 999999)

    # 集計
    prices = [p['price']      for p in properties if p.get('price')]
    yields = [p['yield_rate'] for p in properties if p.get('yield_rate')]
    avg_p  = round(sum(prices)/len(prices)) if prices else 0
    avg_y  = round(sum(yields)/len(yields), 2) if yields else 0

    # トレンドデータ（直近12週）
    all_snaps = snaps[-12:]
    t_dates  = json.dumps([s['date'] for s in all_snaps])
    t_counts = json.dumps([s['count'] for s in all_snaps])
    t_prices = json.dumps([round(s.get('avg_price', 0)) for s in all_snaps])
    t_yields = json.dumps([round(s.get('avg_yield', 0), 2) for s in all_snaps])

    # ── ヘルパー関数 ──────────────────────────────
    def v(p, k, suffix=''):
        val = p.get(k)
        return f'{val}{suffix}' if val is not None else '―'

    def links_html(p):
        return ' '.join(
            f'<a href="{u}" target="_blank" class="site-btn">{n}</a>'
            for n, u in p.get('sources', {}).items()
        )

    def badge(p):
        return '<span class="badge-new">NEW</span>' if p['id'] in new_ids else ''

    def quake_str(p):
        if p.get('new_quake') is True:  return '✅新耐震'
        if p.get('new_quake') is False: return '⚠️旧耐震'
        return '―'

    # ── Tab1: 物件一覧 ──────────────────────────────
    def make_row(p):
        gc = _grade_class(p['grade'])
        ac = AREA_COLORS.get(p['area'], '#999')
        return (
            f'<tr>'
            f'<td><span style="color:{ac};font-size:.7rem">●</span> {p.get("location","―")}{badge(p)}</td>'
            f'<td>{p.get("station","―")}</td>'
            f'<td class="tc">{v(p,"walk_min","分")}</td>'
            f'<td class="price-col">{_fmt_price(p.get("price"))}</td>'
            f'<td class="tc">{v(p,"yield_rate","%")}</td>'
            f'<td class="tc">{v(p,"built_year","年")}</td>'
            f'<td class="tc">{quake_str(p)}</td>'
            f'<td class="tc">{v(p,"units","戸")}</td>'
            f'<td class="tc">{v(p,"land_area","㎡")}</td>'
            f'<td class="tc">{v(p,"building_area","㎡")}</td>'
            f'<td class="tc">{v(p,"structure")}</td>'
            f'<td class="tc" style="font-weight:700;color:{gc}">{p["grade"]}</td>'
            f'<td>{links_html(p)}</td>'
            f'</tr>'
        )
    list_rows = '\n'.join(make_row(p) for p in properties)

    # ── Tab2: エリア別 ──────────────────────────────
    areas = {}
    for p in properties:
        areas.setdefault(p['area'], []).append(p)

    area_sections = []
    for area_name, aps in sorted(areas.items()):
        ac = AREA_COLORS.get(area_name, '#999')
        arows = '\n'.join(make_row(p) for p in aps)
        avg_ap = round(sum(p['price'] for p in aps if p.get('price')) / len(aps)) if aps else 0
        avg_ay = round(sum(p['yield_rate'] for p in aps if p.get('yield_rate')) / max(1, len([p for p in aps if p.get('yield_rate')])), 2)
        area_sections.append(f'''
        <div class="mb-4">
          <h4 style="color:{ac};border-left:4px solid {ac};padding-left:.6rem">
            {area_name}
            <small class="text-muted ms-2" style="font-size:.8rem">{len(aps)}件 ／ 平均{_fmt_price(avg_ap)} ／ 平均利回り{avg_ay}%</small>
          </h4>
          <div class="table-responsive">
            <table class="table table-sm table-bordered table-hover">
              <thead><tr>
                <th>所在地</th><th>最寄り駅</th><th>徒歩</th><th>価格</th>
                <th>利回り</th><th>築年</th><th>耐震</th><th>戸数</th>
                <th>土地</th><th>建物</th><th>構造</th><th>評価</th><th>リンク</th>
              </tr></thead>
              <tbody>{arows}</tbody>
            </table>
          </div>
        </div>''')
    area_html = '\n'.join(area_sections)

    # ── Tab3: 推移グラフ ──────────────────────────────
    has_trend = len(all_snaps) >= 2
    trend_note = '' if has_trend else '<p class="text-muted">データが2週分以上蓄積されるとグラフが表示されます。</p>'

    # エリア別件数推移（スナップショットの物件をエリア分類）
    area_trend_js = ''
    if has_trend:
        area_labels = list(AREA_COLORS.keys())
        area_datasets = []
        for al in area_labels:
            color = AREA_COLORS[al]
            counts = []
            for s in all_snaps:
                cnt = sum(1 for p in s.get('properties', [])
                          if get_area(p) == al)
                counts.append(cnt)
            if any(c > 0 for c in counts):
                area_datasets.append(
                    f'{{"label":"{al}","data":{json.dumps(counts)},"borderColor":"{color}",'
                    f'"backgroundColor":"{color}22","tension":0.3,"fill":false}}'
                )
        area_ds_js = '[' + ','.join(area_datasets) + ']'
        area_trend_js = f'''
        new Chart(document.getElementById("c4"),{{
          type:"line",
          data:{{labels:{t_dates},datasets:{area_ds_js}}},
          options:{{responsive:true,maintainAspectRatio:false,
            plugins:{{title:{{display:true,text:"エリア別掲載件数推移"}}}}}}
        }});'''

    # ── Tab4: 消滅物件アラート ──────────────────────────────
    gone_items_html = ''
    if gone_ids and prev_snap:
        prev_map = {p['id']: p for p in prev_snap.get('properties', [])}
        gone_list = [prev_map[i] for i in gone_ids if i in prev_map]
        if gone_list:
            gone_rows = ''.join(
                f'<tr><td>{p.get("location","不明")}</td><td>{_fmt_price(p.get("price"))}</td>'
                f'<td>{p.get("station","")}</td><td>{p.get("walk_min","―")}分</td>'
                f'<td>{p.get("yield_rate","―")}%</td></tr>'
                for p in gone_list
            )
            gone_items_html = f'''
            <div class="alert alert-danger">
              <strong>🔴 消滅物件（{len(gone_list)}件）</strong> — 成約・掲載終了の可能性
              <table class="table table-sm table-bordered mt-2 mb-0 bg-white">
                <thead><tr><th>所在地</th><th>価格</th><th>駅</th><th>徒歩</th><th>利回り</th></tr></thead>
                <tbody>{gone_rows}</tbody>
              </table>
            </div>'''

    new_items_html = ''
    if new_ids:
        new_props = [p for p in properties if p['id'] in new_ids]
        new_rows = ''.join(
            f'<tr><td>{p.get("location","不明")}{badge(p)}</td><td>{_fmt_price(p.get("price"))}</td>'
            f'<td>{p.get("station","")}</td><td>{p.get("walk_min","―")}分</td>'
            f'<td>{p.get("yield_rate","―") if p.get("yield_rate") else "―"}%</td>'
            f'<td>{links_html(p)}</td></tr>'
            for p in new_props
        )
        new_items_html = f'''
        <div class="alert alert-success">
          <strong>🟢 新着物件（{len(new_ids)}件）</strong>
          <table class="table table-sm table-bordered mt-2 mb-0 bg-white">
            <thead><tr><th>所在地</th><th>価格</th><th>駅</th><th>徒歩</th><th>利回り</th><th>リンク</th></tr></thead>
            <tbody>{new_rows}</tbody>
          </table>
        </div>'''

    # ── 評価行 ──────────────────────────────
    def eval_row(p):
        gc    = _grade_class(p['grade'])
        notes = '・'.join(p.get('grade_notes') or ['問題なし'])
        return (f'<tr><td>{p.get("location","―")}</td>'
                f'<td style="font-weight:700;color:{gc}">{p["grade"]}</td>'
                f'<td>{notes}</td>'
                f'<td>{links_html(p)}</td></tr>')
    eval_rows = '\n'.join(eval_row(p) for p in properties)

    # ── HTML組み立て ──────────────────────────────
    html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>文京区 物件モニター {today_str}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  body{{font-family:"Hiragino Sans","Helvetica Neue",Arial,sans-serif;background:#f4f6f9;font-size:.9rem}}
  .top-bar{{background:linear-gradient(135deg,#1a3c5e,#2d6a9f);color:#fff;padding:1.2rem 0}}
  .stat-card{{background:#fff;border-radius:10px;padding:1rem;box-shadow:0 2px 6px rgba(0,0,0,.08);text-align:center}}
  .stat-n{{font-size:1.6rem;font-weight:700;color:#1a3c5e}}
  .stat-l{{color:#888;font-size:.8rem}}
  .tab-content{{background:#fff;border:1px solid #dee2e6;border-top:none;border-radius:0 0 10px 10px;padding:1.5rem}}
  .nav-tabs .nav-link{{color:#555}}
  .nav-tabs .nav-link.active{{font-weight:600;color:#1a3c5e}}
  table th{{background:#1a3c5e;color:#fff;white-space:nowrap;font-size:.78rem}}
  table td{{font-size:.78rem;vertical-align:middle}}
  .tc{{text-align:center}}
  .price-col{{font-weight:600;color:#1a3c5e;white-space:nowrap}}
  .badge-new{{background:#27ae60;color:#fff;padding:1px 5px;border-radius:3px;font-size:.7rem;margin-left:4px}}
  .site-btn{{font-size:.72rem;padding:1px 5px;background:#eee;border-radius:3px;text-decoration:none;color:#333;margin:1px;display:inline-block}}
  .site-btn:hover{{background:#1a3c5e;color:#fff}}
  h3{{color:#1a3c5e;font-size:1rem;margin-bottom:1rem}}
  .bookmark-tip{{background:#fff8e1;border:1px solid #ffc107;border-radius:6px;padding:.6rem 1rem;font-size:.82rem;margin-bottom:1rem}}
</style>
</head>
<body>

<div class="top-bar">
  <div class="container">
    <h1 class="h4 mb-0">🏢 文京区 一棟アパート モニター</h1>
    <small class="opacity-75">巡回日: {today_str} ｜ 3億円以下 ｜ 楽待・健美家</small>
  </div>
</div>

<div class="container mt-3">

  <!-- ブックマーク案内 -->
  <div class="bookmark-tip">
    📌 このページは <strong>latest.html</strong> としても保存されています。ブックマーク登録しておけば、次回実行後にブラウザを更新するだけで最新情報に切り替わります。
  </div>

  <!-- 統計カード -->
  <div class="row g-3 mb-3">
    <div class="col-6 col-md-3"><div class="stat-card"><div class="stat-n">{len(properties)}</div><div class="stat-l">掲載件数</div></div></div>
    <div class="col-6 col-md-3"><div class="stat-card"><div class="stat-n" style="color:#27ae60">{len(new_ids)}</div><div class="stat-l">新着</div></div></div>
    <div class="col-6 col-md-3"><div class="stat-card"><div class="stat-n">{_fmt_price(avg_p)}</div><div class="stat-l">平均価格</div></div></div>
    <div class="col-6 col-md-3"><div class="stat-card"><div class="stat-n">{avg_y}%</div><div class="stat-l">平均利回り</div></div></div>
  </div>

  <!-- タブ -->
  <ul class="nav nav-tabs" id="mainTab">
    <li class="nav-item"><button class="nav-link active" data-bs-toggle="tab" data-bs-target="#tab-list">📋 物件一覧</button></li>
    <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#tab-area">🗺️ エリア別</button></li>
    <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#tab-trend">📈 推移グラフ</button></li>
    <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#tab-eval">⭐ 評価</button></li>
    <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#tab-alert">🔔 更新情報</button></li>
  </ul>

  <div class="tab-content" id="mainTabContent">

    <!-- 物件一覧 -->
    <div class="tab-pane fade show active" id="tab-list">
      <h3>全物件一覧（価格順）</h3>
      <div class="table-responsive">
        <table class="table table-bordered table-hover">
          <thead><tr>
            <th>所在地</th><th>最寄り駅</th><th>徒歩</th><th>価格</th>
            <th>利回り</th><th>築年</th><th>耐震</th><th>戸数</th>
            <th>土地</th><th>建物</th><th>構造</th><th>評価</th><th>リンク</th>
          </tr></thead>
          <tbody>{list_rows}</tbody>
        </table>
      </div>
      <small class="text-muted">● 色はエリア区分。太字の最寄り駅は指定ターゲット駅。</small>
    </div>

    <!-- エリア別 -->
    <div class="tab-pane fade" id="tab-area">
      <h3>エリア別物件一覧</h3>
      {area_html}
    </div>

    <!-- 推移グラフ -->
    <div class="tab-pane fade" id="tab-trend">
      <h3>相場推移グラフ</h3>
      {trend_note}
      {"" if not has_trend else f"""
      <div class="row g-3">
        <div class="col-md-6"><div style="height:240px"><canvas id="c1"></canvas></div></div>
        <div class="col-md-6"><div style="height:240px"><canvas id="c2"></canvas></div></div>
        <div class="col-md-6"><div style="height:240px"><canvas id="c3"></canvas></div></div>
        <div class="col-md-6"><div style="height:240px"><canvas id="c4"></canvas></div></div>
      </div>
      <small class="text-muted mt-2 d-block">※ データが蓄積されるにつれてグラフが充実します。</small>
      """}
    </div>

    <!-- 評価 -->
    <div class="tab-pane fade" id="tab-eval">
      <h3>個別物件評価</h3>
      <table class="table table-bordered table-hover">
        <thead><tr><th>所在地</th><th>評価</th><th>評価コメント</th><th>リンク</th></tr></thead>
        <tbody>{eval_rows}</tbody>
      </table>
      <div class="mt-3 p-3" style="background:#f8f9fa;border-radius:6px;font-size:.82rem">
        <strong>評価基準：</strong><br>
        <span style="color:#27ae60">A</span>: 利回り4.5%以上・新耐震・駅7分以内・戸数4戸以上の条件を高水準で満たす<br>
        <span style="color:#2980b9">B+/B</span>: 概ね良好。一部条件が不足<br>
        <span style="color:#e67e22">C</span>: 要確認事項あり<br>
        <span style="color:#e74c3c">D</span>: 旧耐震・利回り異常など重大な懸念あり
      </div>
    </div>

    <!-- 更新情報 -->
    <div class="tab-pane fade" id="tab-alert">
      <h3>前回比 更新情報</h3>
      {new_items_html if new_items_html else '<p class="text-muted">新着物件はありません。</p>'}
      {gone_items_html if gone_items_html else '<p class="text-muted">消滅した物件はありません。</p>'}
    </div>

  </div><!-- /tab-content -->
</div><!-- /container -->

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
{"" if not has_trend else f"""
<script>
const opt = {{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}}}};
new Chart(document.getElementById("c1"),{{type:"line",data:{{labels:{t_dates},datasets:[{{label:"掲載件数",data:{t_counts},borderColor:"#2980b9",fill:true,backgroundColor:"#2980b910",tension:0.3}}]}},options:{{...opt,plugins:{{...opt.plugins,title:{{display:true,text:"掲載件数推移"}}}}}}}});
new Chart(document.getElementById("c2"),{{type:"line",data:{{labels:{t_dates},datasets:[{{label:"平均価格(万円)",data:{t_prices},borderColor:"#e74c3c",fill:true,backgroundColor:"#e74c3c10",tension:0.3}}]}},options:{{...opt,plugins:{{...opt.plugins,title:{{display:true,text:"平均価格推移（万円）"}}}}}}}});
new Chart(document.getElementById("c3"),{{type:"line",data:{{labels:{t_dates},datasets:[{{label:"平均利回り(%)",data:{t_yields},borderColor:"#27ae60",fill:true,backgroundColor:"#27ae6010",tension:0.3}}]}},options:{{...opt,plugins:{{...opt.plugins,title:{{display:true,text:"平均利回り推移（%）"}}}}}}}});
{area_trend_js}
</script>
"""}
</body>
</html>'''
    return html

# ===========================================================
# メイン
# ===========================================================

def main():
    today     = date.today()
    today_str = today.strftime('%Y年%m月%d日（') + ['月','火','水','木','金','土','日'][today.weekday()] + '）'
    today_key = today.strftime('%Y-%m-%d')

    print(f'\n🏢 文京区 一棟アパート モニター')
    print(f'📅 {today_str}')
    print('=' * 50)

    # ── 1. スクレイピング ──
    print('\n【1/4】 各サイトを巡回中...')
    props = []
    props += scrape_rakumachi(); time.sleep(2)
    props += scrape_kenbiya();   time.sleep(2)
    props += scrape_athome()

    # ── 2. 統合・重複除去 ──
    print('\n【2/4】 データを統合中...')
    properties = merge(props)
    print(f'  → {len(properties)} 件確認')

    # ── 3. 履歴更新（前回スナップを保存してから追記）──
    print('\n【3/4】 履歴を更新中...')
    history = load_history()
    snaps = history.get('snapshots', [])

    # 同日の既存エントリがあれば上書き、なければ追記
    prev_snap = snaps[-1] if snaps and snaps[-1]['date'] != today_key else (snaps[-2] if len(snaps) >= 2 else None)

    prices  = [p['price'] for p in properties if p.get('price')]
    yields  = [p['yield_rate'] for p in properties if p.get('yield_rate')]
    new_snap = {
        'date':         today_key,
        'count':        len(properties),
        'avg_price':    sum(prices)/len(prices) if prices else 0,
        'avg_yield':    sum(yields)/len(yields) if yields else 0,
        'property_ids': [p['id'] for p in properties],
        'properties':   properties,
    }
    # 同日のエントリは上書き、別日なら追記
    if snaps and snaps[-1]['date'] == today_key:
        snaps[-1] = new_snap
    else:
        snaps.append(new_snap)
    history['snapshots'] = snaps
    save_history(history)

    # ── 4. レポート生成 ──
    print('\n【4/4】 レポートを生成中...')
    html = generate_report(properties, prev_snap, history, today_str)

    # 日付付きファイルと latest.html の両方に保存
    path_dated  = os.path.join(REPORT_DIR, f'report_{today_key}.html')
    path_latest = os.path.join(REPORT_DIR, 'latest.html')
    for path in [path_dated, path_latest]:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html)

    print(f'\n✅ 完了！')
    print(f'📊 レポート（日付付き）: {path_dated}')
    print(f'📊 最新版（ブックマーク用）: {path_latest}')
    subprocess.run(['open', path_latest])  # latest.html をブラウザで開く

if __name__ == '__main__':
    main()
