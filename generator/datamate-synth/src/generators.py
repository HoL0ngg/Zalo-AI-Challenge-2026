"""Seeded synthetic Vietnamese retail data; deterministic and network-free."""
from __future__ import annotations
import calendar as pycalendar
import json
import random
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
from .calendar import solar_to_lunar

LABELS = {
    'tap_hoa': 'Tạp hóa khu dân cư', 'ca_phe': 'Quán cà phê và trà sữa',
    'nha_thuoc': 'Nhà thuốc', 'vlxd': 'Cửa hàng vật liệu xây dựng',
    'sua_xe': 'Tiệm sửa xe máy', 'me_va_be': 'Cửa hàng mẹ và bé',
    'quan_com': 'Quán cơm văn phòng', 'dien_thoai': 'Cửa hàng điện thoại'
}
FIRST_NAMES = ('An', 'Bình', 'Bảo', 'Chi', 'Duyên', 'Đạt', 'Hà', 'Hân', 'Hiếu', 'Hòa', 'Hùng', 'Khang', 'Lan', 'Linh', 'Long', 'Mai', 'Minh', 'Nam', 'Ngân', 'Ngọc', 'Phúc', 'Phương', 'Quân', 'Quỳnh', 'Thảo', 'Thành', 'Trang', 'Trúc', 'Tú', 'Vy')
LAST_NAMES = ('Nguyễn', 'Trần', 'Lê', 'Phạm', 'Hoàng', 'Huỳnh', 'Phan', 'Vũ', 'Đặng', 'Bùi')
REGIONS = ('Quận 1', 'Quận 3', 'Bình Thạnh', 'Gò Vấp', 'Thủ Đức', 'Tân Bình', 'Phú Nhuận', 'Bình Tân')


def _months_later(first: date, months: int) -> date:
    m = first.month - 1 + months
    y = first.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(first.day, pycalendar.monthrange(y, m)[1]))


def _daystr(day: date, style: int, rng: random.Random) -> str:
    if style == 0:
        return day.isoformat() if rng.random() < 0.90 else day.strftime('%d/%m/%Y')
    return day.strftime('%d/%m/%Y') if rng.random() < 0.90 else day.isoformat()


def _num(value: int, rng: random.Random, rate: float) -> int | str:
    if rng.random() < rate and abs(value) >= 1000:
        return f'{value:,}'.replace(',', '.' if rng.random() < 0.5 else ',')
    return int(value)


def _undia(s: str) -> str:
    d = unicodedata.normalize('NFD', s.replace('đ', 'd').replace('Đ', 'D'))
    return ''.join(c for c in d if unicodedata.category(c) != 'Mn')


def _variant(s: str, rng: random.Random) -> str:
    mode = rng.randrange(6)
    if mode == 0:
        return _undia(s.lower()).replace('ml', ' ml')
    if mode == 1:
        return s.upper()
    if mode == 2:
        return s.lower() + '  '
    if mode == 3:
        return unicodedata.normalize('NFD', s)
    if mode == 4:
        return s.title()
    return s.replace(' ', '  ', 1)


def _product_price(name: str, kind: str, rng: random.Random) -> int:
    if kind == 'dien_thoai':
        if 'Điện thoại' in name or any(x in name.lower() for x in ('iphone', 'galaxy', 'xiaomi', 'oppo', 'vivo', 'realme', 'nokia', 'ipad', 'tab ')):
            return rng.randrange(200, 2800) * 10000
        return rng.randrange(8, 160) * 10000
    if kind == 'vlxd':
        return rng.randrange(15, 600) * 1000
    if kind == 'nha_thuoc':
        return rng.randrange(8, 400) * 1000
    if kind == 'me_va_be':
        return rng.randrange(20, 850) * 1000
    if kind == 'sua_xe':
        return rng.randrange(12, 490) * 1000
    return rng.randrange(8, 150) * 1000


def _unit(kind: str, name: str) -> str:
    if kind == 'vlxd':
        if 'm3' in name: return 'm³'
        if 'kg' in name.lower(): return 'kg'
        return 'cái'
    if kind in ('ca_phe', 'quan_com'): return 'phần'
    if kind == 'sua_xe' and name.startswith('Công '): return 'lần'
    return 'cái'


def _weighted_days(start: date, end: date, kind: str) -> tuple[list[date], np.ndarray]:
    days, weights = [], []
    d = start
    while d <= end:
        ld, lm, _, _ = solar_to_lunar(d)
        # Shops mostly close on the first and second lunar New Year days.
        if lm == 1 and ld in (1, 2):
            w = 0.0
        else:
            w = 1.32 if d.weekday() >= 5 else 1.0
            if d.day in (1, 15, 25, 30): w *= 1.30
            if (lm == 12 and ld >= 23) or (lm == 1 and ld <= 10): w *= 1.7
            if lm == 8 and 11 <= ld <= 16 and kind in ('ca_phe', 'quan_com'): w *= 1.7
            if (d.month, d.day) in ((1, 1), (4, 30), (5, 1), (9, 2)): w *= 1.45
            if d.weekday() == 6 and kind == 'vlxd': w *= 0.55
        days.append(d)
        weights.append(w)
        d += timedelta(days=1)
    p = np.asarray(weights, dtype=float)
    return days, p / p.sum()


def generate_business(business_id: str, kind: str, seed: int, config: dict, catalog: dict, style: int) -> tuple[dict[str, pd.DataFrame], dict]:
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    month_count = rng.randint(*config['months_per_business'])
    start = date(2025, rng.choice((3, 4, 5)), 1)
    end = _months_later(start, month_count) - timedelta(days=1)
    target_lines = rng.randint(*config['rows_per_business'])
    nproducts = min(len(catalog[kind]), rng.randint(*config['products_per_business']))
    ncustomers = rng.randint(*config['customers_per_business'])
    miss_cost = business_id in config['missing_cost_business_ids']
    noise_cfg = config['noise']
    entries = rng.sample(catalog[kind], nproducts)
    products, customers = [], []
    product_names = {}
    for i, e in enumerate(entries, 1):
        name, category = e.split('|')
        sku = f'P{i:04}'
        product_names[sku] = name
        price = _product_price(name, kind, rng)
        group = category
        if rng.random() < 0.027:
            group = _undia(category) if rng.random() < .6 else category + ' '
        record = dict(ma_sp=sku, ten_sp=name, danh_muc=group, don_vi=_unit(kind, name), gia_ban=_num(price, rng, noise_cfg['text_number_rate']))
        if not miss_cost:
            record['gia_von'] = _num(int(price * rng.uniform(.58, .82)), rng, noise_cfg['text_number_rate'])
        products.append(record)
    for i in range(1, ncustomers + 1):
        customers.append({
            'ma_kh': f'C{i:04}', 'ten_kh': rng.choice(LAST_NAMES) + ' ' + rng.choice(FIRST_NAMES) + ' ' + rng.choice(FIRST_NAMES),
            'sdt': f'09{rng.randrange(0, 100_000_000):08}',
            'khu_vuc': '' if rng.random() < noise_cfg['missing_optional_cell_rate'] else rng.choice(REGIONS)
        })
    days, weights = _weighted_days(start, end, kind)
    # Generate N line items, then group into 1-3 lines per order.
    norders = round(target_lines / 1.75)
    indices = np_rng.choice(len(days), size=norders, replace=True, p=weights)
    order_dates = sorted(days[int(i)] for i in indices)
    zipf = np.asarray([1 / (i + 2) ** 1.05 for i in range(nproducts)], dtype=float)
    zipf /= zipf.sum()
    orders, lines = [], []
    for i, sale_date in enumerate(order_dates, 1):
        oid = f'O{i:06}'
        cancelled = rng.random() < config['cancel_rate']
        status = 'hủy' if cancelled else 'hoàn thành'
        customer = f'C{rng.randint(1, ncustomers):04}'
        count = rng.choices((1, 2, 3), weights=(0.45, 0.37, 0.18))[0]
        voucher_requested = rng.choice((0, 0, 0, 0, 5000, 10000, 20000))
        orders.append(dict(
            ma_don=oid, ngay=_daystr(sale_date, style, rng), ma_kh=customer,
            trang_thai=status, voucher_don=0,
            phi_ship=_num(rng.choice((0, 0, 12000, 20000, 25000)), rng, noise_cfg['text_number_rate']),
            vat=0
        ))
        subtotal = 0
        for j in range(count):
            pidx = int(np_rng.choice(nproducts, p=zipf))
            p = products[pidx]
            sku = p['ma_sp']
            base_price = int(str(p['gia_ban']).replace('.', '').replace(',', ''))
            multiplier = 1.0 + ((sale_date - start).days // 130) * 0.015
            price = int(round(base_price * multiplier / 1000)) * 1000
            qty = rng.choices((1, 2, 3, 4, 6), (0.62, 0.22, 0.09, 0.05, 0.02))[0]
            discount = min(price * qty, rng.choice((0, 0, 0, 0, 1000, 3000, 5000)))
            subtotal += price * qty - discount
            display = _variant(product_names[sku], rng) if rng.random() < noise_cfg['display_variant_rate'] else product_names[sku]
            returned = rng.random() < config['returns_rate']
            lines.append(dict(
                dong_id=f'L{i:06}-{j+1}', ma_don=oid, ma_sp=sku,
                so_luong=qty, don_gia=_num(price, rng, noise_cfg['text_number_rate']),
                giam_gia_dong=_num(discount, rng, noise_cfg['text_number_rate']),
                tra_hang=returned, ten_hien_thi=display
            ))
        orders[-1]['voucher_don'] = _num(min(voucher_requested, subtotal), rng, noise_cfg['text_number_rate'])
        orders[-1]['vat'] = _num(int(subtotal * .08) if rng.random() < .35 else 0, rng, noise_cfg['text_number_rate'])
    # Cap not exact, but targeted count is within user requested 500-5000.
    assert 500 <= len(lines) <= 5000
    # Inject tiny number of same-ID duplicate export rows; id is the dedup key.
    for r in rng.sample(lines, min(int(len(lines) * noise_cfg['duplicate_line_rate']), 8)):
        lines.append(dict(r))
    rng.shuffle(lines)
    sold = Counter()
    sold_by_third = [Counter(), Counter(), Counter()]
    span = max(1, (end - start).days)
    order_day = {o['ma_don']: date.fromisoformat(o['ngay']) if '-' in o['ngay'] else datetime.strptime(o['ngay'], '%d/%m/%Y').date() for o in orders}
    for line in {row['dong_id']: row for row in lines}.values():
        sku = line['ma_sp']; q = line['so_luong']; sold[sku] += q
        third = min(2, int(((order_day[line['ma_don']] - start).days / span) * 3))
        sold_by_third[third][sku] += q
    purchases = []
    lot_id = 0
    for sku in product_names:
        lean_stock = rng.random() < 0.22
        price = int(str(next(x['gia_ban'] for x in products if x['ma_sp'] == sku)).replace('.', '').replace(',', ''))
        for t in range(3):
            lot_id += 1
            # Each third is replenished early with buffer to avoid negative stock.
            on_date = start + timedelta(days=round((span / 3) * t))
            quantity = int(sold_by_third[t][sku] + (rng.randint(0, 3) if lean_stock else rng.randint(15, 60)))
            expiry = ''
            if kind in ('tap_hoa', 'nha_thuoc', 'me_va_be', 'ca_phe', 'quan_com'):
                expiry = _daystr(on_date + timedelta(days=rng.randint(250, 700)), style, rng)
            lot = dict(
                lo_id=f'B{lot_id:05}', ngay_nhap=_daystr(on_date, style, rng), ma_sp=sku,
                so_luong=quantity, han_dung=expiry
            )
            if not miss_cost:
                lot['gia_nhap'] = _num(int(price * rng.uniform(0.55, 0.79)), rng, noise_cfg['text_number_rate'])
            purchases.append(lot)
    debts = []
    if kind in ('tap_hoa', 'vlxd', 'sua_xe', 'me_va_be', 'dien_thoai'):
        for j, customer in enumerate(rng.sample(customers, min(ncustomers, rng.randint(9, 22))), 1):
            debts.append(dict(ma_kh=customer['ma_kh'], so_tien_no=_num(rng.randrange(50, 1700) * 1000, rng, noise_cfg['text_number_rate']),
                              ngay_no=_daystr(start + timedelta(days=rng.randint(0, span)), style, rng)))
    tables = {name: pd.DataFrame(rows) for name, rows in (
        ('products', products), ('customers', customers), ('orders', orders),
        ('order_lines', lines), ('purchases', purchases)
    )}
    if debts:
        tables['debts'] = pd.DataFrame(debts)
    registry = {
        'business_id': business_id, 'kind': kind, 'start': start.isoformat(), 'end': end.isoformat(),
        'format': config['formats'][((int(business_id[-2:]) - 1) + (1 if business_id.startswith('dev') else 0)) % 3],
        'products': {sku: {'name': name, 'aliases': sorted({name, sku, *[x['ten_hien_thi'].strip() for x in lines if x['ma_sp'] == sku]})} for sku, name in product_names.items()}
    }
    return tables, registry
