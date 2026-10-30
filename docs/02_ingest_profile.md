# 02. Bước 1 — Ingest & Profile

## Mục tiêu
Biến gói dữ liệu thô (nhiều định dạng, lộn xộn) thành một `BusinessContext` có thể truy vấn bằng SQL và mô tả được cho LLM.

## Việc cần làm
1. **Nạp file** vào DuckDB (chỉ đọc):
   - CSV: tự dò dấu phân cách, encoding (UTF-8, UTF-8-BOM, đôi khi cp1258).
   - XLSX: nhiều sheet; tiêu đề có thể nằm ở dòng 2–3; ô gộp ở đầu sheet; bỏ dòng tổng cuối bảng.
   - SQLite: attach read-only, liệt kê bảng/view.
2. **Làm sạch kiểu dữ liệu** (không sửa file gốc, chỉ tạo view):
   - Ngày: nhiều định dạng (`yyyy-mm-dd`, `dd/mm/yyyy`) → chuẩn hóa về DATE.
   - Số lưu dạng chuỗi với dấu `.`/`,` ngăn cách nghìn → số.
   - Unicode: NFC cho mọi chuỗi, `strip` khoảng trắng; **giữ bản gốc** vì đáp án phải khớp cách viết trong dữ liệu.
3. **Profiling** mỗi cột: kiểu, tỉ lệ rỗng, min/max, số giá trị khác nhau, vài giá trị mẫu; phát hiện cột ngày, tiền, số lượng, khóa, tên.
4. **Phát hiện quan hệ**: khóa chính/ngoại (cùng tên cột, tập giá trị chứa nhau).
5. **Đọc ngữ cảnh**:
   - `README.md` của business: mô tả hoạt động, ý nghĩa cột, quirks.
   - `rulebook.md` **của split đang chạy**: trích tham số (định nghĩa doanh thu, tuần bắt đầu thứ mấy, "tháng này", giá vốn, cửa sổ Tết...).
   - `calendar.csv`: ngày dương, âm, cờ Tết.
6. **Từ điển giá trị** cho cột dạng tên (sản phẩm, khách hàng, danh mục...): danh sách giá trị khác nhau để bước Linking dùng.
7. **Cache** theo `business_id` vì nhiều câu hỏi dùng chung một business.

## Đầu ra
`BusinessContext`: tên bảng/view, schema + thống kê, tham số rulebook (dạng cấu trúc + văn bản gốc), từ điển giá trị, calendar.

## Kiểm tra nhất quán giữa các bảng (Phase 4, mục 2)
`ingest/consistency.py` đếm bằng SQL trên view chuẩn (sau `_capabilities`, trong `build_canonical`), kết quả ở `CanonicalSchema.quality`:
| Khóa | Ý nghĩa | Hậu quả nếu bỏ qua |
|---|---|---|
| `lines_without_order` | dòng bán có `order_id` không có trong đơn hàng | bị loại **im lặng** khỏi `v_sales` (INNER JOIN), doanh thu thiếu |
| `line_skus_not_in_products` | SKU trên dòng bán không có trong bảng sản phẩm | tên sản phẩm rơi về SKU, nhóm hàng rỗng |
| `order_customers_not_in_customers` | mã khách trên đơn trỏ vào hư không (khách trống là bình thường, không tính) | thống kê theo khách lệch |
| `orders_without_date` | ngày đơn không đọc được | đơn biến mất khỏi mọi truy vấn theo kỳ |

Mỗi khóa là `0` (sạch), `N > 0` (có vấn đề) hoặc `None` (không biết: thiếu view hoặc truy vấn lỗi). Chỉ **ghi nhận, không chặn câu hỏi**:
mỗi mục `> 0` thành warning `consistency:<khóa>=<N>` (vào `ingest_warnings` trong log), và `describe()` thêm khóa `data_quality` cho prompt **chỉ khi có vấn đề**,
nên business sạch giữ nguyên prompt. Dữ liệu train/dev của bộ sinh không có lỗi nào trong số này (0 warning); giá trị là độ bền cho business mới ở private test.
Không làm: "ngày tương lai" (kỳ đã giải luôn ≤ `as_of`) và tỉ lệ rỗng tổng quát (không có quyết định nào phụ thuộc).

## Lưu ý
- Dữ liệu lớn tới ~300.000 dòng: DuckDB xử lý nhanh, không cần nạp hết vào RAM của LLM; chỉ đưa schema + vài dòng mẫu vào prompt.
- Không bao giờ ghi vào `/data`.
- Mọi bước phải lỗi-an-toàn: file hỏng một phần thì bỏ phần đó, ghi cảnh báo, vẫn tiếp tục.
