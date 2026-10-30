# 14. Phase 2 — Question Understanding (chạy, mở rộng, hạn chế)

Chi tiết hành vi và danh sách giả định: [03_question_understanding.md](03_question_understanding.md).

## Chạy test và báo cáo
```
python -m pytest                          # toàn bộ (mock backend, CPU)
python -m pytest tests/test_temporal.py tests/test_normalizer.py tests/test_understanding.py
python scripts/eval_understanding.py      # độ phủ thời gian, token thời gian chưa khớp, tỉ lệ đổi, phục hồi theo loại nhiễu
python -m datamate.cli run --data-dir dataset/train --result-dir result/train_p2
```
Sau lần chạy cuối, mỗi bản ghi trong `result/train_p2/logs/questions.jsonl` có khóa `understanding`
(`normalized`, `normalized_ascii`, `periods`, `intent_hints`, `rule_params`, `warnings`).
Số phục hồi theo loại nhiễu là **in-sample**: lexicon có từ vựng mẫu câu của chính bộ sinh. Dùng báo cáo để tìm lỗ hổng rule,
không tinh chỉnh theo id câu hỏi.

## Mở rộng
- **Teencode**: thêm vào `data/teencode_dict.json` dạng `"cụm chuẩn": ["biến thể", ...]`. Tránh viết tắt mơ hồ
  (ví dụ `dt` có thể là doanh thu hoặc điện thoại). Biến thể trùng giữa hai cụm chuẩn sẽ bị loại và test sẽ báo.
  Biến thể chỉ là dạng bỏ dấu của cụm chuẩn không cần thêm, lexicon đã phục hồi.
- **Từ vựng**: thêm từ/cụm có dấu vào `data/vi_business_words.txt` (mỗi dòng một mục, chữ thường), rồi chạy
  `python scripts/build_lexicon.py` để sinh lại `data/vi_lexicon.txt` (`--check` kiểm tra file có cũ không; test cũng kiểm).
  Muốn một khóa không dấu **không bao giờ** được đoán, thêm vào `data/vi_homographs.txt`, hoặc thêm các dạng có dấu khác
  của khóa đó vào từ vựng để khóa trở nên mơ hồ.
- **Biểu thức thời gian**: thêm mẫu vào `_PATTERNS` trong `understanding/temporal.py` (cụ thể đứng trước chung) kèm
  dòng trong bảng `test_expressions`. Giả định mới phải thành tham số có tên trong `configs/rules_defaults.yaml` mục `time:`.
- **Intent**: thêm regex (trên văn bản không dấu) vào `intent_keywords` trong `configs/rules_defaults.yaml`.

## Hạn chế đã biết
- "ngày D" đứng một mình, thứ trong tuần ("thứ hai tuần rồi"), "đầu/cuối tháng", "cùng kỳ" cho tuần hoặc quý chưa được hỗ trợ.
- Số bằng chữ chỉ có tập nhỏ (một..mười, mười một, mười hai, mười lăm, hai mươi, ba mươi).
- Lịch Tết chỉ lấy từ `calendar.csv` (cờ hoặc cột âm lịch). Không có calendar thì không có Period cho Tết.
- `protected_values` hiện chỉ lấy từ tối đa 5 mẫu mỗi cột trong profile; tên thực thể ngoài mẫu vẫn có thể bị sửa
  nếu trùng từ trong lexicon. Từ điển giá trị đầy đủ thuộc Phase 3.
- Lexicon nhỏ (khoảng một nghìn mục), nên khôi phục dấu chủ yếu phủ từ vựng kinh doanh phổ biến và từ vựng mẫu câu.
  Từ ngoài lexicon được giữ nguyên.
- Lỗi gõ chồng nhiều loại lên một từ (ví dụ vừa dính từ vừa hoán vị) thường không phục hồi được.
  Lỗi hoán vị chỉ xét token từ 5 ký tự và cần đúng một từ khớp.
- Các từ chỉ thời gian trong tên sản phẩm có thể bị coi là mốc thời gian nếu tên đó không nằm trong vùng bảo vệ.
- Số nguyên bằng chữ trong `top N` ("ba mặt hàng") chỉ nhận khi theo sau là danh từ trong danh sách (`mặt hàng`, `sản phẩm`, `nhóm hàng`...).

## Phase 3 (Entity/Schema Linking) cần gì từ `ResolvedQuestion`
- `normalized` và `normalized_ascii` để so khớp thực thể (so khớp không dấu song song, vì khôi phục dấu có thể sai).
- `remove_mentions(normalized, periods)` để loại từ chỉ thời gian trước khi tìm thực thể.
- `intent_hints` (metric, operation, `top_n`) để chọn cột, thước đo và dạng phép tính.
- Từ điển giá trị đầy đủ của mỗi business (mở rộng profiler) truyền vào `understand(..., protected_values=...)`
  để bảo vệ tên thực thể ngay từ chuẩn hóa.
- `warnings` (`outside_calendar_range`, `future_period`, `tet_window_not_found`, `understanding_error`) cho Answerability Gate quyết định `unanswerable` hay `abstain`.
