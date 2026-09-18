# Audit trước thay đổi deployment

- Frontend: frontend/index.html, app.js, style.css; JavaScript thuần, không package.json, React hoặc Vite.
- Backend: server.py, Python stdlib HTTPServer; requirements.txt chỉ NumPy. Không Flask/FastAPI/Node.
- Optimizer: lns/core.py (thuật toán gốc), lns/adapter.py; worker ProcessPoolExecutor trong road_network/jobs.py.
- Map: data/raw/hcm_map4.osm, 11,898,698 bytes. Parser chuẩn hóa node/cạnh có hướng; SVG tự vẽ trong trình duyệt. Không Leaflet, tile layer hoặc CDN, nên invalidateSize và lỗi khởi tạo Leaflet không áp dụng.
- Dataset: data/presentation_scenario.json, scenario_validation.json, example_request.json, mock.json. Demo dùng presentation_scenario; không dùng mock để tối ưu.
- road_network/: loader, store, routing, costs, incidents, telemetry, reoptimization; data/processed là output tùy chọn, không cần triển khai.
- tests/: Python unittest và Node test runner; tools/: extraction, scenario design. Không chạy các tool thiết kế lại dataset khi build/deploy.
- CSS/JS dùng URL gốc /style.css, /app.js; fetch qua boundedFetch với đường dẫn /api/... cùng origin. Không có localhost hoặc đường dẫn C:/D: trong runtime frontend. Tài liệu và bài kiểm tra có đường dẫn local tham khảo; không đưa vào runtime.
- API GET: /api/health, /api/network, /api/network/metadata, /api/network/geojson, /api/network/routing-profile, /api/demo-scenario, /api/presentation-scenario, /api/simulation?session_id=..., /api/jobs/{id}, /example.json.
- API POST: /api/optimize, /api/network/routes, /api/simulation, /api/incidents, /api/reoptimize, /api/jobs/initial, /api/traffic/inject, /api/traffic/telemetry, /api/traffic/applied.
- Dynamic loading: network/scenario/session JSON và job polling; không import module từ CDN.
- file:// không chạy được vì đường dẫn / trỏ về filesystem root, không có HTTP API cho /api/..., và fetch bị giới hạn bởi origin trình duyệt. Cần web server, không mở HTML trực tiếp.
- Deployment blockers: chỉ bind 127.0.0.1, port cố định, raw map bị gitignore, chưa có /health/config môi trường/CORS/build/deployment manifest. HTML có thẻ đóng sai do chỉnh tay. Các lỗi UI thiếu zoom/decision-scope đã được xử lý trước đó.
- Git: toàn bộ project đang untracked; chưa có remote. Không reset, xóa lịch sử hoặc ghi đè thuật toán.
- Chọn Render một service phục vụ frontend + API: ít cấu hình, không cần CORS cho phương án mặc định. HTTPS do Render cung cấp. Giữ nguyên thuật toán, payload và dataset.
