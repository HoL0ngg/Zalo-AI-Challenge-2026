"""Executable gold answers computed solely from reloaded tables and rulebook.

No precomputed numeric answers, hidden registry, or LLM output is used here.
"""
from __future__ import annotations
import calendar
import math
from datetime import date, datetime, timedelta
import pandas as pd

WEEKDAYS = ['Thứ hai', 'Thứ ba', 'Thứ tư', 'Thứ năm', 'Thứ sáu', 'Thứ bảy', 'Chủ nhật']


def parse_date(value) -> date | None:
    s = str(value).strip()
    if not s or s == 'nan' or s == 'None':
        return None
    if '-' in s:
        return date.fromisoformat(s[:10])
    return datetime.strptime(s[:10], '%d/%m/%Y').date()


def num(value) -> float:
    s = str(value).strip().replace(' ', '')
    if s in ('', 'None', 'nan'):
        return 0.0
    # Dataset numbers are nonnegative integers, separators in groups of 3.
    return float(s.replace(',', '').replace('.', ''))


def as_int(x: float) -> int:
    return math.floor(x + .5) if x >= 0 else math.ceil(x - .5)


def fmt_number(x: float, two_decimal: bool = False):
    return round(float(x) + 1e-10, 2) if two_decimal else as_int(float(x))


def _normalize_return(v) -> bool:
    return str(v).strip().casefold() in ('true', '1', '1.0', 'yes', 'có')


class Dataset:
    """Canonical in-memory computation view, loaded from disk by caller."""
    def __init__(self, raw: dict[str, pd.DataFrame], rules: dict, cal: pd.DataFrame):
        self.rules = rules
        self.available_columns = {table: set(df.columns) for table, df in raw.items()}
        self.cal = cal.copy()
        self.cal['date'] = self.cal['date'].map(parse_date)
        self.products = raw['products'].drop_duplicates('ma_sp').copy()
        self.customers = raw['customers'].drop_duplicates('ma_kh').copy()
        self.orders = raw['orders'].drop_duplicates('ma_don').copy()
        self.lines = raw['order_lines'].drop_duplicates('dong_id').copy()
        self.purchases = raw['purchases'].drop_duplicates('lo_id').copy() if 'purchases' in raw else None
        self.debts = raw['debts'].copy() if 'debts' in raw else None
        self.has_cost = self.purchases is not None and 'gia_nhap' in self.purchases.columns
        self.has_expiry = self.purchases is not None and 'han_dung' in self.purchases.columns and self.purchases['han_dung'].astype(str).str.strip().ne('').any()
        self.orders['day'] = self.orders['ngay'].map(parse_date)
        for col in ('voucher_don', 'phi_ship', 'vat'):
            self.orders[col] = self.orders[col].map(num)
        for col in ('so_luong', 'don_gia', 'giam_gia_dong'):
            self.lines[col] = self.lines[col].map(num)
        self.lines['tra_hang'] = self.lines['tra_hang'].map(_normalize_return)
        self.lines['line_revenue'] = (self.lines['so_luong'] * self.lines['don_gia'] - self.lines['giam_gia_dong']).clip(lower=0)
        returned = set(self.lines.loc[self.lines['tra_hang'], 'ma_don'])
        is_cancel = self.orders['trang_thai'].astype(str).str.casefold().str.strip().isin(('hủy', 'huỷ', 'huy', 'cancelled'))
        self.cancelled = self.orders.loc[is_cancel].copy()
        invalid = set(self.cancelled['ma_don'])
        if rules['exclude_entire_order_if_any_return']:
            invalid |= returned
        self.valid_orders = self.orders[~self.orders['ma_don'].isin(invalid)].copy()
        join_cols = ['ma_don', 'ma_kh', 'day', 'voucher_don', 'phi_ship', 'vat']
        self.sales = self.lines.merge(self.valid_orders[join_cols], on='ma_don', how='inner', validate='many_to_one')
        if rules['revenue_subtract_order_voucher']:
            # Order voucher is applied proportionally to each line's net value.
            totals = self.sales.groupby('ma_don')['line_revenue'].transform('sum')
            reduction = self.sales['voucher_don'] * self.sales['line_revenue'] / totals.replace(0, float('nan'))
            self.sales['revenue'] = (self.sales['line_revenue'] - reduction.fillna(0)).clip(lower=0)
        else:
            self.sales['revenue'] = self.sales['line_revenue']
        if rules['revenue_include_vat']:
            sizes = self.sales.groupby('ma_don')['line_revenue'].transform('sum').replace(0, float('nan'))
            self.sales['revenue'] += (self.sales['vat'] * self.sales['line_revenue'] / sizes).fillna(0)
        if rules['revenue_include_shipping']:
            sizes = self.sales.groupby('ma_don')['line_revenue'].transform('sum').replace(0, float('nan'))
            self.sales['revenue'] += (self.sales['phi_ship'] * self.sales['line_revenue'] / sizes).fillna(0)
        self.products['ten_sp'] = self.products['ten_sp'].astype(str).str.strip()
        self.product_names = dict(zip(self.products['ma_sp'], self.products['ten_sp']))
        self.aliases = {}
        for sku, group in self.lines.groupby('ma_sp', sort=True):
            name = self.product_names.get(sku, sku)
            self.aliases[sku] = sorted({sku, name, *[x.strip() for x in group['ten_hien_thi'].astype(str) if x.strip()]})
        if self.purchases is not None:
            for col in ('so_luong', 'gia_nhap'):
                if col in self.purchases:
                    self.purchases[col] = self.purchases[col].map(num)
            for col in ('ngay_nhap', 'han_dung'):
                if col in self.purchases:
                    self.purchases[col + '_dt'] = self.purchases[col].map(parse_date)
        if self.debts is not None:
            self.debts['so_tien_no'] = self.debts['so_tien_no'].map(num)
            self.debts['day'] = self.debts['ngay_no'].map(parse_date)

    def period(self, key: str, asof: date) -> tuple[date, date] | None:
        if key == 'yesterday':
            return asof - timedelta(days=1), asof - timedelta(days=1)
        if key in ('this_month', 'last_month', 'same_month_lastyear'):
            first = asof.replace(day=1)
            if key == 'this_month':
                return first, asof
            if key == 'last_month':
                last = first - timedelta(days=1)
                return last.replace(day=1), last
            y = asof.year - 1
            last_day = calendar.monthrange(y, asof.month)[1]
            return date(y, asof.month, 1), date(y, asof.month, min(asof.day, last_day))
        if key in ('last_week', 'this_week', 'prior_week'):
            start_day = 6 if self.rules['week_start'] == 'sunday' else 0
            beginning = asof - timedelta(days=(asof.weekday() - start_day) % 7)
            if key == 'this_week':
                return beginning, asof
            if key == 'prior_week':
                return beginning - timedelta(days=14), beginning - timedelta(days=8)
            return beginning - timedelta(days=7), beginning - timedelta(days=1)
        if key == 'tet':
            mask = self.cal['is_tet_window'].astype(int).eq(1)
            dates = sorted(self.cal.loc[mask, 'date'])
            groups = []
            if not dates:
                return None
            beginning = prev = dates[0]
            for d in dates[1:]:
                if (d - prev).days > 1:
                    groups.append((beginning, prev))
                    beginning = d
                prev = d
            groups.append((beginning, prev))
            passed = [p for p in groups if p[1] <= asof]
            return passed[-1] if passed else None
        raise ValueError(key)

    def scoped(self, key: str, asof: date) -> tuple[pd.DataFrame, pd.DataFrame]:
        period = self.period(key, asof)
        if period is None:
            return self.sales.iloc[:0], self.valid_orders.iloc[:0]
        begin, end = period
        sales = self.sales[(self.sales['day'] >= begin) & (self.sales['day'] <= end)]
        orders = self.valid_orders[(self.valid_orders['day'] >= begin) & (self.valid_orders['day'] <= end)]
        return sales, orders

    def stock(self, asof: date) -> dict[str, float]:
        if self.purchases is None:
            return {}
        lots = self.purchases[self.purchases['ngay_nhap_dt'].le(asof)]
        inputs = lots.groupby('ma_sp')['so_luong'].sum().to_dict()
        outputs = self.sales[self.sales['day'].le(asof)].groupby('ma_sp')['so_luong'].sum().to_dict()
        return {sku: max(0.0, inputs.get(sku, 0) - outputs.get(sku, 0)) for sku in self.product_names}

    def cost(self, asof: date) -> dict[str, float]:
        if not self.has_cost:
            return {}
        lots = self.purchases[self.purchases['ngay_nhap_dt'].le(asof)].copy()
        lots['extended'] = lots['so_luong'] * lots['gia_nhap']
        by = lots.groupby('ma_sp').agg(quantity=('so_luong', 'sum'), total=('extended', 'sum'))
        return {sku: row['total'] / row['quantity'] for sku, row in by.iterrows() if row['quantity'] > 0}


def _unans(reason: str) -> dict:
    return {'type': 'unanswerable', 'answer': None, 'reason': reason}


def _value(kind: str, answer, alias: list[str] | None = None) -> dict:
    d = {'type': kind, 'answer': answer}
    if alias:
        d['alias'] = alias
    return d


def _metric_rank(ds: Dataset, sales: pd.DataFrame, field: str, bottom: bool = False):
    if sales.empty:
        return None
    grouped = sales.groupby('ma_sp', sort=True)[field].sum().sort_index()
    ranked = sorted(grouped.index, key=lambda sku: (grouped[sku] if bottom else -grouped[sku], sku))
    return ranked


def _growth(current: float, previous: float) -> dict:
    if previous == 0:
        return _unans('Kỳ so sánh có mẫu số bằng 0, không xác định tỷ lệ tăng trưởng.')
    pct = (current - previous) / previous * 100
    return _value('percent', round(pct, 2))


def _product_name(ds: Dataset, sku: str) -> dict:
    return _value('string', ds.product_names[sku], ds.aliases.get(sku))


def answer_question(ds: Dataset, spec: dict, as_of_date: str) -> dict:
    """Compute a portal-style answer given the template ID and semantic parameters."""
    template = spec['template']
    asof = date.fromisoformat(as_of_date)
    period = spec.get('period', 'this_month')
    sales, orders = ds.scoped(period, asof)
    if template in ('top_qty', 'bottom_qty', 'top_revenue', 'top3_qty', 'top3_revenue'):
        field = 'revenue' if 'revenue' in template else 'so_luong'
        ranked = _metric_rank(ds, sales, field, bottom=template == 'bottom_qty')
        if ranked is None:
            if template.startswith('top3'):
                return _value('list', [])
            return _unans('Không có giao dịch hợp lệ trong kỳ để xếp hạng sản phẩm.')
        if template.startswith('top3'):
            return _value('list', [ds.product_names[sku] for sku in ranked[:3]])
        return _product_name(ds, ranked[0])
    if template == 'revenue':
        return _value('number', as_int(sales['revenue'].sum()))
    if template == 'orders_count':
        return _value('number', int(len(orders)))
    if template == 'qty_total':
        return _value('number', as_int(sales['so_luong'].sum()))
    if template == 'cancel_count':
        bounds = ds.period(period, asof)
        if bounds is None:
            return _value('number', 0)
        a, b = bounds
        return _value('number', int(ds.cancelled['day'].between(a, b).sum()))
    if template == 'growth':
        compare = spec['compare']
        other, _ = ds.scoped(compare, asof)
        # compare this month's partial total against the previous full month, per rulebook.
        return _growth(float(sales['revenue'].sum()), float(other['revenue'].sum()))
    if template == 'best_day':
        if sales.empty: return _unans('Không có ngày nào phát sinh doanh thu hợp lệ.')
        daily = sales.groupby('day')['revenue'].sum()
        best = min([d for d in daily.index if daily[d] == daily.max()])
        return _value('date', best.isoformat())
    if template == 'top_weekday':
        if orders.empty: return _unans('Không có đơn hợp lệ trong kỳ.')
        days = orders['day'].map(lambda d: d.weekday()).value_counts()
        best = min(i for i, v in days.items() if v == days.max())
        return _value('string', WEEKDAYS[best])
    if template == 'sold_product':
        sku = spec['sku']
        if sku not in ds.product_names:
            return _unans('Sản phẩm được hỏi không xuất hiện trong dữ liệu của cơ sở.')
        return _value('boolean', bool(sales['ma_sp'].eq(sku).any()))
    if template == 'debt_table':
        if ds.debts is None:
            return _unans('Không có bảng theo dõi công nợ trong bộ dữ liệu.')
        debt = ds.debts[ds.debts['day'].le(asof)].groupby('ma_kh')['so_tien_no'].sum()
        names = ds.customers.set_index('ma_kh')['ten_kh'].to_dict()
        rows = [[sku, names.get(sku, ''), as_int(amount)] for sku, amount in debt.items() if amount > 0]
        rows.sort(key=lambda r: (-r[2], r[0]))
        return _value('table', {'columns': ['ma_kh', 'ten_kh', 'so_tien_no'], 'rows': rows})
    if template in ('near_expiry', 'low_stock', 'slow_high_stock'):
        if ds.purchases is None:
            return _unans('Thiếu chứng từ nhập lô để xác định tồn kho.')
        stocks = ds.stock(asof)
        if template == 'near_expiry':
            if not ds.has_expiry:
                return _unans('Không có hạn sử dụng trong chứng từ nhập hàng.')
            # FIFO assignment of cumulative sales to dated lots, product-by-product.
            sold_all = ds.sales[ds.sales['day'].le(asof)].groupby('ma_sp')['so_luong'].sum().to_dict()
            expiry_items = set()
            lots = ds.purchases[ds.purchases['ngay_nhap_dt'].le(asof)].sort_values(['ma_sp', 'ngay_nhap_dt', 'lo_id'])
            for sku, part in lots.groupby('ma_sp', sort=True):
                consumed = sold_all.get(sku, 0)
                for _, lot in part.iterrows():
                    quantity_left = max(0, lot['so_luong'] - consumed)
                    consumed = max(0, consumed - lot['so_luong'])
                    expiry = lot['han_dung_dt']
                    if expiry and asof <= expiry <= asof + timedelta(days=30) and quantity_left > 0:
                        expiry_items.add(sku)
            return _value('list', sorted([ds.product_names[s] for s in expiry_items]))
        if template == 'low_stock':
            return _value('list', sorted(ds.product_names[sku] for sku, qty in stocks.items() if qty < 15))
        start30 = asof - timedelta(days=29)
        recent = ds.sales[ds.sales['day'].between(start30, asof)].groupby('ma_sp')['so_luong'].sum().to_dict()
        items = [sku for sku, qty in stocks.items() if qty >= 70 and recent.get(sku, 0) <= 2]
        return _value('list', sorted(ds.product_names[s] for s in items))
    if template == 'aov':
        if orders.empty: return _unans('Không có đơn hàng hợp lệ để tính giá trị đơn bình quân.')
        return _value('number', fmt_number(float(sales['revenue'].sum()) / len(orders), two_decimal=True))
    if template == 'profit':
        if not ds.has_cost:
            return _unans('Thiếu trường giá vốn và giá nhập lô nên không thể tính lợi nhuận.')
        cost = ds.cost(asof)
        if not set(sales['ma_sp']).issubset(cost):
            return _unans('Thiếu lô có giá nhập cho một số sản phẩm đã bán trong kỳ.')
        cogs = (sales['ma_sp'].map(cost) * sales['so_luong']).sum()
        return _value('number', as_int(float(sales['revenue'].sum()) - float(cogs)))
    if template == 'customer_debt':
        if ds.debts is None:
            return _unans('Cơ sở không có bảng công nợ.')
        cid = spec['customer_id']
        if cid not in set(ds.customers['ma_kh']):
            return _unans('Khách hàng không tồn tại trong danh mục.')
        amount = ds.debts[(ds.debts['ma_kh'] == cid) & (ds.debts['day'].le(asof))]['so_tien_no'].sum()
        return _value('number', as_int(amount))
    if template == 'top_customer':
        if sales.empty: return _unans('Chưa có khách hàng mua hợp lệ trong kỳ.')
        revenue = sales.groupby('ma_kh')['revenue'].sum()
        who = sorted(revenue.index, key=lambda key: (-revenue[key], key))[0]
        names = ds.customers.set_index('ma_kh')['ten_kh']
        return _value('string', str(names[who]))
    if template == 'unique_customers':
        return _value('number', int(orders['ma_kh'].nunique()))
    if template == 'top_category':
        if sales.empty: return _unans('Không có sản phẩm bán trong kỳ.')
        categories = ds.products.set_index('ma_sp')['danh_muc'].astype(str).str.strip().to_dict()
        agg = sales.assign(category=sales['ma_sp'].map(categories)).groupby('category')['revenue'].sum()
        best = sorted(agg.index, key=lambda key: (-agg[key], key))[0]
        return _value('string', best)
    if template == 'unknown_product':
        named = str(spec.get('requested_product', '')).casefold()
        present = [sku for sku, name in ds.product_names.items() if named in (sku.casefold(), name.casefold())]
        if not present:
            return _unans('Không có mã hoặc tên sản phẩm được hỏi trong dữ liệu cơ sở.')
        return _value('number', as_int(sales[sales['ma_sp'].eq(present[0])]['so_luong'].sum()))
    if template == 'missing_metric':
        field = spec['missing_column']
        if not any(field in cols for cols in ds.available_columns.values()):
            return _unans(f'Không có trường {field} trong dữ liệu của cơ sở.')
        return _unans(f'Có trường {field} nhưng không có dữ liệu/định nghĩa chỉ tiêu đủ để tổng hợp.')
    if template == 'outside_range':
        # The question's specified Gregorian interval predates *this* business.
        first = ds.orders['day'].min()
        if first > date(2023, 1, 31):
            return _unans('Không có lịch sử giao dịch tháng 01/2023, nằm ngoài khoảng dữ liệu.')
        return _value('number', as_int(ds.sales[ds.sales['day'].between(date(2023,1,1), date(2023,1,31))]['revenue'].sum()))
    raise KeyError(f'Unknown answer template: {template}')
