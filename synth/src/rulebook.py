"""The markdown rulebook is executable configuration and the single source of truth."""
import json
from pathlib import Path

BASE = {
    'week_start': 'monday',
    'revenue_subtract_order_voucher': False,
    'revenue_include_vat': False,
    'revenue_include_shipping': False,
    'exclude_cancelled': True,
    'exclude_entire_order_if_any_return': True,
    'top_seller_metric': 'quantity',
    'month_to_as_of': True,
    'cost_method': 'weighted_average_lots',
    'deduplicate_by_record_id': True,
    'tet_lunar_start': '12-23',
    'tet_lunar_end': '01-10'
}


def split_rules(split: str) -> dict:
    rules = dict(BASE)
    if split == 'dev':
        rules['week_start'] = 'sunday'
        rules['revenue_subtract_order_voucher'] = True
    return rules


def write_rulebook(path: Path, split: str) -> None:
    r = split_rules(split)
    week = 'Chủ nhật–Thứ bảy' if r['week_start'] == 'sunday' else 'Thứ hai–Chủ nhật'
    voucher = 'TRỪ voucher cấp đơn, phân bổ theo tỷ lệ giá trị dòng hợp lệ.' if r['revenue_subtract_order_voucher'] else 'KHÔNG trừ voucher cấp đơn.'
    body = f'''# Quy tắc vận hành — {split.upper()}

- **Doanh thu:** tổng `so_luong * don_gia - giam_gia_dong` (không âm) của đơn hợp lệ; {voucher}
- Không cộng VAT, phí ship. Loại đơn hủy và **toàn bộ đơn** nếu có ít nhất một dòng trả hàng.
- **Bán chạy** = số lượng bán hợp lệ, không phải doanh thu. Thứ tự hòa: mã sản phẩm tăng dần.
- **Tuần:** {week}. “Tuần rồi / tuần trước” là tuần lịch liền trước, không phải 7 ngày gần đây.
- **Tháng này:** từ ngày 1 đến hết `as_of_date`; “tháng trước” là cả tháng liền trước.
- **Cùng kỳ năm ngoái:** ngày 1 đến ngày tương ứng với as_of_date một năm trước (giới hạn ngày cuối tháng).
- **Giá vốn:** bình quân gia quyền (`sum(qty_nhap*gia_nhap)/sum(qty_nhap)`) của các lô nhập **đến as_of_date**; chi phí phải đủ trường dữ liệu. Doanh thu/profit có thể có phần thập phân, tiền trả dạng số nguyên VND sau làm tròn half-up.
- **Tết:** từ 23 tháng Chạp đến hết mùng 10 tháng Giêng theo lịch âm Việt Nam. Khi hỏi “Tết”, lấy cửa sổ Tết gần nhất đã kết thúc tính đến `as_of_date`.
- **Bản ghi trùng:** loại bản sao cùng `dong_id`/`ma_don`/`lo_id` trước khi tính; các dòng bán hàng khác ID là giao dịch thật.
- **Tồn kho:** nhập lô trước/trong ngày `as_of_date` trừ số lượng bán ở các đơn hợp lệ cho đến ngày đó. Hàng sắp hết hạn: lô có tồn dương và hạn dùng từ `as_of_date` tới +30 ngày.
- **Nợ:** bảng cộng nợ theo khách, không tự trừ bằng đơn bán hàng; nguồn nợ là bảng `debts`.
- **Mức tăng trưởng:** `(kỳ này - kỳ trước) / kỳ trước * 100`, làm tròn 2 chữ số; kỳ trước bằng 0 -> không thể trả lời.

## Cấu hình máy đọc (cũng là nguồn quy tắc cho bộ chấm)

```json
{json.dumps(r, ensure_ascii=False, sort_keys=True, indent=2)}
```
'''
    path.write_text(body, encoding='utf-8')


def read_rulebook(path: Path) -> dict:
    body = path.read_text(encoding='utf-8')
    return json.loads(body.split('```json\n', 1)[1].split('\n```', 1)[0])
