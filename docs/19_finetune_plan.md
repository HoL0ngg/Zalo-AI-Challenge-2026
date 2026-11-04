# 19. Kế hoạch fine-tune và tối ưu tài nguyên (2×RTX 5090, 6 giờ, ≤ 15B, offline)

## Nguyên tắc
1. **Fine-tune sửa độ chính xác; test-time compute (N ứng viên + vote + repair) sửa độ ổn định.** Cần cả hai, và fine-tune làm trước vì nó quyết định N cần bao nhiêu.
2. **Chỉ fine-tune khi prompt đã đóng băng.** Mẫu SFT là cặp (prompt, SQL). Đổi lớp chuẩn, tên view hay khuôn prompt thì dữ liệu cũ vô dụng. Vì vậy thứ tự là: lớp chuẩn README (đang làm) → đóng băng prompt → sinh dữ liệu → huấn luyện.
3. **Luật chấm +1/−1** làm abstain có giá trị: trả lời khi độ đồng thuận ≥ ngưỡng (≈ 0,5–0,6), chỉnh trên tập giữ lại.
4. **Không dùng dữ liệu test** (kể cả public_test): chỉ train chính thức có đáp án.

## Dữ liệu: rejection sampling từ train chính thức (3000 câu, có đáp án, không có SQL gốc)
- Chạy model nền trên train với N=8 mẫu (nhiệt độ 0,6–0,8) và repair; thực thi; **giữ mẫu có kết quả khớp đáp án**. Nhiều mẫu đúng cho một câu thì giữ tối đa 2 (SQL ngắn nhất, khác nhau).
- Giữ cả cặp **lỗi → sửa đúng** (huấn luyện repair) và **đúng/sai cùng prompt** (DPO tùy chọn nếu còn thời gian).
- **Chia theo business, không theo câu**: 24 business huấn luyện, 6 giữ lại (private test có business chưa thấy). Báo cáo `points` (+1/−1) trên 6 business đó.
- Câu unanswerable (70/3000 ≈ 2%): đưa vào với đầu ra "abstain/unanswerable" rõ ràng, nhưng chủ yếu để gate (luật) xử lý, không để model đoán.
- Câu hỏi sinh ra từ vài chục khuôn: oversample các khuôn khó (growth, tồn kho, giá vốn) để không bị khuôn dễ lấn át.

## Mô hình và huấn luyện (vừa 2×32 GB, vừa ngân sách 15B)
| Chọn | Lý do |
|---|---|
| LLM 7–8B (Qwen2.5-Coder-7B hoặc Qwen3-8B), LoRA r=32–64 trên mọi lớp tuyến tính | 8B bf16 ≈ 16 GB + kích hoạt/optimizer của LoRA nằm gọn trong một 5090; còn lại ~6B tham số cho BGE-M3 (few-shot) |
| **Loss chỉ trên phần SQL** (che prompt) | prompt dài ~2,5k token, SQL ~150: không che thì học thuộc schema |
| 2–3 epoch, lr 1e-4 (LoRA), cosine, batch hiệu dụng 32 | 3000 mẫu × ~3k token ≈ 9M token/epoch ≈ 40–60 phút/epoch trên một 5090 (ước tính, cần đo) |
| Data parallel 2 GPU khi huấn luyện (DDP), không TP | 5090 không có NVLink |
| Sau huấn luyện: **gộp LoRA vào trọng số** rồi lượng tử FP8 | không tốn chi phí adapter lúc suy luận; số tham số không đổi (kiểm bằng `model_budget.py`) |
| 14B thay cho 8B chỉ khi đo thấy hơn rõ rệt trên 6 business giữ lại | 14B chiếm gần hết 15B, mất embedding, và LoRA 14B chậm gấp ~2 |
Prompt càng ngắn càng rẻ: rút gọn schema (đã làm) giảm cả thời gian huấn luyện lẫn độ trễ suy luận.

## Ngân sách 6 giờ lúc chấm
Điểm nghẽn thật **không phải GPU** mà là nạp dữ liệu: `biz_106` (xlsx 100k dòng) mất ~50 giây, 30 business ≈ 10 phút tuần tự.
- Nạp và dựng view cho mọi business **song song** (process pool, 512 GB RAM đủ) **trong lúc** model đang load lên GPU; cache DuckDB ở `/work`.
- Hai replica vLLM (data parallel), prefix caching, CUDA graph bật, FP8; sắp xếp prompt theo business để dùng lại tiền tố.
- Kế hoạch cố định (không phụ thuộc đồng hồ, để tái lập ≤ 0,03): Pass 1 N=1 → ghi `submission.jsonl` đầy đủ; Pass 2 N=8 + repair; Pass 3 chỉ cho câu bất đồng. Đồng hồ chỉ cắt đuôi khẩn cấp ở ~5h15.

## Thứ tự làm
1. Xong lớp chuẩn README và đạt tỉ lệ khớp đáp án cao trên 30 business (đang ~90% ở các business đã sửa).
2. Chạy base model trên train (Kaggle hoặc máy chấm) lấy log; đóng băng prompt.
3. `scripts/build_sft_data.py`: log + đáp án → JSONL hội thoại (chỉ mẫu đúng); chia theo business.
4. Huấn luyện LoRA; đo `points` trên 6 business giữ lại, so với base + vote.
5. Chỉnh N và ngưỡng abstain trên cùng tập đó; đóng băng; chạy hai lần kiểm tái lập.

SFT và script QLoRA đã có trong repo. Pass N ứng viên + vote vẫn chưa triển khai (`voting/` là `vote_stub`);
`candidate_count` trong config chưa làm pipeline sinh nhiều ứng viên. Không tăng N trong YAML rồi kỳ vọng có voting.

## Lần chạy Kaggle 03/11/2026: chẩn đoán từ log

Nguồn: `kaggle_log/zalo-ai-challenge (3).log`, T4 16 GB ×2, source remote `43b407b`.
Working tree local lúc kiểm tra là `ce9342c`, vì vậy code trên Kaggle và code local **khác nhau**.
Log đã có cách đổi warmup sang `warmup_steps`; script local vẫn dùng `warmup_ratio`.

Lỗi dừng chính xác ở dòng 686/698 của log:
`TypeError: TrainingArguments.__init__() got an unexpected keyword argument 'group_by_length'`.
Transformers 5.16.1 không nhận đối số cũ này. Cả hai rank đã nạp xong trọng số rồi mới lỗi;
traceback này không cho thấy CUDA OOM, cũng chưa có bằng chứng đã chạy được bước optimizer nào.
Các cảnh báo pip xung đột thư viện có sẵn trên Kaggle và FA2 không hỗ trợ T4 không phải nguyên nhân
của traceback trên: vLLM đã fallback sang TRITON_ATTN và chạy xong baseline.

| Số đo baseline trên train chính thức | Kết quả |
|---|---:|
| Câu hỏi | 3.000 |
| Đúng | 1.156 (38,53%) |
| Sai | 1.374 |
| Abstain | 470 |
| Điểm đúng − sai | **−218** |
| SQL chạy được / câu đã sinh SQL | 2.645/2.913 (90,80%) |
| Precision khi trả lời thường, theo report | 46,25% |
| Sai giá trị / sai type | 1.123 / 163 |
| Abstain do binder / format-sanity | 201 / 198 |
| Gate chặn nhầm | 61 |
| Accuracy number / percent | 45,59% / 29,07% |
| Accuracy date / list / table | 20,69% / 20,73% / 0/19 |
| Mẫu SFT trước lọc độ dài | 888 từ 24 business |
| Thời gian baseline đầy đủ | khoảng 175 phút, chưa gồm chuẩn bị |
| Prompt trung bình / tối đa | 3.336 / 6.854 token |

SQL chạy được không đồng nghĩa hiểu đúng nghiệp vụ. Lỗi giá trị lớn hơn lỗi cú pháp, nên chỉ tăng
repair hay tăng epoch chưa có cơ sở để cải thiện. Rejection sampling chỉ học các lời giải model
đã làm được; khó tự bổ sung cách làm cho tồn kho, giá vốn, công nợ nếu các lớp dữ liệu đó còn thiếu.
Log gần nhất chỉ có báo cáo tổng hợp; `kaggle_out/` là các lần cũ, có cả dữ liệu tổng hợp.
Không dùng chúng để quy lỗi chi tiết của 3.000 câu mới hoặc khẳng định checkpoint mới tốt hơn.

## Notebook sửa cho lần chạy lại từ đầu trên T4 ×2

Hai entrypoint `notebooks/kaggle_finetune.ipynb` và `notebooks/datamate-qlora-kaggle-fixed.ipynb`
hiện chứa cùng luồng. Push source sửa lên nhánh `BRANCH` (mặc định `main`) trước khi chạy trên Kaggle;
cell đầu lấy source GitHub, nên chỉ upload notebook mà chưa push script sẽ vẫn chạy code cũ.

- Cố định phiên bản vLLM/Transformers/PEFT/bitsandbytes đã ghi nhận ở log trong
  `requirements-kaggle.txt`; vLLM chọn torch tương thích. Đây là mốc tái lập để kiểm tra,
  chưa phải một stack đã chứng minh train thành công. Lưu `environment.txt` gồm cả dependencies gián tiếp.
- `training_options()` dùng `warmup_steps` nguyên, tính theo số mẫu, world size, accumulation và epoch;
  bỏ `group_by_length=False`. Notebook gọi constructor trên CPU **trước baseline** và script kiểm tra
  constructor trước load model. Không âm thầm bỏ qua đối số quan trọng nếu API đổi tiếp.
- 4-bit NF4, FP16, SDPA, checkpointing, mỗi rank gắn đúng GPU; loss chỉ tính SQL và token kết thúc
  của chat template. Không ghép cứng token kết thúc của riêng Qwen. Tắt KV cache khi train.
- Điểm xuất phát: rank 32, alpha 64, dropout 0,05, LR **5e-5**, **2 epoch**, microbatch 1/GPU,
  accumulation 8 → batch hiệu dụng **16**, max length **4.096**. Đây là cấu hình thử thận trọng,
  **không phải siêu tham số tối ưu đã đo**. Chạy smoke test DDP 2 optimizer step trước full train,
  dùng thư mục riêng, bỏ adapter smoke khỏi bước chọn model.
- Mẫu dài hơn max length bị loại toàn bộ; không cắt mất schema/câu hỏi/SQL. Xem `examples`, `dropped`
  và token lengths trong log/`lora/training_summary.json`. Prompt inference có thể dài 6.854 token nên
  ngưỡng 4.096 có nguy cơ loại mất nhóm khó. Chỉ tăng lên 6.144 sau khi đo VRAM thực tế trên T4;
  khi đó phải kiểm tra lại điểm holdout. Không hứa số 888 còn nguyên sau lọc token.
- Builder thực thi lại SQL bằng schema và rulebook hiện tại, format và so gold rồi mới ghi SFT.
  SQL từ log cũ không được mặc nhiên xem là đúng sau khi sửa ingest/formatter/prompt.
- Lưu adapter mỗi epoch, tối đa 2 checkpoint, không lưu optimizer/base FP16 để tiết kiệm disk.
  **Không hỗ trợ resume optimizer từ các checkpoint chỉ có adapter**; log/SFT được lưu riêng
  trong `stage1_sft.zip` để tái sử dụng ở một phiên sau.
- Chấm base và từng checkpoint trên **toàn bộ 6 business giữ lại** (600 câu khi mỗi business có 100 câu).
  Kiểm tra đủ ID, chọn theo `correct - wrong`; hòa điểm giữ base hoặc checkpoint sớm hơn.
  Không dùng train loss để chọn, không dùng public_test để train/chọn hyperparameter.
- `selection.json` ghi đúng/sai/abstain theo checkpoint, tên bản được chọn và config. Nếu chọn LoRA,
  adapter tương ứng được chép ra `lora/adapter_*` và cấu hình inference trỏ đúng checkpoint.
  `report_checkpoint-*.json` cho biết nhóm lỗi nào giảm/tăng.
- Public_test chạy **offline**, hai tiến trình vLLM, TP=1 mỗi GPU; kiểm tra exit code, schema, số dòng
  và tập ID trước khi chép `/kaggle/working/submission.jsonl`. Không có gold nên không đo accuracy tại đây.
  Cuối phiên tải `datamate_results.zip` để đọc checkpoint, logs và cấu hình.

LoRA rank 32 trên 7 lớp tuyến tính của Qwen2.5-Coder-7B thêm khoảng 80,74M tham số;
profile Kaggle LoRA khai báo bảo thủ **7,70B**, vẫn dưới 15B. Hai replica GPU dùng chung một model,
không phải hai model khác nhau. Nếu tăng rank hoặc thêm embedding phải cập nhật khai báo.

## Cách quyết định vòng fine-tune tiếp theo

1. Xác nhận smoke test cả hai rank thành công, loss hữu hạn, có checkpoint và đủ holdout IDs.
2. Đọc `selection.json`: chỉ giữ adapter nếu điểm holdout cao hơn base trên cùng tập câu.
   Nếu epoch 1 hơn epoch 2, chọn epoch 1; không tăng epoch chỉ vì loss train còn giảm.
3. So `wrong_value`, `wrong_type`, `abstain:exec_binder`, `abstain:format_or_sanity` trong report.
   Với số liệu hiện có, ưu tiên sửa liên kết/schema/định dạng và kiểm chứng các view còn thiếu
   trước khi tăng kích cỡ model. Bổ sung lời giải đã thực thi đúng từ **train**, tránh nhân bản câu dễ.
4. Sau khi chốt cấu hình, chạy holdout hai lần để đo tái lập. Notebook không tự tốn một lượt GPU
   lặp lại; test CPU determinism chỉ xác nhận đường mock. Holdout đã dùng chọn checkpoint là validation,
   không phải một ước lượng accuracy hoàn toàn độc lập.
5. Máy chấm 2×5090 khác T4. Chưa có benchmark 6 giờ trên máy đích, chưa triển khai N-candidate voting;
   không xem notebook Kaggle là bằng chứng đạt thời gian hay mức điểm chính thức.

Tham khảo API chính thức:
[TrainingArguments/Trainer](https://huggingface.co/docs/transformers/main_classes/trainer),
[train_sampling_strategy thay cho group_by_length](https://huggingface.co/docs/transformers/trainer_recipes).
