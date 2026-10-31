# Tài liệu DataMate — Mục lục

| File | Nội dung |
|---|---|
| 00_overview.md | Bài toán, đầu vào/đầu ra, cách chấm điểm, ràng buộc |
| 01_architecture.md | Kiến trúc tổng thể, luồng dữ liệu, nguyên tắc thiết kế |
| 02_ingest_profile.md | Bước 1: nạp dữ liệu, profiling, rulebook, calendar |
| 03_question_understanding.md | Bước 2: chuẩn hóa teencode/typo + Temporal Resolver |
| 04_entity_schema_linking.md | Bước 3: nối từ trong câu hỏi với giá trị/cột thật |
| 05_answerability_gate.md | Bước 4: quyết định có trả lời được không |
| 06_code_generation.md | Bước 5: sinh SQL/Python, prompt, few-shot, N ứng viên |
| 07_execution_repair.md | Bước 6: sandbox, tự sửa lỗi |
| 08_voting_formatting.md | Bước 7-8: bỏ phiếu, định dạng đáp án |
| 09_models.md | Lựa chọn mô hình, ngân sách 15B, serving |
| 10_evaluation_data.md | Đánh giá, dữ liệu tự sinh, đo từng bước |
| 11_deployment_runtime.md | Docker, predict.sh, time guard, tái lập |
| 12_roadmap.md | Lộ trình thực hiện và rủi ro |
| 13_baseline.md | Baseline chạy được và giới hạn hiện tại |
| 14_phase2.md | Phase 2: Question Understanding, cách chạy, mở rộng, hạn chế |
| 15_phase3.md | Phase 3: lớp ngữ nghĩa chuẩn, Entity/Schema Linking, gate luật |
| 16_phase4_p0.md | Phase 4 / P0: chat template, parser SQL, prompt gọn, báo cáo theo bước |
# Baseline implementation

See [13_baseline.md](13_baseline.md) for the runnable baseline and current boundaries.
