# 17. Phase 4 / P1 — Sửa hình dạng đáp án (từ lần chạy LLM thật đầu tiên)

Số đo thật đầu tiên (Kaggle T4, Qwen2.5-Coder-7B-AWQ, `dataset/train` 320 câu, `dev` 120 câu):

| | Trước P0 | P0 train | P0 dev |
|---|---|---|---|
| Accuracy | 0,10 | 0,622 | 0,625 |

Chạy lại hai lần cho kết quả giống 100%; 1 GPU và 2 GPU (data parallel) lệch 1/320 câu.
Khoảng 36 câu sai nhưng **SQL và kết quả đã đúng**: lỗi nằm ở bước quyết định hình dạng đáp án, không phải ở LLM hay dữ liệu.

## Đã sửa
| Lỗi | Sửa | File |
|---|---|---|
| Top-N (`top3_qty`, `top3_revenue`): model SELECT thêm cột số lượng/doanh thu nên formatter đòi list một cột và abstain | List lấy **cột đầu** (thực thể), giữ nguyên thứ tự `ORDER BY` | `formatting/formatter.py` |
| "Khách nào…nhất" trả bảng 2 cột (tên, tổng) → kiểu `table`, gold là `string` | `Candidate.meta["expected_type"]` (đặt ở `apply_expected`); khi mong `string`, kết quả **một dòng nhiều cột** lấy cột đầu. Nhiều dòng vẫn ra `table` (không đoán). Scalar số không bị đổi kiểu | `codegen/generator.py`, `formatter.py` |
| `intent_keywords.top1/bottom1` chỉ khớp khi "nhiều nhất" liền nhau, nên "mua nhiều tiền nhất", "nhiều đơn hàng hợp lệ nhất" không được nhận | Cho phép tối đa 4 từ xen giữa; `date_of_max` ("ngày nào…") vẫn thắng vì khai báo trước | `configs/rules_defaults.yaml` |
| "Thứ mấy …" trả số (`EXTRACT(DOW …)`), gold là "Thứ sáu"… | Cột `weekday_vi` (Thứ hai … Chủ nhật) trong `v_valid_orders` và `v_sales`; câu "thứ mấy" có `expected = string`; system prompt dặn dùng `weekday_vi` | `ingest/canonical.py`, `linking/schema_linker.py`, `codegen/prompt_builder.py` |

Hệ quả phụ: `top1/bottom1` rộng hơn nên gate "kỳ rỗng khi hỏi top 1" (`UNDEFINED_ON_EMPTY`) áp dụng cho nhiều câu hơn (đúng ngữ nghĩa).

## Đo (không cần GPU)
`scripts/replay_format.py` chấm lại một lần chạy đã xong bằng **code hiện tại**: dùng lại SQL và kết quả trong log, chạy lại understand → link → gate → format rồi chấm.
```
python scripts/replay_format.py <result_dir> <data_dir> --answers <answers.jsonl> [--meta questions_meta.jsonl]
```
Trên log Kaggle P0: train 0,622 → **0,694** (199 → 222/320), dev 0,625 → **0,692** (75 → 83/120); `top3_revenue` 0 → 9/9, `top_customer` 0 → 8/8, `top3_qty` 0 → 6/9;
không template nào giảm. Replay **không** đo được `top_weekday` (cần SQL mới dùng `weekday_vi`, phải chạy lại LLM) và mọi thay đổi làm đổi SQL.

## Còn lại (nhóm lỗi tiếp theo)
- `growth` 0/19: 17 câu abstain vì SQL thiếu `FROM` (binder error, repair 8/70 lần thành công) → repair có thông tin lỗi + kiểm tra sqlglot + N ứng viên/vote.
- `aov` 0/10 (trung bình theo dòng thay vì theo đơn), `low_stock`/`slow_high_stock`/`near_expiry` (chưa có view tồn kho), `profit` (giá vốn bình quân nhập lô), `bottom_qty`, `cancel_count`, `best_day`, `debt_table`: cần rulebook/định nghĩa nghiệp vụ xác nhận trước khi sửa view.
