# 09. Mô hình và công nghệ

## Ràng buộc
- Tổng tham số mọi mô hình lúc suy luận ≤ **15B** (LLM + embedding + reranker + classifier; MoE tính toàn bộ tham số).
- Trọng số phải công khai trước 01/10/2026, giấy phép cho phép dùng; có thể fine-tune; cho phép lượng tử hóa.
- Khai báo mô hình trong README. Code tự kiểm tra qua `configs/models.yaml`.

## Cấu hình đề xuất (placeholder, cần xác nhận)
| Vai trò | Gợi ý | Tham số xấp xỉ |
|---|---|---|
| LLM sinh code | Qwen3-8B (hoặc Qwen2.5-Coder-7B) | 7–8B |
| Embedding | BGE-M3 | ~0,6B |
| Tổng | | ~9B (còn dư ~6B) |
Phương án lớn: một LLM ~14B (Qwen3-14B) nhưng gần chạm trần, gần như không còn chỗ cho embedding. Hai LLM lớn cùng lúc không đủ ngân sách.
Hãy kiểm tra số tham số chính xác, ngày phát hành và giấy phép từng mô hình trước khi chốt.

## Serving
- **vLLM** offline engine, CUDA ≥ 12.8 và bản PyTorch/vLLM tương thích Blackwell.
- 2 GPU: ưu tiên **data parallel** (mỗi GPU một bản mô hình, chia câu hỏi) nếu mô hình vừa 32 GB; ngược lại tensor parallel.
- Lượng tử hóa (AWQ/GPTQ/FP8) để tăng thông lượng.
- Guided decoding để ép dạng đầu ra.
- Prefix caching cho phần prompt chung (schema, rulebook).

## Fine-tuning (tùy chọn)
- LoRA trên cặp (ngữ cảnh → code) thu bằng **rejection sampling**: sinh code cho câu train, chỉ giữ code chạy ra đúng đáp án tham chiếu.
- Chỉ dùng dữ liệu train/tự sinh/công khai; **tuyệt đối không dùng public/private test**.

## Các công nghệ khác
DuckDB, pandas, openpyxl, rapidfuzz, unidecode, sqlglot, Pydantic, pytest, Docker.

## Backend mock
`llm/mock_backend.py` cho phép chạy test và pipeline trên CPU không cần mô hình.

## Cài đặt baseline

Phụ thuộc Python được tách thành:

- `requirements.txt`: stack CPU/Windows, gồm DuckDB, xử lý bảng, validation,
  Transformers, Sentence Transformers và mock/test tooling.
- `requirements-gpu.txt`: tuỳ chọn cho Linux/CUDA, cài thêm vLLM và các gói
  phục vụ fine-tune. Không cài file này trên Windows.

`configs/models.yaml` là nguồn khai báo duy nhất cho model ID, đường dẫn local
và số tham số. `pip` không tải model weights; weights phải được chuẩn bị sẵn
trong image hoặc thư mục local trước khi chạy offline. Baseline mặc định dùng
`mock` backend và tắt các model thật để có thể kiểm thử không cần GPU hay mạng.
