# 18. Phase 4 / P2 — Dữ liệu chính thức: growth, repair và những gì còn thiếu

Bộ train chính thức (3000 câu, 30 business `biz_1xx`, có đáp án) và `public_test` (1000 câu, 14 business `dev_0xx`, không có đáp án) nằm ở `dataset/`.
**`dataset/train` và `dataset/dev` cũ là dữ liệu tổng hợp** (`synth/`); bản tổng hợp còn ở `synth/out/` và các test hồi quy Phase 3 đọc ở đó.
Toàn bộ số đo ở docs 16–17 là trên dữ liệu tổng hợp; **chưa có số đo LLM thật nào trên dữ liệu chính thức**.

## Luật chấm chính thức (rulebook §9) — đã chốt câu hỏi còn mở ở docs/12
Đúng **+1**, sai **−1**, abstain hoặc thiếu dòng **0**. Hệ quả: chỉ nên trả lời khi xác suất đúng > 50%; một câu sai tệ bằng một câu đúng có lợi.
`datamate report` giờ in thêm `points` (`correct`, `wrong`, `abstain`, `score`), `datamate eval` in `accuracy` và `points`.

## Kiểm tra gói dữ liệu không cần LLM
`python scripts/check_package.py dataset/train --answers dataset/train/answers.jsonl [--business biz_123]` (≈11 phút cho cả train): ingest, lớp chuẩn, kỳ, gate.

Kết quả đầu tiên trên train chính thức (trước các sửa ở docs này):
| | |
|---|---|
| business nạp được | 30/30 |
| lớp chuẩn hoàn chỉnh (`v_sales`...) | **1/30** |
| gate bắt đúng câu unanswerable | 0/70 |
| gate chặn nhầm | 34 (cả 34 ở `biz_123`) |
| câu percent có đủ 2 kỳ | 173/598 |

## Đã sửa
| Vấn đề | Sửa | File |
|---|---|---|
| "tháng 3/2025 … so với tháng liền trước" ra tháng của **hôm nay** (8/2026) thay vì 2/2025 | Sau từ nối so sánh (`so với`, `so vs`, `vs`), cụm "X trước/liền trước/rồi" là kỳ liền trước **kỳ chính**, không phải trước hôm nay. Xử lý cả khi cụm so sánh đứng trước kỳ chính. Hỗ trợ viết tắt `th`/`thg` | `understanding/temporal.py` |
| "tháng này so với tháng trước" lấy cả tháng trước | Rulebook chính thức: **cùng số ngày** (chặn ở ngày cuối tháng trước). Là tham số `time.month_compare_same_days` (mặc định `false`, giữ luật cũ); bật tự động khi rulebook có câu đó (đọc từ văn xuôi). Tuần/quý/năm đang mở giữ nguyên | `temporal.py`, `configs/rules_defaults.yaml` |
| Câu tăng giá chỉ ra ngày đổi giá | "N ngày kể từ ngày đó" vs "N ngày liền trước": hai kỳ `[D, D+N−1]` và `[D−N, D−1]` | `temporal.py` (`_price_change_windows`) |
| Mọi câu "%" bị coi là tăng trưởng | `intent_hints.percent_kind` ∈ `growth, share, rate, proportion, price_effect, shift_compare` (regex ở `intent_keywords.percent_kind`, thứ tự quan trọng) | `understanding/intent.py` |
| Model quên `FROM` (17/19 câu growth abstain; repair chép lại y nguyên) | (a) prompt có **khuôn SQL** theo `percent_kind`, điền sẵn ngày kỳ chính/kỳ so sánh (`answer_shape`); (b) `quick_fix` thêm `FROM <bảng>` xác định khi chỉ một bảng được viện dẫn | `codegen/prompt_builder.py`, `execution/repair.py` |
| Repair 1 lượt, mù lỗi | `repair` mới: chẩn đoán theo loại lỗi (thiếu bảng, cột gần đúng, mơ hồ, GROUP BY, ép kiểu), liệt kê cột thật của bảng liên quan, gửi kèm các lần thất bại trước, hỏi lại một lần nếu model lặp lại câu cũ. Pipeline cho tối đa 3 vòng (`max_repair_attempts`), dùng `quick_fix` trước | `execution/repair.py`, `runtime/pipeline.py` |
| xlsx: "12 columns passed, passed data had 11" làm mất bảng đơn hàng | openpyxl bỏ ô trống cuối dòng; bù cho đủ độ rộng tiêu đề | `ingest/loader.py` |
| Gate chặn nhầm công nợ/giá vốn/hạn dùng khi lớp chuẩn nhận vai trò sai | Thêm `column_names` cho 3 khái niệm: chỉ kết luận "thiếu" khi dữ liệu thô cũng không có cột gợi ý | `configs/schema_roles.yaml` |
| T4 chạy 3000 câu quá lâu | `--max-per-business N` (mẫu xác định, N câu đầu mỗi business); `eval --logged-only` chấm đúng tập đã chạy; notebook mặc định mẫu 8 câu/business | `runtime/runner.py`, `runtime/cli.py`, `dataparallel.py`, notebook |

Đo trên log cũ (dữ liệu tổng hợp): `quick_fix` sửa được 18/39 lỗi thực thi lần đầu, cả 18 chạy được, 11 ra đúng đáp án (trước đó cả 18 abstain).

## Còn lại — việc lớn nhất
**Lớp chuẩn (Phase 3) chưa hiểu dữ liệu chính thức.** Mỗi business là một kiểu xuất file POS khác nhau (tên cột tiếng Việt như `Mã hóa đơn`, `Thời gian`, `Trạng thái`; ngày lẫn `01/02/2025`, số serial Excel và `1 thg 6 2025`; số lượng `1 cái`; mỗi tháng một sheet; bảng quy đổi đơn vị; sổ quỹ; phiếu giao hàng).
Khi không ghép đủ vai trò, prompt dùng schema thô và README bị cắt ở 2000 ký tự, trong khi README chứa thông tin quyết định (quy đổi đơn vị, ý nghĩa cột, quy ước nợ).
- Ví dụ prompt thô: `biz_115` ≈ 36 000 ký tự (16 bảng, mỗi tháng một sheet) vượt `max_model_len: 8192` trên T4 → câu đó abstain; `biz_106` ≈ 16 700.
- Hướng làm: đọc **README của từng business** (`- **Cột**: ý nghĩa`) để gán vai trò (đơn giá, trạng thái đơn, tên hàng, ngày bán, số lượng quy đổi, thành tiền sau giảm, mã/tên khách), thống nhất ngày/tiền/số lượng, gộp các sheet theo tháng, đọc bảng quy đổi đơn vị, và 4 trạng thái đơn của rulebook §8.
- Chưa làm: gate "kỳ nằm ngoài khoảng dữ liệu" (nguồn chính của 70 câu unanswerable) cho business chưa có lớp chuẩn; `weekday_vi`, `v_inventory`, giá vốn theo dòng bán (rulebook §5), đơn vị cơ bản.
