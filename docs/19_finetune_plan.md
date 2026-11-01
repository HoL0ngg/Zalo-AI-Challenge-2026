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

Chưa làm trong repo: bước 3–4 (cần log LLM thật trên dữ liệu chính thức) và pass N ứng viên + vote (`voting/` vẫn là `vote_stub`).
