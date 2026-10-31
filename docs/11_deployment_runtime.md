# 11. Triển khai và vận hành

## Docker
- Base image có CUDA ≥ 12.8 (dùng image chính thức theo Docker guideline của BTC).
- Chứa: source code (huấn luyện và suy luận), trọng số mô hình, `predict.sh`, README.
- Cài đặt phụ thuộc **lúc build**; không `pip install`/tải mô hình lúc chạy.
- Đặt `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`. Container chạy không mạng.

## predict.sh
1. Đọc test từ `/data`, ghi `/result/submission.jsonl` và `/result/logs/`.
2. Đặt seed và biến môi trường offline.
3. Gọi `python -m datamate.cli run --data-dir /data --result-dir /result`.
4. Luôn thoát an toàn sau khi flush, in tóm tắt (số câu đã trả lời / unanswerable / abstain / thời gian).

## Time guard
- Ngân sách tổng (mặc định ~5h30m, chừa biên an toàn dưới 6h, đã tính thời gian nạp mô hình).
- Theo dõi tốc độ trung bình; khi thời gian còn lại không đủ → các câu còn lại ghi `abstain` ngay.
- Có thể giảm N ứng viên/vòng sửa khi gần hết giờ (chế độ nhanh).

## Resume
Nếu chạy lại, bỏ qua các id đã có trong `submission.jsonl` (không trùng dòng).

## Logs
Mỗi câu một bản ghi: id, câu gốc và câu chuẩn hóa, khoảng thời gian đã giải, thực thể nối, code sinh ra, kết quả thực thi, kết quả bỏ phiếu, đáp án cuối, thời gian. BTC dùng log để đối chiếu khi hai lần chạy khác nhau.

## Danh sách kiểm tra trước khi nộp
- [ ] Tổng tham số ≤ 15B, README khai báo đủ mô hình.
- [ ] Chạy offline thành công (container không mạng).
- [ ] Toàn bộ test chạy trong < 6 giờ trên máy tương đương (kể cả nạp mô hình).
- [ ] `/data` chỉ đọc vẫn chạy được.
- [ ] Hai lần chạy lệch ≤ 0,03 trên dev.
- [ ] Không có hard-code theo id; test no-hardcoding pass.
- [ ] Log đầy đủ trong `/result/logs/`.

## Chạy thử trên Kaggle GPU (smoke test, không phải benchmark)
Kaggle cho T4 x2 (16 GB/card, không có bfloat16) hoặc P100, khác xa máy chấm 2 x RTX 5090.
Chỉ dùng để xác nhận pipeline chạy được với LLM thật, không dùng để đo mốc 6 giờ.

- Notebook mẫu: `notebooks/kaggle_run.ipynb` (clone repo → trọng số → cài đặt → test mock → chạy vLLM trên `dataset/train` → chấm).
- Cấu hình: `configs/kaggle.yaml` (backend `vllm`) và `configs/models_kaggle.yaml`
  (Qwen2.5-Coder-7B-Instruct-AWQ, `float16`, `quantization: awq`, `max_model_len: 8192`).
  File config phải nằm trong `configs/` vì `runner.py` suy ra gốc repo từ vị trí file này;
  `local_path` được nối từ gốc repo.
- Trọng số: tải một lần bằng `huggingface_hub.snapshot_download` rồi lưu thành Kaggle Dataset;
  các lần sau add làm Input, symlink vào `models/qwen-coder-awq` và chạy offline.
- `llm/vllm_backend.py` đọc thêm `quantization`, `tensor_parallel_size`, `max_model_len`,
  `gpu_memory_utilization`, `max_num_seqs`, `enforce_eager` từ khai báo mô hình (chỉ truyền khi có khai báo).
  `enforce_eager` mặc định bật để tránh bước capture CUDA graph hay lỗi trên T4; tắt trên máy chấm để tăng tốc.
- **2 GPU (data parallel)**: `python -m datamate.runtime.dataparallel --config configs/kaggle.yaml --data-dir dataset/train --result-dir <dir> --gpus 0,1`
  (notebook cell 8a–8c). Mỗi GPU một tiến trình `datamate run` (`CUDA_VISIBLE_DEVICES`, `tensor_parallel_size: 1`), chia **theo business** (cân bằng theo số câu, thứ tự cố định,
  không phụ thuộc đồng hồ); kết quả được gộp lại đúng thứ tự `questions.jsonl`. Dữ liệu từng shard được **copy** vào `<dir>/.shards/in_*` (loader từ chối symlink ra ngoài gói) rồi xóa
  sau khi chạy; log từng shard ở `<dir>/.shards/shard_*.log`. Pipeline vẫn tuần tự trong mỗi tiến trình, nên đây mới là bước đầu của W2 (Phase 5), chưa phải batch.
  Không dùng tensor parallel cho 5090 (không NVLink).
- Ghi kết quả vào `/kaggle/working`, không ghi vào `/kaggle/input` (read-only, tương đương `/data`).
- Không gọi `scripts/predict.sh` trên Kaggle (cứng `/data`, `/result`); gọi `python -m datamate.cli run` với `--data-dir`/`--result-dir`.
- Prompt hiện chưa dùng chat template của Qwen Instruct nên đáp án sẽ phần lớn sai; mục tiêu giai đoạn này chỉ là chạy thông.
