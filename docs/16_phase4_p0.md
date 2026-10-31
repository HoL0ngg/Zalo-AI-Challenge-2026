# 16. Phase 4 / P0 — Nền tảng tương tác với model

Thiết kế gốc: [06_code_generation.md](06_code_generation.md), [09_models.md](09_models.md). P0 không đổi kiến trúc; nó sửa cách LLM được gọi
và thêm công cụ **đo** để các thay đổi sau (few-shot, voting, LoRA) được đánh giá bằng số.

## Đã làm
| Mục | File | Nội dung |
|---|---|---|
| Chat template | `llm/vllm_backend.py` (`render_chat`) | Gọi `tokenizer.apply_chat_template` với `system` + `user` thay cho chuỗi thô. `enable_thinking` (khai báo trong `models*.yaml`, mặc định `false`) chỉ có tác dụng với template kiểu Qwen3. |
| System prompt | `codegen/prompt_builder.py` (`SYSTEM_PROMPT`) | Vai trò, định dạng `<sql>…</sql>`, checklist (chỉ dùng cột có trong schema, dùng ngày đã giải nguyên văn, hình dạng kết quả khớp formatter, % đơn vị phần trăm, tie-break theo rulebook). Tie-break **không** gán cứng: theo rulebook của split, nếu rulebook im lặng thì theo mã tăng dần. |
| Parser đầu ra | `codegen/sql_parser.py` (`extract_sql`) | Thứ tự: thẻ `<sql>` → khối ``` → từ khóa `WITH/SELECT` đầu tiên. Thẻ không đóng (bị cắt) vẫn lấy được; bị cắt giữa `<think>` thì trả rỗng. Backend dừng ở `</sql>` (stop sequence). |
| Log kiểm toán | `core.Candidate.meta` | `raw_output`, `finish_reason` (`length` = bị cắt bởi `max_tokens`), `prompt_tokens`; được ghi trong `attempts[*].candidate.meta` của log từng câu. |
| `max_tokens` | `configs/models*.yaml` | 768 (trước đây 512 cứng trong code). |
| Thu gọn prompt | `prompt_builder.py` | `compact_schema`: mỗi cột một chuỗi `"name TYPE: meaning"`, bỏ `roles` (tên bảng/cột thô, chỉ dụ model bỏ qua view). `readme` ≤ 2000, `rulebook` ≤ 3000 ký tự, tổng ≤ 16000 ký tự (bỏ readme, rồi cắt rulebook; không bao giờ bỏ schema/kỳ/câu hỏi). Phần ổn định theo business đứng trước, phần đổi theo câu đứng sau để prefix caching dùng được. |
| Báo cáo theo bước | `eval/report.py`, `datamate report` | Xem dưới. |
| Đo prompt | `scripts/measure_prompts.py` | Kích thước prompt (ký tự, hoặc token nếu có `--tokenizer`) không cần model. |

Đo trên `dataset/train` (288 câu qua gate): prompt (kèm system) trung bình **11.0k → 8.3k ký tự**; readme và rulebook của dữ liệu hiện tại
chưa chạm trần cắt (readme ~0,8k, rulebook ~2,1k), nên trần chỉ là lưới an toàn cho business lớn hơn ở private test.
Schema vẫn chiếm phần lớn (~2/3). Số token thật phải đo bằng tokenizer của model (`--tokenizer`) trên máy có weights.

## Báo cáo theo bước
```
python -m datamate.cli run --config configs/kaggle.yaml --data-dir dataset/train --result-dir result/train_p0
python -m datamate.cli report result/train_p0 dataset/train/answers.jsonl \
       --meta synth/out/.debug/train/questions_meta.jsonl      # --meta: thêm accuracy theo template
```
- `stages`: số câu đi tới từng bước (`gated`, `generated`, `sql_extracted`, `exec_ok`, `repaired_ok`, `answered`, `correct`) và `rates_over_generated`.
- `failures`: nhóm lỗi duy nhất cho mỗi câu sai — `wrong_value`, `wrong_type`, `wrongly_blocked`, `should_be_unanswerable`,
  `abstain:no_sql_in_reply`, `abstain:exec_{syntax,binder,catalog,conversion,timeout,other}`, `abstain:format_or_sanity`, `abstain:generation_error`, `abstain:no_attempt`.
- `exec_errors`: mọi lỗi thực thi (kể cả lỗi sau đó được repair); `finish_reasons`/`prompt_tokens`/`latency_seconds` để thấy cắt cụt, độ dài prompt và tốc độ.
- `precision_when_answered`: đúng / số câu có trả lời (loại câu chặn bởi gate), dùng khi hiệu chỉnh ngưỡng abstain sau này.

## Hạn chế / việc tiếp theo (P1)
- Repair vẫn là một lượt, nối vào prompt cũ; chưa có `EXPLAIN`/sqlglot và sanity check sau thực thi.
- Chưa few-shot, chưa N ứng viên/voting, vLLM vẫn chạy batch = 1.
- Chưa có số đo với LLM thật sau P0 (cần GPU/Kaggle): chạy lệnh trên rồi so với lần chạy trước P0 bằng cùng `report`.
- Backend chưa được kiểm thử với vLLM thật trong phiên này; phần dựng chat/parse có test CPU (`tests/test_model_interface.py`). Cần xác nhận `get_tokenizer()` và `stop=["</sql>"]` trên phiên bản vLLM sẽ dùng.
