# 15. Phase 3 — Lớp ngữ nghĩa chuẩn, Entity/Schema Linking, Gate luật

Thiết kế gốc: [04_entity_schema_linking.md](04_entity_schema_linking.md) và [05_answerability_gate.md](05_answerability_gate.md).
Phase này làm theo một nhận xét từ dữ liệu: câu hỏi nhắc tên thực thể cụ thể rất ít (khoảng 17 trên 440 câu), còn điểm nghẽn thật là
**schema và dữ liệu bẩn**: ba bộ tên bảng/cột, ngày lẫn ISO và `DD/MM/YYYY`, tiền là chuỗi có dấu nhóm nghìn, dòng bán trùng `dong_id`,
đơn hủy hoặc có dòng trả hàng. Vì vậy LLM không còn đọc bảng thô: nó viết SQL trên các view chuẩn, đã khử trùng và đã áp quy tắc rulebook.

## Luồng
`ingest` (tạo view chuẩn + chỉ mục thực thể) → `understand` (dùng `protected_values` đầy đủ) → `link` (thực thể + schema + cờ) →
`gate` (luật) → `generate` (prompt có view, thực thể, kiểu đáp án) → thực thi → `format_answer`.

## 3.1 Lớp ngữ nghĩa chuẩn (`ingest/canonical.py`)
- **Role mapping** (`map_roles`): nhận diện vai trò products, customers, orders, lines, purchases, debts từ tên bảng và tên cột.
  Tên được chuẩn hóa (tách camelCase và snake_case, bỏ dấu, chữ thường): `MaSP` → `ma sp`, `ChiTietDon` → `chi tiet don`.
  Từ đồng nghĩa nằm trong `configs/schema_roles.yaml`, không nằm trong code. Các dòng ánh xạ của README
  (như `` `OrderID` = `ma_don` ``) tự thêm đồng nghĩa. Một vai trò chỉ được gán khi đủ **mọi cột bắt buộc**; mỗi bảng chỉ giữ một vai trò;
  chọn theo điểm giảm dần rồi theo tên để ổn định. Tên bảng chỉ là điểm cộng, cột mới quyết định.
- **View chuẩn** (`v_products, v_customers, v_orders, v_lines, v_purchases, v_debts`): cột tên cố định, kiểu sạch.
  Ngày parse nhiều định dạng (ISO, `DD/MM/YYYY`; tự phát hiện `MM/DD` nếu dữ liệu chứng minh), tiền như `1.558.000`, `8,225,850`, `12,5`, `149000đ`,
  boolean `true/1/có`, khử trùng theo khóa id giữ dòng đầu (theo `rowid`).
- **View nghiệp vụ** theo rulebook của split (`business_flags`, JSON trong rulebook thắng `configs/rules_defaults.yaml` mục `business:`):
  `v_valid_orders` loại đơn hủy và (tùy cờ) cả đơn có dòng trả hàng; `v_sales` gồm dòng của đơn hợp lệ với `line_revenue = max(qty*unit_price - discount, 0)`
  và `revenue` đã xử lý voucher (phân bổ theo tỉ lệ), VAT, ship theo cờ.
- **Capabilities** (`has_customers, has_debts, has_cost, has_expiry, date_range`): `True`, `False` hoặc `None`. `None` nghĩa là lớp này không kết luận được
  (không map được business) và khi đó **không có gì bị chặn**. Hạn dùng chỉ tính là có khi có ít nhất một ngày hợp lệ; giá vốn khi có ít nhất một `unit_cost`.
- Mọi view tạo trong DuckDB tạm lúc ingest; sandbox vẫn chỉ cho một câu SELECT, chỉ đọc.
- **Sửa loader**: CSV trước đây để pandas tự suy kiểu nên `10.000` hoặc `149.000` thành `10.0` và `149.0`, sai 1000 lần. Nay CSV đọc dạng chuỗi và
  chỉ đổi sang số khi không mơ hồ (`coerce_csv_types`); cột có số nhóm nghìn, số có số 0 đứng đầu (điện thoại, mã) hoặc nội dung hỗn hợp giữ dạng chuỗi.

## 3.2 Entity index và linker (`linking/entity_index.py`, `entity_linker.py`)
- **Index** mỗi business một lần: sản phẩm (SKU, tên chuẩn, mọi alias lấy từ `display_name` của dòng bán, nên biến thể chữ hoa, NFD, mất dấu gộp về **một** thực thể),
  khách (mã, tên), nhóm hàng (gộp biến thể mất dấu hoặc thừa khoảng trắng, chọn cách viết có dấu). Khóa: NFC, bỏ dấu, chữ thường, token chữ số.
  `context.protected_values` là tên và alias, được `understand` dùng để không sửa tên thực thể.
- **Quét khớp chính xác** theo n-gram dài nhất trên khóa không dấu. Khớp **một từ** chỉ được tính khi là mã có chữ số, hoặc đứng ngay sau từ gợi ý
  cùng loại (`sản phẩm Trà` không được khớp nhóm hàng `Trà`).
- **Mã dính** (`KháchC0001`): chữ cái sát dãy số khớp một mã.
- **Từ gợi ý** (`sản phẩm`, `mặt hàng`, `khách`, `nhóm hàng`...): văn bản sau đó đến một từ kết thúc (danh sách ngắn trong config) là một mention.
  Mention được giải bằng rapidfuzz: điểm = nửa độ giống chuỗi (kể cả hoán vị ký tự, tính bằng Damerau-Levenshtein) cộng nửa độ phủ token hai chiều;
  mọi token có chữ số (`330ml`, `d21`) phải khớp **chính xác**. Chọn khi điểm ≥ 0,85 và hơn ứng viên thứ hai ≥ 0,05;
  từ 0,70 là `ambiguous` (giữ top ứng viên); dưới đó là `missing`.
- `missing_entity` chỉ được báo khi mention trông như tên riêng (có token lẫn chữ và số, hoặc có từ ngoài từ vựng và ngoài vốn từ của business).
  Cụm chung như "sản phẩm tồn kho" không bao giờ thành `missing_entity`.
- Khoảng thời gian đã giải (`Period.mention`) bị che trước khi tìm thực thể. Tie-break cố định: điểm giảm, loại thực thể, rồi id tăng.

## 3.3 Schema linker (`linking/schema_linker.py`) và gate (`gate/__init__.py`)
- `detect_needs`: khái niệm câu hỏi cần (`debt`, `cost`, `expiry`, `employee`, `utilities`) bằng từ khóa trong `configs/schema_roles.yaml` mục `concepts:`.
  Khái niệm thiếu khi capability là `False` và không cột thô nào có tên khớp `column_names`. Chỉ xét khi business đã map đầy đủ (`complete`).
- `period_outside_data`: kỳ primary nằm hoàn toàn ngoài `date_range` của đơn hàng (chỉ khi câu hỏi dùng dữ liệu bán hàng).
- `expected_answer`: kiểu đáp án suy từ `intent_hints`. `force_type` chỉ bật khi hình dạng kết quả không đủ để suy (percent, list, table);
  đơn vị `VND` hoặc `count` làm formatter làm tròn nguyên. Các kiểu còn lại để formatter suy từ kết quả.
- `gate`: `unanswerable` khi có `missing_entity`, `missing_capability` hoặc `period_outside_data`, kèm lý do tiếng Việt.
  `ambiguous` và mọi lỗi ánh xạ **không chặn** (chặn nhầm câu trả lời được tệ hơn bỏ sót câu không trả lời được).
- `LinkResult` có thêm `entities`, `schema`, `flags`; nhật ký mỗi câu có khóa `linking`. `link_stub` và `gate_stub` còn là alias.

## 3.4 Prompt, formatter, scorer
- `codegen/prompt_builder.py`: khi có lớp chuẩn, `schema` là mô tả view (tên, kiểu, ý nghĩa cột, capabilities, quy tắc hiệu lực) thay cho profile thô, kèm
  `linked_entities` (id và tên chuẩn nguyên văn) và `expected_answer`; có chỉ dẫn chỉ dùng view `v_*`. Không có lớp chuẩn thì giữ schema thô như trước.
- `codegen/generator.py` (`apply_expected`, dùng cả cho repair): điền `answer_type` và `unit` cho candidate khi backend chưa đặt.
- `formatting/formatter.py`: tổng hoặc đếm (đơn vị VND, count) trên kỳ không có dòng nào cho `NULL`, được hiểu là `0` (đáp án gold của bộ sinh là 0).
- `eval/scorer.py`: đọc khóa `alias` của gold (trước đây chỉ đọc `aliases` nên alias không bao giờ khớp).

## Chạy và mở rộng
```
python -m pytest
python scripts/eval_linking.py        # role mapping, gate, entity linking theo loại nhiễu (đọc synth ở mức script)
python -m datamate.cli run --data-dir dataset/train --result-dir result/train_p3
```
- **Từ đồng nghĩa mới** cho tên bảng/cột: sửa `configs/schema_roles.yaml` mục `roles:`. Cột bắt buộc là điều kiện để gán vai trò.
- **Khái niệm mới** cần có trong dữ liệu (ví dụ "bảo hành"): thêm vào `concepts:` với `keywords`, `capability` (hoặc `null`) và `column_names`.
- **Quy tắc nghiệp vụ mới**: thêm khóa vào `BUSINESS_KEYS` và `business:` trong `configs/rules_defaults.yaml`, rồi dùng trong SQL của view.

## Kết quả đo (train và dev)
- Role mapping: đúng toàn bộ vai trò và cột của 11 business ở cả 3 định dạng.
- View chuẩn đối chiếu `Dataset` của bộ sinh trên các business CSV (cả dev có trừ voucher): doanh thu, số lượng, số đơn hợp lệ và số dòng khớp tuyệt đối.
- Gate trên train: chặn đúng 32 trên 32 câu `unanswerable`, 0 chặn nhầm. Dev: chặn đúng 12 câu probe (4 mỗi business).
- Chỉ với gate, backend mock đạt 32 đúng, 0 sai trên train (288 câu còn lại là abstain vì mock không sinh SQL).
- Entity linking trên câu tổng hợp có nhiễu (in-sample): mã 100%; tên sản phẩm 98,8%, alias 97,4%, tên khách 93,6%; tên không tồn tại bị chặn 66/66.
  Lỗi hoán vị ký tự trong từ dài còn 87%, lỗi dính hoặc tách khoảng trắng 94,6%. Số này tái lập giữa các lần chạy (hạt giống cố định).

## Hạn chế đã biết
- Chỉ xử lý business có đủ vai trò `orders` và `lines`; bảng phẳng một sheet chưa được hỗ trợ (khi đó không có view và không có gì bị chặn).
- Tồn kho và hàng sắp hết hạn chưa có view riêng; LLM tính từ `v_purchases` và `v_sales`.
- Khái niệm chi phí vận hành, nhân viên chỉ nhận qua từ khóa; từ ngoài danh sách sẽ không bị chặn.
- Chưa dùng embedding (BGE-M3). Chưa kiểm tra tính nhất quán dữ liệu (ví dụ SKU có trên dòng bán nhưng không có trong bảng sản phẩm).
- Đo entity là in-sample với nhiễu của chính bộ sinh; nhiễu thật có thể khác.

## Phase 4 cần gì
Số đo end-to-end với LLM thật trên Kaggle trước và sau Phase 3 (chưa chạy trong phiên này), few-shot theo từng loại câu hỏi dùng `schema.expected` và `linked_entities`,
nhiều ứng viên và voting theo kết quả thực thi, kiểm tra cú pháp bằng sqlglot, và gate theo dữ liệu (ví dụ kỳ trước bằng 0 khi tính tăng trưởng, kỳ rỗng khi hỏi top 1).
