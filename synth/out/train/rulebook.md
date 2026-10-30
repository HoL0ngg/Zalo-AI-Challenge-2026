# Quy tắc vận hành — TRAIN

- **Doanh thu:** tổng `so_luong * don_gia - giam_gia_dong` (không âm) của đơn hợp lệ; KHÔNG trừ voucher cấp đơn.
- Không cộng VAT, phí ship. Loại đơn hủy và **toàn bộ đơn** nếu có ít nhất một dòng trả hàng.
- **Bán chạy** = số lượng bán hợp lệ, không phải doanh thu. Thứ tự hòa: mã sản phẩm tăng dần.
- **Tuần:** Thứ hai–Chủ nhật. “Tuần rồi / tuần trước” là tuần lịch liền trước, không phải 7 ngày gần đây.
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
{
  "cost_method": "weighted_average_lots",
  "deduplicate_by_record_id": true,
  "exclude_cancelled": true,
  "exclude_entire_order_if_any_return": true,
  "month_to_as_of": true,
  "revenue_include_shipping": false,
  "revenue_include_vat": false,
  "revenue_subtract_order_voucher": false,
  "tet_lunar_end": "01-10",
  "tet_lunar_start": "12-23",
  "top_seller_metric": "quantity",
  "week_start": "monday"
}
```
