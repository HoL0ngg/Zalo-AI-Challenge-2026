# 03. Bước 2 — Question Understanding

Gồm hai phần nối tiếp: **Normalizer** rồi **Temporal Resolver**, cộng một lớp **intent hints** nhẹ.
Không dùng LLM, hoàn toàn deterministic. Câu hỏi gốc (`ResolvedQuestion.question`) luôn được giữ nguyên.
Hàm vào: `datamate.understanding.understand(question, context) -> ResolvedQuestion`
(`understand_stub` còn là alias tương thích ngược). Mọi lỗi bên trong được bắt, ghi vào `warnings`
(`understanding_error:<stage>:...`) và quay về bản pass-through; một câu không bao giờ làm sập lượt chạy.

## 2a. Vietnamese Normalizer (`understanding/normalizer.py`)
Mục tiêu: đưa câu hỏi nhiễu về tiếng Việt chuẩn mà **không đổi ý định**. Nguyên tắc: **sửa ít còn hơn sửa sai**;
chỉ đổi khi kết quả là từ đã biết hoặc khôi phục duy nhất từ lexicon. Kết quả là điểm bất động
(`normalize(normalize(x)) == normalize(x)`).

Thứ tự các bước:
1. **Làm sạch**: NFC, bỏ ký tự điều khiển/độ rộng bằng 0, gộp khoảng trắng.
2. **Đánh dấu vùng bảo vệ** (không bao giờ sửa): mã chứa chữ số (`P0017`, `SKU12ab`) và các giá trị thực thể
   trong `protected_values` (so khớp không phân biệt hoa/thường và dấu; giá trị dưới 3 chữ cái bị bỏ qua).
   `understand()` lấy giá trị từ `profile[...]["samples"]` của các cột chuỗi (tối đa 5 mẫu mỗi cột).
   Từ điển giá trị đầy đủ sẽ có ở Phase 3.
3. **Teencode/viết tắt** theo `data/teencode_dict.json` (token/cụm, khớp dài nhất trước, không phân biệt hoa/thường):
   `sp→sản phẩm`, `dc/đc→được`, `ko/k/hok→không`, `bn/bnh→bao nhiêu`, `hnay→hôm nay`, `nhìu→nhiều`, `%→phần trăm`.
   `k` sau một số (`5 k`) và `%` dính số (`10%`) không bị đổi. Viết tắt mơ hồ (`dt`, `cn`) bị loại có chủ đích.
4. **Sửa từng token** (chỉ khi từ chưa biết): gộp ký tự lặp (3 ký tự trở lên luôn gộp; 2 ký tự chỉ gộp khi ra từ đã biết,
   nên `xoong` được giữ); bảng typo explicit nhỏ (`thnags→tháng`); hoán vị hai ký tự kề nhau, bỏ phím thanh Telex ở cuối
   (`thangs`), `dd→đ`, chỉ nhận khi ra đúng một từ trong lexicon; tách từ dính (`Trongdịp`, `Nhânviên`) khi có đúng một cách
   tách thành hai từ đã biết.
5. **Khôi phục dấu theo cụm**: quy hoạch động chọn cách phủ câu bằng các cụm duy nhất sao cho phủ nhiều token nhất
   (tránh cụm dài nuốt đầu cụm sau). Token có dấu phải khớp đúng, token không dấu khớp theo `fold`.
6. **Khôi phục dấu từng từ**: chỉ cho token ASCII, khóa phải ứng với đúng một từ trong lexicon và không nằm trong
   `data/vi_homographs.txt` (`ban`, `co`, `do`, `la`, `chua`... luôn giữ nguyên nếu không có cụm xác nhận).
7. Từ đã biết viết toàn chữ hoa được hạ thường; token không đổi giữ nguyên hoa/thường, token được sửa xuất ra chữ thường.
8. `normalized_ascii = fold(normalized)`: bỏ dấu, `đ→d`, lowercase, **cùng độ dài** với bản có dấu
   (để regex chạy trên bản không dấu rồi cắt văn bản gốc cùng vị trí).

Dữ liệu: `data/teencode_dict.json` (dạng `canonical -> [variants]`, bản chép từ synth và mở rộng; `src/` không import synth),
`data/vi_lexicon.txt` (sinh bởi `scripts/build_lexicon.py` từ canonical của teencode, `data/vi_business_words.txt` và từ vựng
mẫu câu của bộ sinh), `data/vi_homographs.txt`. Biến thể teencode chỉ là dạng bỏ dấu của canonical được chuyển sang kênh
lexicon (cần kiểm tra tính duy nhất) thay vì thay thế vô điều kiện; biến thể trùng giữa hai canonical bị loại.

## 2b. Temporal Resolver (`understanding/temporal.py`, hàm thuần)
Đầu vào: câu đã chuẩn hóa, `as_of_date`, `calendar.csv` của split, tham số hiệu lực.
Khoảng ngày luôn **inclusive**. Regex chạy trên `fold(text)` nên không phụ thuộc dấu; mỗi `Period.mention` cắt từ văn bản chuẩn hóa.
Các mẫu sắp xếp từ cụ thể đến chung và đánh dấu vùng đã dùng (để `cùng kỳ năm ngoái` không bị `năm ngoái` ăn mất).

### Tham số hiệu lực (`rule_params`)
`parse_rule_params(rulebook, defaults)`: khối JSON máy đọc được trong `rulebook.md` **của split đang trả lời** luôn thắng
`configs/rules_defaults.yaml`. Khóa `week_start` có fallback văn xuôi (`Tuần: Chủ nhật–Thứ bảy`, `Weeks start Monday`).
Giá trị sai kiểu → dùng mặc định và phát `rulebook_param_invalid:<key>`. `rule_params["rule_sources"][key]` ∈
`rulebook | rulebook_prose | default` để truy vết.

| Tham số | Mặc định | Nguồn |
|---|---|---|
| `week_start` | monday | rulebook (dev đặt sunday) |
| `month_to_as_of` | true | rulebook |
| `tet_lunar_start`, `tet_lunar_end` | `12-23`, `01-10` | rulebook |
| `this_week_mode` | `week_to_date` | **ASSUMPTION** |
| `quarter_to_as_of`, `year_to_as_of` | true | **ASSUMPTION** |
| `rolling_window_includes_as_of` | true | **ASSUMPTION** |
| `bare_cung_ky` | `year` | **ASSUMPTION** |
| `pre_tet_days`, `post_tet_days` | 7, 7 | **ASSUMPTION** |

### Biểu thức hỗ trợ và ngữ nghĩa
| Biểu thức | Khoảng ngày |
|---|---|
| hôm nay / hôm qua / hôm kia | as_of / as_of−1 / as_of−2 |
| tuần này | ngày đầu tuần..as_of (`this_week_mode`) |
| tuần rồi, tuần trước, tuần vừa rồi | **tuần lịch** liền trước (không phải 7 ngày gần đây) |
| tháng này | ngày 1..as_of nếu `month_to_as_of`, ngược lại cả tháng |
| tháng trước, tháng rồi | cả tháng liền trước |
| tháng sau, tuần sau, quý sau | kỳ kế tiếp (kèm `future_period:<label>`) |
| quý này / quý trước | đầu quý..as_of / cả quý liền trước |
| năm nay / năm ngoái | 1/1..as_of / cả năm trước |
| cùng kỳ năm ngoái | ngày 1..cùng ngày năm trước, giới hạn cuối tháng (29/2 → 28/2) |
| cùng kỳ tháng trước | ngày 1..cùng ngày tháng trước, giới hạn cuối tháng |
| N ngày/tuần/tháng qua | `as_of−N+1..as_of` (`N` là số hoặc chữ nhỏ như "ba mươi") |
| N ngày/tuần/tháng tới | `as_of..as_of+N` (kèm `future_period`) |
| từ ngày X đến ngày Y | khoảng tường minh; thiếu tháng/năm bên trái lấy từ bên phải; đảo đầu cuối thì đổi chỗ + warning |
| ngày D tháng M [năm Y], dd/mm[/yyyy] | một ngày |
| tháng M, tháng M năm Y, tháng MM/YYYY | cả tháng (tháng hiện tại thì theo `month_to_as_of`) |
| quý Q [năm Y], năm YYYY | cả quý / cả năm |
| cuối tuần | Thứ bảy+Chủ nhật gần nhất đã kết thúc; "cuối tuần này" = cuối tuần của tuần hiện tại |
| Tết, dịp Tết gần nhất | cửa sổ Tết gần nhất có `end <= as_of` (suy từ calendar, không hard-code ngày dương) |
| trước Tết / sau Tết | `pre_tet_days` trước / `post_tet_days` sau cửa sổ Tết đó |
| "tính đến hôm nay", "đến nay" | từ bổ nghĩa, không tạo Period |

Tết: dùng cột `is_tet_window` hoặc `is_tet` nếu có, nếu không suy từ `lunar_month/lunar_day` và
`tet_lunar_start/end`. Nếu `as_of` nằm trong một cửa sổ thì dùng cửa sổ trước và phát
`as_of_inside_tet_window_using_previous`. Không có dữ liệu → không tạo Period, phát `tet_window_not_found`.

### Cặp so sánh
Thứ tự nhắc: mốc đầu là `primary`. Mốc đứng sau `so với`/`so sánh với` là `comparison`.
`so với <tuần|tháng|quý|năm> liền trước đó` và `kỳ trước` là kỳ liền trước của primary
(`previous_week` dịch 7 ngày, `previous_month`/`quarter`/`year` là cả kỳ trước, `previous_period` cùng độ dài ngay trước).
Nhiều mốc không có từ khóa so sánh → mốc sau là `comparison` kèm `multiple_periods_without_comparison_marker`.

### Danh sách ASSUMPTION (rulebook im lặng)
Mỗi giả định phát warning khi được dùng; giá trị thật của rulebook private có thể khác, nên chúng là tham số có tên.
1. "tuần này" = đầu tuần..as_of, nhất quán với "tháng này" (`this_week_mode`).
2. "quý này", "năm nay" tính đến as_of (`quarter_to_as_of`, `year_to_as_of`).
3. "N ngày qua" gồm cả as_of (`rolling_window_includes_as_of`); `tuần qua`/`tháng qua` không có số được hiểu là N=1 kèm `bare_rolling_window_assumes_one_unit`.
4. "cùng kỳ" đứng một mình = cùng kỳ năm ngoái (`bare_cung_ky`), kèm `ambiguous_cung_ky_assumed_year`.
5. Ngày/tháng không có năm: lấy năm của as_of, nếu rơi vào tương lai thì lùi một năm (`year_inferred_previous:*`, `year_inferred_current:*`).
6. "cuối tuần" = cặp Thứ bảy+Chủ nhật gần nhất đã kết thúc, không phụ thuộc `week_start`.
7. "trước Tết"/"sau Tết" = 7 ngày liền kề cửa sổ Tết (`pre_tet_window_is_assumption`, `post_tet_window_is_assumption`).
8. Tháng hiện tại nêu tường minh ("tháng 8" trong tháng 8) cũng tính đến as_of (`explicit_current_month_to_as_of`).
9. "kỳ trước" = cùng độ dài, ngay trước primary.

### Cảnh báo
`future_period:<label>` (end > as_of), `outside_calendar_range:<label>` (vượt phạm vi calendar, hữu ích cho Answerability Gate),
`invalid_date`, `range_endpoints_swapped`, `rulebook_json_unreadable`, `temporal_error:<pattern>:<Exception>`.

## 2c. Intent hints (`understanding/intent.py`)
Từ khóa trong `configs/rules_defaults.yaml` (`intent_keywords`), khớp trên `normalized_ascii`, thứ tự khai báo là thứ tự ưu tiên.
`intent_hints = {"metric": quantity|revenue|profit|debt|stock|expiry|none, "operation": top1|bottom1|topN|sum|count|exists|compare_percent|avg|date_of_max|none, "top_n": int|None}`.
Chỉ là gợi ý để prompt và các bước sau tham khảo, không quyết định cuối cùng. "ngày" không được tính là danh từ của `topN`
(vì `30 ngày qua` là cửa sổ thời gian).

## Đầu ra: `ResolvedQuestion`
`question` (bản gốc), `normalized`, `normalized_ascii`, `periods[]` (`Period(label, start, end, role, mention)`),
`intent_hints`, `rule_params`, `warnings`. Mọi trường mới đều có mặc định nên mã cũ vẫn chạy.
Mỗi câu được ghi vào log dưới khóa `understanding` (ngày dạng ISO) và đưa vào prompt codegen cùng chỉ dẫn
"use the provided dates; do not compute relative dates yourself".
`remove_mentions(text, periods)` bỏ các từ chỉ thời gian trước khi tìm thực thể (dùng ở Phase 3).

## Kiểm thử
`tests/test_temporal.py` (bảng biểu thức, biên ngày, năm nhuận, qua năm, tuần bắt đầu Chủ nhật, Tết, cặp so sánh, cảnh báo),
`tests/test_normalizer.py` (từng loại nhiễu, vùng bảo vệ, idempotent, NFC/NFD, tính toàn vẹn của dict/lexicon),
`tests/test_understanding.py` (determinism, fallback, intent, log, prompt, `src/` không import synth).
Báo cáo độ phủ: `python scripts/eval_understanding.py` (xem `docs/14_phase2.md`).
