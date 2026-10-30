"""31 answerable question templates + four explicitly unanswerable probes.

A Template specifies a natural-language form, a dispatched answer function,
and the expected portal answer type. Questions hold only opaque IDs and text.
"""
from __future__ import annotations
import calendar
import random
from dataclasses import dataclass
from datetime import date, timedelta
from .answers import Dataset


@dataclass(frozen=True)
class Template:
    template_id: str
    text: str
    answer_fn: str
    answer_type: str
    period: str = 'this_month'
    compare: str = ''
    needs: str = ''


TEMPLATES = [
    Template('top_qty_current', 'Mặt hàng nào bán chạy nhất tháng này theo số lượng?', 'top_qty', 'string'),
    Template('top_qty_lastweek', 'Tuần rồi sản phẩm nào bán nhiều nhất?', 'top_qty', 'string', 'last_week'),
    Template('top_qty_tet', 'Trong dịp Tết gần nhất, sản phẩm nào bán chạy nhất?', 'top_qty', 'string', 'tet'),
    Template('top_qty_lastyear', 'Cùng kỳ năm ngoái mặt hàng nào bán nhiều nhất?', 'top_qty', 'string', 'same_month_lastyear'),
    Template('bottom_qty_lastmonth', 'Tháng trước sản phẩm bán ít nhất là gì?', 'bottom_qty', 'string', 'last_month'),
    Template('top_rev_lastweek', 'Tuần rồi mặt hàng nào mang về doanh thu cao nhất?', 'top_revenue', 'string', 'last_week'),
    Template('top_rev_lastyear', 'Cùng kỳ năm ngoái sản phẩm doanh thu cao nhất là gì?', 'top_revenue', 'string', 'same_month_lastyear'),
    Template('revenue_thismonth', 'Tổng doanh thu tháng này tính đến hôm nay là bao nhiêu?', 'revenue', 'number'),
    Template('revenue_lastmonth', 'Tháng trước cửa hàng thu được bao nhiêu tiền bán hàng?', 'revenue', 'number', 'last_month'),
    Template('revenue_lastweek', 'Doanh thu tuần rồi là bao nhiêu?', 'revenue', 'number', 'last_week'),
    Template('revenue_yesterday', 'Hôm qua doanh thu bao nhiêu?', 'revenue', 'number', 'yesterday'),
    Template('revenue_tet', 'Doanh thu dịp Tết gần nhất là bao nhiêu?', 'revenue', 'number', 'tet'),
    Template('revenue_lastyear', 'Doanh thu cùng kỳ năm ngoái đạt bao nhiêu?', 'revenue', 'number', 'same_month_lastyear'),
    Template('growth_month', 'Doanh thu tháng này tăng trưởng bao nhiêu phần trăm so với tháng trước?', 'growth', 'percent', 'this_month', 'last_month'),
    Template('growth_week', 'Doanh thu tuần rồi tăng giảm bao nhiêu % so với tuần liền trước đó?', 'growth', 'percent', 'last_week', 'prior_week'),
    Template('best_day', 'Trong tháng trước, ngày nào có doanh thu cao nhất?', 'best_day', 'date', 'last_month'),
    Template('busy_weekday', 'Tháng trước thứ mấy có nhiều đơn hàng hợp lệ nhất?', 'top_weekday', 'string', 'last_month'),
    Template('sold_yesterday', 'Hôm qua có bán được sản phẩm {product} không?', 'sold_product', 'boolean', 'yesterday'),
    Template('top3_qty', 'Cho mình danh sách top 3 sản phẩm bán nhiều nhất tháng trước, đúng thứ tự.', 'top3_qty', 'list', 'last_month'),
    Template('top3_revenue', 'Liệt kê ba mặt hàng doanh thu cao nhất trong tháng này.', 'top3_revenue', 'list'),
    Template('debt_customers', 'Lập bảng các khách đang nợ tiền, kèm mã khách, tên và số tiền nợ.', 'debt_table', 'table', needs='debts'),
    Template('customer_debt_specific', 'Khách {customer} hiện còn nợ cửa hàng bao nhiêu?', 'customer_debt', 'number', needs='debts'),
    Template('expiry_soon', 'Sản phẩm nào còn tồn mà lô hàng sẽ hết hạn trong 30 ngày tới?', 'near_expiry', 'list', needs='expiry'),
    Template('low_stock', 'Liệt kê hàng đang tồn kho dưới 15 đơn vị.', 'low_stock', 'list'),
    Template('slow_high_stock', 'Sản phẩm nào tồn ít nhất 70 cái mà 30 ngày qua chỉ bán tối đa 2 cái?', 'slow_high_stock', 'list'),
    Template('cancel_count', 'Tháng trước có bao nhiêu đơn hàng bị hủy?', 'cancel_count', 'number', 'last_month'),
    Template('average_order_value', 'Giá trị đơn hàng trung bình tháng này là bao nhiêu?', 'aov', 'number'),
    Template('profit_lastmonth', 'Lợi nhuận gộp tháng trước dựa trên giá vốn bình quân nhập lô là bao nhiêu?', 'profit', 'number', 'last_month', needs='cost'),
    Template('top_customer', 'Khách hàng nào mua nhiều tiền nhất tháng trước?', 'top_customer', 'string', 'last_month'),
    Template('unique_customers', 'Tháng này có bao nhiêu khách hàng khác nhau đã mua?', 'unique_customers', 'number'),
    Template('top_category', 'Nhóm hàng nào đem lại doanh thu cao nhất tháng này?', 'top_category', 'string'),
    Template('count_week', 'Tuần rồi có bao nhiêu đơn hàng hợp lệ?', 'orders_count', 'number', 'last_week'),
    Template('qty_lastmonth', 'Tổng số lượng sản phẩm bán ra tháng trước là bao nhiêu?', 'qty_total', 'number', 'last_month'),
    Template('count_current', 'Tháng này chốt được bao nhiêu đơn hợp lệ?', 'orders_count', 'number')
]


FORCED_UNANSWERABLE = (
    ('unknown_product', 'Sản phẩm Nước thần ZZZ 999ml tuần rồi bán được mấy cái?', 'unknown_product', 'last_week'),
    ('missing_employee', 'Nhân viên ca tối nào mang về doanh thu nhiều nhất tháng trước?', 'missing_metric', 'last_month'),
    ('outside_history', 'Doanh thu trong tháng 01/2023 là bao nhiêu?', 'outside_range', 'last_month'),
    ('missing_utilities', 'Chi phí điện nước riêng của cửa hàng trong tháng trước là bao nhiêu?', 'missing_metric', 'last_month'),
)


def eligible_dates(ds: Dataset, rng: random.Random, count: int) -> list[date]:
    first, last = min(ds.orders['day']), max(ds.orders['day'])
    # after 12 months => same-period-last-year questions have coverage
    eligible = min(first + timedelta(days=370), max(first + timedelta(days=30), last - timedelta(days=25)))
    days = [eligible + timedelta(days=i) for i in range((last - eligible).days + 1)]
    assert len(days) > 25, (first, last)
    monday = next(d for d in days if d.weekday() == 0)
    sunday = next(d for d in days if d.weekday() == 6)
    month_ends = [d for d in days if d.day == calendar.monthrange(d.year, d.month)[1]]
    edges = [monday, sunday, rng.choice(month_ends)]
    return (edges + [rng.choice(days) for _ in range(max(0, count - 3))])[:count]


def make_business_specs(ds: Dataset, registry: dict, seed: int, count: int) -> list[tuple[str, dict, str]]:
    rng = random.Random(seed)
    first, last = min(ds.orders['day']), max(ds.orders['day'])
    normal = [t for t in TEMPLATES if not (
        ((t.period == 'same_month_lastyear') and (last - first).days < 375) or
        (t.needs == 'debts' and ds.debts is None) or
        (t.needs == 'expiry' and not ds.has_expiry) or
        (t.needs == 'cost' and not ds.has_cost)
    )]
    # Every business includes every applicable template; rotate to reach 36.
    normal = list(normal)
    rng.shuffle(normal)
    selected = (normal * (count // len(normal) + 1))[:count - 4]
    rng.shuffle(selected)
    dates = eligible_dates(ds, rng, count)
    skus = sorted(ds.product_names)
    generated = []
    for i, t in enumerate(selected):
        asof = dates[i]
        params = {'template': t.answer_fn, 'period': t.period}
        if t.compare:
            params['compare'] = t.compare
        text = t.text
        if t.answer_fn == 'customer_debt':
            cid = rng.choice(sorted(ds.debts['ma_kh'].unique()))
            params['customer_id'] = cid
            customer_name = ds.customers.loc[ds.customers['ma_kh'].eq(cid), 'ten_kh'].iloc[0]
            # An identifiable partial customer name, sometimes with a code to disambiguate.
            text = text.format(customer=rng.choice([customer_name, ' '.join(customer_name.split(' ')[:2]) + ' (' + cid + ')', cid]))
        if t.answer_fn == 'sold_product':
            sku = rng.choice(skus)
            params['sku'] = sku
            # Ask using an actually observed name variant, or the machine SKU.
            observed = ds.aliases[sku]
            label = rng.choice([ds.product_names[sku], sku, rng.choice(observed)])
            text = text.format(product=label)
        generated.append((text, params, asof.isoformat()))
    forced = list(FORCED_UNANSWERABLE)
    if not ds.has_cost:
        forced[-1] = ('no_cost', 'Lợi nhuận gộp tháng trước là bao nhiêu, tính theo giá vốn bình quân nhập lô?', 'profit', 'last_month')
    for j, (ident, text, fn, period) in enumerate(forced):
        params = {'template': fn, 'period': period}
        if ident == 'unknown_product':
            params['requested_product'] = 'Nước thần ZZZ 999ml'
        elif ident == 'missing_employee':
            params['missing_column'] = 'nhan_vien_ca_toi'
        elif ident == 'missing_utilities':
            params['missing_column'] = 'chi_phi_dien_nuoc'
        generated.append((text, params, dates[count-4+j].isoformat()))
    assert len(generated) == count
    return generated
